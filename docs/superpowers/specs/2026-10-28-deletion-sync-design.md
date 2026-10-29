# Deletion sync: local deletions → iCloud Recently Deleted

Status: design, awaiting approval. Issue #5.
Sources this design carries forward: issue #5's comments (Python-era decisions) and the
"Deletion-mirroring (#5)" / "Deletion-sync review surface" sections of
`go-rewrite-spike:docs/superpowers/specs/2026-08-14-go-rewrite-design.md`. The Go rewrite is
shelved; this ports its deletion-sync design to the Python implementation.

Ships in two parts, each plannable and shippable on its own:

- **Part 1 — CLI.** Detection, circuit breaker, held batches, `--resolve-deletions`, notification events.
- **Part 2 — Telegram.** A new authenticated control channel, approve/reject from the bot, thumbnail review.

## Intent

icloudpd downloads into directories Immich watches as external libraries. Deleting a photo in
Immich should delete it from iCloud too, on the next sync. Today nothing flows back: the user
has to delete the same photo twice.

The user also uses the iCloud Shared Library, so this must work for both the personal library
and the Shared Library.

## Goals

- A photo whose local files were deleted is moved to iCloud's Recently Deleted.
- Off by default, opt-in per config entry.
- A glitch (a dropped mount, a half-synced share, a config change) never deletes photos from iCloud.
- Large batches stop and wait for a human; small ones run unattended.
- Works for any library a config entry targets, including the Shared Library (`SharedSync-…` zone).

## Non-goals

- **Undo/restore.** Technically possible (same `records/modify` call with `isDeleted: 0`), deliberately
  excluded: iCloud's Recently Deleted already covers regret. Do not add it.
- **One run covering several libraries.** Each library stays its own config entry (see "Multiple libraries").
- **Per-item approval.** Approve/reject is all-or-nothing per held batch.
- **Retiring the web UI.** Part 2 builds the channel that will replace it, but moving 2FA off the web UI and
  deleting it is a separate follow-up project.

## Anti-goals (failure even if it "works")

- Any path where a scan that could not see the files (unmounted volume, missing manifest) proposes deletions.
- Changing `folder_structure`, `file_match_policy`, `live_photo_mov_filename_policy`, or similar settings
  produces deletion candidates. A path change must cause a re-download, never a delete.
- A mutating action reachable without authentication. The current web UI's unauthenticated POST endpoints
  must not gain any deletion action.
- A slow leak (a few false "missing" files per night, each run under the threshold) deleting indefinitely
  without ever tripping the breaker.

## Constraints

- **Immich only removes the file when its trash is emptied**, and only on a read-write mount. On a
  read-only (`:ro`) mount the file never disappears, so nothing syncs. With Immich's default trash
  retention, the iCloud delete lands when Immich empties its trash, not when the user clicks delete.
  Document this in the README. (Immich FAQ, "How are deletions of files handled in external libraries?")
- **Shared Library deletes affect every participant.** The item goes to Recently Deleted for everyone and
  the contributor is notified. A wrong bulk delete is visible to other people.
- **Deleting in a `SharedSync` zone is unverified.** `delete_photo()` posts to the library's own `zone_id`,
  which should be correct, but no one has confirmed it works against a shared zone. Part 1 includes a
  manual live test on one throwaway photo before the feature is used against the Shared Library.
- The manifest (`src/icloudpd/manifest.py`) is best-effort: failures are logged and swallowed. Deletion
  sync cannot be best-effort. With `sync_deletions` on, a manifest that fails to open or write is a
  hard error for that entry's run, not a warning.
- Config entries run sequentially in one process; each entry (one account + one library + one directory)
  has its own manifest database.

## Decisions (made with the user, 2026-10-28)

| Decision | Choice | Why |
|---|---|---|
| Debounce | **Two scans.** A photo must be missing on one scan and still missing on a later completed scan before it becomes a candidate. | Absorbs one-off glitches. Cost: deletes reach iCloud one sync later. |
| When an approved batch executes | **On the next scan**, not immediately. | Every full scan re-fetches each photo, refreshing its `recordChangeTag` for free. Immediate execution would need a per-record lookup call this codebase has never used. |
| Part 2 bot → icloudpd channel | **A new authenticated control channel**, used only by deletion commands at first. | The user wants the web UI gone; building deletion actions on it would deepen the dependency. |
| Scope split | Part 1 CLI, Part 2 Telegram. | Ship the CLI fast; Telegram builds on the same held-batch state with no rework. |

Carried forward unchanged from issue #5 / the Go design:

- Detection happens **inside the download loop**, not as a separate end-of-run pass. A separate pass loses
  the "auto-heal race": the loop would re-download the deleted file before the pass saw it was gone.
- An asset counts as deleted only when **all** of its recorded files are missing (Live Photo pair, multiple
  `--size` copies, RAW+JPEG).
- **Circuit breaker, cumulative.** `deletion_sync_threshold`: `-1` = no cap (rclone `--max-delete`
  semantics), positive `N` = hold for review once the cumulative count reaches `N`. No recommended default.
- At/above threshold: **zero** deletions execute, the whole batch is held, and it **stays held across runs**
  until resolved. New candidates on later runs **merge into the same batch**.
- **Held items are not re-downloaded** while undecided. Resolving is the only way out.
- `--resolve-deletions={approve,reject}` is one enum flag, never two booleans.
- Truncated scans can't see everything: `sync_deletions` is rejected at startup with `recent` or `until_found`.

## Approaches considered

**Detection.** (a) End-of-run diff of manifest vs. filesystem — rejected: loses the auto-heal race, and any
truncated scan floods false candidates. (b) In-loop detection — **chosen**.

**Approval timing.** (a) Next scan — **chosen**, see above. (b) Immediate, via per-record lookup — rejected
for v1: unverified API, and it would also be needed to re-verify stale tags.

**Part 2 channel.** (a) Token-protected endpoints on the existing web UI — rejected: the user wants the web UI
retired. (b) **New authenticated control listener** — chosen, designed to become the web UI's replacement.
(c) Kill the web UI first — rejected: delays Telegram approval behind a much larger 2FA migration.

---

# Part 1 — CLI

## Configuration

New per-entry fields (UserConfig; available under `all_users` / `users[]` in YAML and as CLI flags):

| Field | CLI | Default | Meaning |
|---|---|---|---|
| `sync_deletions` | `--sync-deletions` | `false` | Master switch. Off = nothing detected, nothing held, nothing deleted. |
| `deletion_sync_threshold` | `--deletion-sync-threshold N` | `-1` | `-1` no cap; `N ≥ 1` hold once the cumulative count reaches `N`. `0` is rejected. |

New global (run-mode) flag: `--resolve-deletions {approve,reject}` (see "Resolving a held batch").

Startup validation, per entry with `sync_deletions: true`:

- **Reject** if `recent` or `until_found` is set (truncated scans miss deletions).
- **Reject** if `require_mount_marker` is false. *(Builder call, made here: the `.mounted` marker from #35 is
  the liveness gate. Without it an unmounted volume can look like an empty library. Requiring it is cheap and
  closes the classic rsync footgun.)*
- **Warn** (don't block) if `deletion_sync_threshold` is `-1`: that is almost always an unedited default.
- **Warn** if `state_directory` is unset: the manifest then lives inside the media directory and disappears
  with it. *(My call: warn, not reject, because the marker gate already prevents the unmounted case.)*
- **Reject** if two entries resolve to the same `state.db` path, counting the default
  `<directory>/.icloudpd/state.db` as well as an explicit `state_directory`. Today's
  `_has_shared_state_directory` (`base.py:269`) only compares explicit `state_directory` values, so two entries
  sharing a `directory` with no `state_directory` slip through. Deletion state is per database, so sharing one
  would mix two libraries' held batches and trip flags. *(My call: reject, and the error says to give each
  entry its own `state_directory`.)*
- `--dry-run` with `sync_deletions` **writes no deletion state** (`missing_since_utc`, `deletion_items`,
  `deletion_state` stay unchanged). It logs what a real scan would do: assets fully missing now ("would become
  candidates after one more scan"), existing candidates ("would delete" or "would hold"), and whether the
  breaker would trip. No events fire. *(My call: a dry run must never move a real run closer to deleting.)*
- Other options stay compatible: `auto_delete`, `delete_after_download`, `keep_icloud_recent_days`,
  `skip_created_before/after`, `albums`, `skip_videos/photos`. Filters only shrink the set of photos visited,
  and in-loop detection only ever judges photos it visits, so they can cause missed deletions but never
  false ones.

## State (manifest database)

All state lives in the entry's existing `state.db`. Schema changes are additive (`CREATE TABLE IF NOT
EXISTS`, `ALTER TABLE … ADD COLUMN` guarded by a column check).

`downloaded_assets` gains:

- `missing_since_utc TEXT NULL` — set the first scan an asset is judged fully missing; cleared when any of its
  files is seen again.

New table `deletion_items` (one row per asset in the deletion pipeline):

| Column | Notes |
|---|---|
| `record_name` PK | |
| `filename` | for humans (logs, CLI listing, Telegram) |
| `asset_date_utc` | for humans |
| `detected_utc` | when it became a candidate |
| `status` | `held`, `approved`, `rejected`, `deleted`, `skipped_gone`, `skipped_reappeared`, `failed` |
| `status_changed_utc` | |
| `record_change_tag` | latest seen; refreshed every scan |

New table `deletion_state` (single row): `tripped INTEGER`, `tripped_utc`, `last_notified_count`.

Rows in terminal states (`deleted`, `skipped_*`) are kept for 30 days for the cumulative window and audit,
then pruned. *(My call; the exact retention is the builder's.)*

## Detection (in the download loop)

At the start of processing each asset in `download_builder` (`src/icloudpd/base.py:651`), when
`sync_deletions` is on:

1. Compute the paths this run would write for the asset (the same logic the loop already runs), **including
   the variants the loop already checks**: the `-<size>` suffixed path under `NAME_SIZE_DEDUP_WITH_SUFFIX`, and
   the legacy `-original` path. The manifest records whichever variant was found, so matching only the plain
   name would make those assets never become candidates.
2. Load the asset's manifest rows (`manifest.get_all_for_asset`).
3. The asset is **fully missing** only if **all** of:
   - it has at least one manifest row, **and**
   - at least one of this run's computed paths matches a manifest row (so the naming rules haven't changed
     under it), **and**
   - every manifest row's path is absent on disk.
4. If it is not fully missing: clear `missing_since_utc`, and carry on with today's behavior (download any
   individually missing piece, e.g. one half of a Live Photo pair).
5. If it is fully missing and `missing_since_utc` is null: set it, **skip downloading**, and move on. (Suspect.)
6. If it is fully missing and `missing_since_utc` was set by an earlier, completed scan: it is a **candidate**.
   Upsert a `deletion_items` row (status per "Circuit breaker" below), refresh its `record_change_tag`, skip
   downloading.

Held items (`status = held` or `approved`) are never downloaded. `rejected` items fall through to normal
download.

Rule 3's second condition is what makes a naming-setting change safe: none of the new computed paths have
rows, so the asset is downloaded under its new name instead of deleted.

"Completed scan" = the enumeration for that entry ran to the end without cancellation or an exception. A
scan that didn't complete does not count toward the two-scan debounce, and executes nothing. *(My call.)*

## Circuit breaker

Evaluated **once, after the scan completes**, never mid-scan.

- **`approved` items bypass the breaker.** They execute at the end of the next completed scan however large
  the batch. A human already decided; re-holding them would mean an approved batch at or above the threshold
  never runs.
- Cumulative count = items currently `held` + new candidates found this scan + items **auto-deleted** in the
  last 7 days. **Approved deletions don't count** toward the window, so approving a big cleanup doesn't hold
  every deletion for the following week. *(The Go design left the window open; 7 days and excluding approved
  deletions are my calls. The window is what stops a slow leak.)*
- **Not tripped and below threshold** (or threshold `-1`): execute this scan's candidates (see "Execution"),
  emit `deletion_sync_summary`.
- **Count reaches threshold**, or the batch is **already tripped**: set every candidate to `held`, execute
  nothing, set `deletion_state.tripped`. Emit `deletion_sync_threshold_tripped` the first time, and again only
  when the held batch has grown by record names not seen before (silent re-confirmation otherwise).

## Execution

Runs after the scan, using the `PhotoAsset` objects (and fresh `recordChangeTag`s) the scan just fetched.
`delete_photo()` moves the deletion out of the loop: no deletion happens mid-enumeration for this feature.

- Before each delete, re-check that every manifest path is still absent. If any file has reappeared:
  `skipped_reappeared`.
- `approved` items not seen in this scan (already gone from iCloud): `skipped_gone`.
- `delete_photo()` today ignores the response. For this feature, check it: a non-2xx response or a
  per-record error marks the item `failed` (retried next scan), never `deleted`.
- On success: `deleted`, and prune that asset's `downloaded_assets` rows.
- The `records/modify` payload already takes an `operations` array, but nothing in this codebase sends more
  than one. Batching several deletes per request (non-atomic, so one bad record doesn't fail the rest) is
  allowed only after a live test confirms it; otherwise one request per asset.

## Resolving a held batch

`icloudpd --config … --resolve-deletions approve|reject --username U [--library L]`

- Selects exactly one config entry by `username` + `library` (library defaults to the entry default,
  `PrimarySync`). No match, or more than one, is an error. Never resolves "all entries".
- This needs its own argument handling. Today `--config` plus `-u/--username` is rejected (`cli.py:605`), and
  `--library` given alongside `--config` overrides every entry (`cli.py:614`). In resolve mode, `--username`
  and `--library` select an entry instead. *(Exact flag spelling is the builder's.)*
- Opens that entry's `state.db`, prints the batch (count + filename + date, one per line), and applies the
  decision. Needs no iCloud login, so it works while a watch-mode process is running (SQLite locking on local
  disk handles the concurrent writer).
- `approve`: `held` → `approved`; clears `tripped`. Deletes go out at the end of the next completed scan.
- `reject`: `held` → `rejected`; clears `tripped`; clears `missing_since_utc` on those assets. They
  re-download on the next scan.
- No held batch: prints that and exits 0.

A read-only `--list-pending-deletions` (same selector) prints the batch without changing anything.
*(My call; cheap, and the CLI otherwise has no way to look before deciding.)*

## Notification events

Through the existing `notifications.notify()`. `data` always carries `library` and `directory`.

- `deletion_sync_summary` — after auto-execution. `data`: `deleted_count`, `failed_count`, `items`
  (`record_name`, `filename`, `asset_date`) capped at 50 with `total` alongside.
- `deletion_sync_threshold_tripped` — when held, or when the held batch grows. `data`: `held_count`,
  `new_count`, `threshold`, `items` (same cap).

## Multiple libraries

Each library is its own config entry with its own `state.db` (enforced at startup, see "Configuration"). Threshold, held batch, and trip state are
therefore per library. A user can set a lower threshold on the Shared Library entry. A photo lives in one
library at a time, so per-library deletion covers "delete everywhere". Exception, documented: a separate copy
of the same picture in another library is a different record and is not deleted.

## Verification (Part 1)

Automated, against a fake library and temp directories:

- Delete one file of a Live Photo pair → no candidate; that file re-downloads. Delete both → suspect on scan 1,
  candidate on scan 2. Same for multi-size and RAW+JPEG.
- Change `folder_structure` between scans → zero candidates, everything re-downloads under new paths.
- Missing marker → entry skipped, nothing detected.
- Cancelled scan → doesn't advance the debounce, executes nothing.
- Below threshold → deletes, summary event, manifest rows pruned.
- Reaching threshold → zero deletes, batch held, tripped event; trip persists across the next scan; new
  candidates merge and re-notify only on new record names.
- Slow leak: `N-1` per scan across scans → trips on the cumulative count.
- `reject` → items re-download next scan. `approve` → deleted at the end of the next scan; an item gone from
  iCloud meanwhile → `skipped_gone`; a file restored locally meanwhile → `skipped_reappeared`.
- Failed `records/modify` response → `failed`, retried next scan, never `deleted`.
- An approved batch larger than the threshold executes on the next scan; afterward a single new deletion
  isn't held just because of it.
- `--dry-run` across any number of scans leaves `state.db`'s deletion state byte-for-byte unchanged.
- Under `NAME_SIZE_DEDUP_WITH_SUFFIX`, deleting a `-<size>` suffixed file still becomes a candidate.
- Startup rejects `sync_deletions` with `recent`/`until_found`/no mount marker, or two entries sharing one
  `state.db` (explicit or default path).
- Resolver refuses a missing or ambiguous entry.

Manual, before using against the Shared Library: delete one throwaway photo in a `SharedSync` zone via the
feature, and confirm it lands in Recently Deleted.

---

# Part 2 — Telegram

> **Superseded** by `2026-10-29-deletion-sync-part2-telegram-design.md` (rich-message review with per-photo keep,
> session registry, multi-account control channel). Kept below for history.

Builds on Part 1's state. No change to detection or the breaker.

## Control channel (new)

A small authenticated HTTP listener inside icloudpd, separate from the web UI, designed to become the web UI's
replacement later.

- Off unless `control_token_file` is set (global config). The token is read from the file, never from an env
  var or the config file. Every request needs `Authorization: Bearer <token>`; constant-time compare; no token
  → 401.
- Own port (`control_port`; default picked by the builder, not 2011). Binds `0.0.0.0` so the bot container can
  reach it; the token is the protection.
- Endpoints (shape is the builder's call):
  - list entries with a held batch (username, library, count)
  - one page of a held batch (10 items: metadata + thumbnail)
  - resolve a batch (`approve` | `reject`), same semantics as the CLI
- Writes go through the same functions the CLI resolver uses; the listener uses its own SQLite connection.

The bot reads the same token from its own `*_FILE` env var, matching how it already reads `bot_token`.

## Bot

- Handles `deletion_sync_threshold_tripped`: sends the count plus the first page of thumbnails as a media
  group (up to 10), with inline Approve / Reject / Previous / Next buttons. Buttons identify the entry so they
  are never ambiguous, but through a **short key**: Telegram limits `callback_data` to 64 bytes, and an email
  plus `SharedSync-<uuid>` won't fit. The control channel's entry list provides the key.
- Handles `deletion_sync_summary`: count plus the first page of thumbnails, no action buttons (already deleted).
- `/approve <account> <library>` and `/reject <account> <library>` commands. Missing or ambiguous arguments
  are rejected with the list of entries that have a held batch.
- Approving doesn't require paging through the whole batch.
- The reply to Approve says the deletes go out on the next sync.
- Existing `allowed_chat_ids` enforcement applies to every new handler.

## Thumbnails

icloudpd fetches them (the bot has no iCloud session) and serves them through the control channel; nothing is
written to disk.

Two things the Part 2 builder must check first, because they can change the design:

1. **Video thumbnails.** In this codebase a video's `THUMB` size maps to `resVidSmall`, a small video
   (`src/pyicloud_ipd/services/photos.py:799`), not the JPEG poster frame the Go design assumed. Find the JPEG
   field on a real video record (likely `resJPEGThumb` on the master record) before relying on it.
2. **Thumbnail URL lifetime.** A held batch can sit for days, and the URLs come from the last scan. If they
   expire before the next scan refreshes them, paging fails. Measure it.

## Verification (Part 2)

- Requests without the token, or with a wrong one → 401; listener absent when no token file is set.
- Tripped event → media group with real thumbnails, photos and videos; paging both directions on a batch over
  10.
- Approve from Telegram → `approved` → deleted at the end of the next scan. Reject → re-download next scan.
- Two entries with held batches → buttons and commands act on the right one; bare `/approve` is rejected.
- Chat not in `allowed_chat_ids` → ignored.

## Left to the builder

- Exact batch size for `records/modify`, terminal-row retention, control-channel endpoint shapes and default
  port.
- How to test without live iCloud (fake `PhotoLibrary` / recorded responses), in the repo's existing style.
- Migration code for the additive schema changes.
