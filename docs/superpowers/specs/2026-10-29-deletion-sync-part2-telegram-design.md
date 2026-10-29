# Deletion sync Part 2: Telegram review of held batches

Supersedes the "Part 2 — Telegram" section of `2026-10-28-deletion-sync-design.md`. Part 1 (detection, breaker,
execution, CLI resolver) is unchanged except where this document says so.

## Intent

When the circuit breaker holds a batch of deletions, the user reviews it from their phone: sees thumbnails, marks
the few photos they did not mean to delete, and sends the rest to iCloud Recently Deleted. The user wants this
working before enabling deletion sync on their homelab, so the first upgrade is a good experience.

The control channel built here is the start of icloudpd's future control plane: the unauthenticated web UI
(2FA, password, resume/cancel) migrates onto it later. Its shape must make that migration routine, and it must be
multi-account native from the first line, not retrofitted.

## Goals

- A held batch reaches Telegram as one reviewable message with thumbnails.
- Per-photo "keep" before approving. Kept photos re-download to the local library on the next scan.
- Every route, button, message and lock is keyed per account and library. No "current user" anywhere.
- No iCloud session or secret ever leaves icloudpd. The bot gets image bytes, never iCloud URLs or cookies.

## Non-goals

- Migrating the web UI's 2FA/password/resume endpoints (later project; this design only must not block it).
- Browser login for the control channel (later; see "Auth").
- Any change to detection, debounce, threshold semantics or execution timing.
- Per-photo keep in the CLI. The CLI stays whole-batch (`--resolve-deletions approve|reject`).

## Anti-goals (failure even if it "works")

- Deleting a photo the user never had the chance to see in the message they tapped.
- A button that acts on the wrong account or library.
- Two code paths that write the same account's cookie/session files at the same time.
- Any Telegram message for deletions under the threshold. Those stay silent (user decision).

## Constraints

- Telegram `callback_data` is at most 64 bytes.
- A Telegram media album (`sendMediaGroup`) cannot carry buttons.
- Rich messages (Bot API 10.1, June 2026; collage block in 10.2) can carry a collage, per-photo captions and an
  inline keyboard in one message, and are edited in place with `editMessageText(rich_message=…)`. aiogram 3.31.0
  supports them; the bot pins 3.29.1 today.
- icloudpd keeps no iCloud session between scans today: `core_single_run` builds one via `authenticator()`
  (`base.py:1255`) per scan and drops it.
- The bot has no iCloud session and must not get one.
- Production: one Telegram chat in `allowed_chat_ids`; bot and icloudpd on one Docker network.

## Decisions (made with the user, 2026-10-29)

1. **Review UI = one rich message per held batch per entry.** Header line (count, account, library, threshold),
   collage of up to 10 thumbnails each captioned with its number in the batch, then inline keyboard:
   two rows of five toggles (`🗑 7` / `💾 7`), `◀ Prev` / `Next ▶`, and `✅ Delete N, keep M` / `❌ Keep all`.
   Paging edits the same message. Spiked live on the user's phone on 2026-10-29, both with public URLs and with
   uploaded files (`attach://`); the user approved the look.
2. **Under-threshold deletions send nothing to Telegram.** The bot ignores `deletion_sync_summary`.
3. **Keep = re-download.** A kept photo is rejected (Part 1 `reject` semantics for that record): its
   `missing_since` clears and it downloads on the next scan. "Keep all" = reject the whole batch.
4. **Control channel = authenticated HTTP listener inside icloudpd** (approach below), on these terms:
   same stack as the web UI (Flask + waitress, own thread, own port); versioned routes (`/v1/…`); routes address
   an entry explicitly; wired to live in-process state, not only `state.db`; auth is one hook that can later take a
   second scheme.
5. **Session registry.** One live iCloud session per account, shared by scans and the control channel, with a
   per-account lock (details below).
6. Approve on next completed scan, debounce, cumulative breaker: unchanged from Part 1.

## Approaches considered

- **Chosen: control channel in icloudpd; bot pulls pages and thumbnails, writes decisions back.** Thumbnails are
  fetched per page on demand with a live session, which also removes the Part 1 spec's "do thumbnail URLs expire
  while a batch sits for days" risk. Cost: no thumbnails while an account's session is invalid (text fallback).
- Rejected: icloudpd pushes all thumbnails to the bot when the breaker trips. A 300-item batch means hundreds of
  downloads up front, and decisions still need a path back, so it needs the same channel anyway.
- Rejected: bot reads/writes `state.db` over a shared volume. Couples the bot to icloudpd's schema, and the bot
  still has no session for thumbnails.
- Session sub-choice. Rejected: control channel opens its own session from the cookie files. Two live sessions for
  one account can both rewrite the same cookie/session file (silent logout risk), and the web UI migration would
  need the registry anyway.
- UI sub-choice. Rejected: numbered media album plus a separate button message (two bubbles, ten edits per page,
  numbers drawn onto images). Rejected: one-photo-at-a-time viewer (too slow for big batches). Rejected:
  whole-batch only (clumsy for the two-strays case the user cares about).

## Session registry

- A process-wide registry maps **username → session slot**. A slot holds the current `PyiCloudService` (or none)
  and one `threading.RLock`.
- Scans keep calling `authenticator()` exactly as today (same validation, 2FA, session-expiry check), but under the
  account's lock, and publish the result into the slot. A failed or invalid authentication clears the slot.
- Every HTTP request the session makes takes the account's lock (at the session's request layer), so a thumbnail
  fetch waits at most one in-flight request, never a whole scan. *(My call: per-request locking, because
  holding the lock for a whole scan would block review for hours.)*
- The control channel never prompts for a password and never triggers 2FA. It uses the slot's session as is.
  When iCloud rejects it (e.g. 421/450/401 on a thumbnail call), the control channel may
  attempt **one token-only refresh** under the account's lock: re-validate using the stored session token only,
  the same first step a scan's login takes, with no password provider and no MFA. Success → publish the refreshed
  session into the slot. Anything that would need a password or 2FA → give up, leave the slot empty, thumbnails
  unavailable until the next scan logs in. An empty slot has nothing to refresh and simply means "no
  thumbnails yet"; every process start runs a scan that fills it. *(User decision, 2026-10-29.)* Refresh attempts are rate-limited per
  account (at most one per 10 minutes, *my call*) so a broken session can't hammer Apple.
- Context for the above: production scans once every 24 h, so reviews routinely use a session up to a day old.
  On 2026-10-29 the session/Photos cookies, written 20.4 h earlier, still had ~700 h to expiry; server-side
  validity is unmeasured (see Verification, manual).
- Two entries for one account (PrimarySync + SharedSync) share one slot.
- Future web UI 2FA endpoints land on the same registry, keyed by username, replacing `StatusExchange`'s single
  "current user". Not built now.

## Control channel

**Enablement.** Off unless global `control_token_file` is set. Token read from that file at startup; never from an
env var or the config file. Binds `0.0.0.0` on `control_port` (default **2012**, *my call*: next to the web UI's
2011 and distinct from it). Listener absent when no token file is set.

**Auth.** Every request needs `Authorization: Bearer <token>`, compared in constant time; otherwise 401. Implemented
as one `before_request` hook that resolves "who is calling", so a later browser scheme (login → session cookie +
CSRF) adds a branch there without touching routes. Building the browser scheme now is out of scope.

**Entry keys.** Each config entry gets a short key: first 8 hex chars of `sha256(username + "\0" + library)`.
Stable across restarts; fits in `callback_data`. Startup fails on a collision (vanishingly unlikely, but checked).

**Batch token.** A short hash (8 hex) of the sorted record names currently `held` for that entry. Every page
response includes it; every write that acts on the batch must send it back. Mismatch → 409 with the current token.
This is what guarantees "delete only acts on what you saw".

**Routes** (JSON unless noted; exact field names are the builder's):

- `GET /v1/entries` → every configured entry: `key`, `username`, `library`, `held_count`, `tripped`.
- `GET /v1/entries/<key>/held?page=N` → `batch_token`, `page`, `pages`, `total`, `kept_count`, and up to 10 items:
  `number` (1-based position in the batch), `record_name`, `filename`, `asset_date`, `is_video`, `keep`.
  Order is stable: `detected_utc`, then `record_name`.
- `GET /v1/entries/<key>/held/<record_name>/thumbnail` → `image/jpeg` bytes, or 503 when the account's slot is
  empty or iCloud fails. Nothing written to disk.
- `POST /v1/entries/<key>/held/<record_name>/keep` `{keep: bool, batch_token}` → updated page counts.
- `POST /v1/entries/<key>/resolve` `{action: "apply" | "keep_all", batch_token}`.
  `apply`: in **one** write transaction, approve every held item not marked keep and reject every marked one.
  `keep_all`: reject all. Both go through Part 1's `resolve()` logic (extend it to take both sets in one
  transaction rather than reimplementing). Returns counts.
- Unknown key → 404. Entry without `sync_deletions` → 404.

**Writes during a scan.** A running scan holds a write transaction on `state.db` (manifest batching), so `keep`
and `resolve` can't take their write lock until it ends. They use the existing busy timeout and then return 503
`{"reason": "syncing"}`; the bot answers the tap with "icloudpd is syncing, try again in a minute" and changes
nothing. Reads (pages, thumbnails) are unaffected. *(My call: production scans take 5–35 s once a day, so no
change to journal mode or Part 1 batching.)*

**State.** Additive column `deletion_items.keep_marked INTEGER NOT NULL DEFAULT 0`, migrated like Part 1's additive
changes. Cleared when the item leaves `held`. The CLI resolver ignores it (whole batch). The listener opens its
own SQLite connection per request.

## Thumbnails

- Per page, icloudpd looks up that page's records in one `records/lookup` call through the registry session and
  downloads each item's smallest **JPEG** derivative.
- **Builder's first check (can change the design):** a video's `THUMB` maps to `resVidSmall`, a video, not a JPEG
  (`src/pyicloud_ipd/services/photos.py:799`). Find the JPEG poster field on a real video record (likely
  `resJPEGThumb…` on the master record) before building on it. Photos: confirm the same field exists for HEIC,
  RAW and Live Photos.
- Videos show their poster frame with `▶` in the caption.
- Any thumbnail that fails → the tile shows a neutral placeholder image with the same number. Whole page fails
  (slot empty) → the message renders as a numbered text list (filename + date) with the same buttons, plus a line
  saying thumbnails return after the next successful login.

## Bot

- Config: `ICLOUDPD_CONTROL_URL` and `ICLOUDPD_CONTROL_TOKEN_FILE` (the raw `ICLOUDPD_CONTROL_TOKEN` env var is
  rejected, matching existing secret handling). Bump aiogram to 3.31.0.
- `deletion_sync_threshold_tripped` → look up the entry key via `GET /v1/entries` (match `username` + `library`
  from the event), fetch page 1 and its thumbnails, upload them as `attach://` files in one `sendRichMessage`.
  Sent to every allowed chat.
- When the batch grows (a new tripped event for the same entry), the bot sends a fresh message and edits its
  previous message for that entry, if it still knows its id, to "Superseded, see the newer message" without
  buttons. *(My call.)*
- `callback_data` format: `ds:<entrykey>:<op>:<page>:<arg>:<batchtoken>`; worst case well under 64 bytes.
  The bot keeps no review state: every tap carries what it needs, so a bot restart doesn't break open messages.
- Toggle → `POST keep`, redraw keyboard and header counts. Prev/Next → fetch page, edit the message with new
  thumbnails. 409 on any action → redraw the current page with the fresh token and answer the tap with
  "The batch changed, nothing was deleted. Here's the updated batch."
- After `apply`: edit the message to a final state without buttons, e.g. "39 will be deleted at the next sync.
  3 kept, re-downloading." After `keep_all`: "Nothing deleted. 42 photos will re-download at the next sync."
- `/held` command: lists entries with a held batch and re-sends a review message for each. *(My call: this replaces
  the Part 1 spec's `/approve <account> <library>` and `/reject …` commands. Approving through a command would act
  on photos the user didn't see, which conflicts with the anti-goal. The CLI remains the no-thumbnail path.)*
- `deletion_sync_summary` → ignored.
- Existing `allowed_chat_ids` enforcement applies to every new handler, callbacks included.

## Verification

Automated (fake library / recorded responses, repo's existing test style; bot tests in its own suite):

- No token file → no listener. Missing or wrong token → 401 on every route. Constant-time compare used.
- Two accounts, three entries (one account with Primary + Shared): `/v1/entries` lists all three with distinct
  keys; actions on one key never touch another entry's `state.db`.
- Paging is stable across requests; numbers continue across pages (page 2 starts at 11).
- `apply` with marks: kept items `rejected` with `missing_since` cleared, others `approved`, `tripped` cleared,
  all in one transaction. Then next scan: approved deleted, kept re-downloaded.
- Stale `batch_token` (a scan added an item) → 409, nothing changed.
- Registry: a thumbnail fetch during a scan waits only for the in-flight request. Rejected session → one
  token-only refresh, then success or 503; a refresh never invokes a password provider or MFA; second failure
  within 10 minutes doesn't retry.
- `keep`/`resolve` while a scan holds the write lock → 503 `syncing`, nothing changed; bot shows the retry text.
- Bot: tripped event → one `sendRichMessage` with collage + keyboard; toggle/page/apply/keep_all each produce the
  right control call and edit; 409 redraws; callback from a chat not in `allowed_chat_ids` ignored;
  `deletion_sync_summary` sends nothing; every `callback_data` ≤ 64 bytes for the longest realistic key/page.

Manual, live, before enabling on the homelab:

- Video and photo thumbnails render in the collage on the user's phone.
- Session age: open a held batch ~20 h after the last scan; record whether the existing session worked, needed the
  token-only refresh, or fell back to text.
- Batch over 10: page both directions; mark 2; apply; confirm next scan deletes the rest (Recently Deleted) and
  re-downloads the 2.
- Bot restart with a review message open → buttons still work.

## Left to the builder

- Exact JSON field names, error body shape, and the neutral placeholder image.
- Where the registry lock hooks into `PyiCloudSession` and how `core_single_run` publishes into the registry.
- The JPEG thumbnail field (first check above).
- Test doubles for the registry session and Telegram API.
- README, bot README and `docker-compose.example.yml` updates (new env vars, token file, port).
