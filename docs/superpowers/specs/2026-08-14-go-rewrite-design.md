# icloudpd → Go: Rewrite Scope

## Context

`icloudpd` is a container-first service that downloads media from iCloud Photos to local disk, runs unattended 24/7, and feeds external library managers (Immich watches its output as external libraries). It was inherited at fork as a **CLI tool**, and every service capability since — config file, notifications, asset manifest, session-expiry warnings, Telegram 2FA sidecar — has been layered onto that CLI-first core rather than designed into a service.

The symptoms are concrete and now well-evidenced:

- `src/icloudpd/base.py` is **1,343 lines** mixing CLI parsing, orchestration, and per-photo logic.
- The "scheduler" is `while True` + a **1-second `time.sleep` countdown animating a tqdm progress bar** — a terminal widget — burning 3,600 wakeups/hour in a container to render something nobody sees. It measures interval between *completions*, so the schedule drifts and cannot express "3am nightly."
- The web UI has **no authentication on any endpoint**, binds `0.0.0.0` by default, exposes a **destructive unauthenticated `POST /force-reauth`**, and dumps full per-account config to any caller — with the plaintext password suppressed only by a template string comparison (`{% if record != 'password' %}`).
- The asset manifest is **written but never read**; dedup still works by `os.path.isfile()` path-guessing.
- Accounts are processed **strictly sequentially** — one hung account starves all others indefinitely.

**Six of the nine open GitHub issues are architectural complaints, not feature requests.** #27 states the thesis outright: *"an interactive-CLI-era design that container-first features have been layered onto rather than rebuilt for."* #28 documents an actual deadlock between two shipped features. #29 calls the review-surface gap *"a symptom of this project's CLI-native origins."*

**Intended outcome:** a from-scratch Go service, designed as a service, that resolves these by construction rather than by further patching.

### Decision record on the riskiest choice

The rewrite includes the reverse-engineered iCloud protocol client. This was challenged with evidence and re-confirmed:

- Upstream `icloud_photos_downloader` is alive (12,157★, 15 commits/90d) but `src/pyicloud_ipd` is **maintenance-mode** — touched twice in a year, most importantly `2026-04-19 fix: restore 2FA for Apple's updated auth flow (2026+)`. That annual Apple-breaks-auth event becomes **our** problem, and it causes total outage, not degradation.
- **No viable Go library exists.** `chyroc/icloudgo` (121★, Apache-2.0) is the only real prior art and has been dead since 2023-12 — predating the 2026 auth change, so its auth is almost certainly broken. Usable as an **SRP reference**, not a dependency. `gophotocloud` (2016, unlicensed) and `lukasmalkmus/icloud-go` (public CloudKit API, wrong endpoint entirely) are non-options.
- A Python-auth-subprocess hybrid was considered and **rejected**: its value depends on auth being a stable separable seam, but upstream refactors those internals freely (Aug 2025: *"use base Session class instead of PyiCloudSession"*, *"extract service dependencies from PhotoLibrary and PhotoAlbum constructors"*). It would mean owning the hard integration *and* pinning to unstable internals.

Accepted in exchange: a single ~20MB static binary (`CGO_ENABLED=0`, distroless), no secret crossing a process boundary, no cross-language session contract, and no dependency on upstream's internal structure. **The price is owning Apple protocol drift permanently** — mitigated by spiking SRP before anything else is built.

---

## Feature decisions

| Feature | Decision |
|---|---|
| **Asset manifest** | **KEEP, promoted to source of truth.** Identity lookup by iCloud record name replaces `os.path.isfile()` guessing. Kills the "change folder structure → re-download everything" failure mode. |
| **Notifications** | **KEEP.** Generic webhook-style notifier interface as the extension point (tell-don't-ask); others add channels via PR without touching core. |
| **Telegram bot** | **KEEP, promoted to first-party.** Moves out of `integrations/telegram-bot` into the main project as the reference notifier implementation and the 2FA/control channel. |
| **Autodelete after download** | **CUT.** No use case. |
| **Deletion-mirroring (#5)** | **ADD.** Local deletion → move to iCloud Recently Deleted. Distinct from autodelete; the manifest was always the prerequisite. Design is **already locked in** across multiple prior sessions — see the dedicated section below; do not re-derive it. |
| **Session-expiry warnings** | **KEEP, refined.** ~99% of re-auth is 2FA-only — that path must be low-friction, Telegram-first. Password re-prompt **only on confirmed auth failure against Apple**, never on routine expiry. |
| **XMP sidecars** | **KEEP.** Carry issue #32 (`adjustmentSimpleDataEnc` decode failure silently dropping Orientation on some HEIC) as a fixture-driven test case; decoder must return a typed error, not a swallowed warning. |
| **Web UI** | **KEEP, cut down to a single surface.** Always-on read-only dashboard only, off by default. No mutating web endpoints, no credential-entry web form, no thumbnail-proxy web server — see **Web UI, decided (2026-09-22)** below. |
| **Scheduling** | **REPLACE.** Cron expressions primary, `every: 1h` sugar desugared into the same engine. Timer-driven, context-cancellable. **Required per account, no default** (corrected 2026-09-22 — an earlier draft of this row claimed a `0 3 * * *` default that contradicted the config schema's own "required" note; `validate` rejects a config missing `schedule`, it does not silently apply one). `0 3 * * *` (daily, 3am) is only the example value shown in the sample config. Manual trigger via `/sync <account>` in Telegram, in addition to the schedule. |
| **Multi-account** | **REPLACE.** Concurrent, one goroutine per account, global rate limiter (default 2 req/s, configurable), per-phase timeouts (30s for auth/one listing page/one API call; downloads use a minimum-speed threshold instead of a flat deadline). |
| **Health/readiness, JSON logging, Prometheus metrics, graceful shutdown + resumable downloads** | **ADD** — all four. None exist today. `/readyz` flips not-ready only on **total** failure (every account down); one hung account among several does not flip it. |
| **Review surface (#29)** | **ADD, Telegram-native — see "Deletion-sync review surface" below.** No web thumbnail proxy. Live `THUMB`-size thumbnails (~46KB) fetched on demand and sent as Telegram photo messages, paginated, never stored on disk. |

**Secrets:** vendor-agnostic. One interface — a **file containing the value, watched with fsnotify** so external rotation (Doco-CD + Bitwarden Secrets Manager, Docker secrets, K8s volumes, Vault Agent) is picked up live without restart. **No vendor SDK.** One file per secret, no multi-secret file parsing — matches how Docker secrets, Kubernetes Secret volumes (each key becomes its own file), and Vault Agent already deliver values. This upgrades today's read-once-at-startup behavior, which the current spec lists as an explicit non-goal.

**Credential model** (resolves #27's flattened `password_providers` list; decided 2026-09-08, refined 2026-09-22) — two axes:
- *Source chain*, all non-interactive, one value per watched file: `apple_id` and `password` each follow watched file → env var → in-memory cache (last known-good, RAM only, never serialized).
- *Escalation policy, split by failure type* (Apple's own auth API already distinguishes these — `PyiCloud2SARequiredException` vs `PyiCloudFailedLoginException` in the reference client):
  - **2FA/2SA required** (the ~99% case, expected and routine): notify over Telegram, code entered back as an **inline reply in the same chat**. Ephemeral, never persisted. **Multi-account disambiguation (decided 2026-09-22):** if two accounts need a code at the same time in the same chat, the bot uses Telegram's native **reply-to-message** linking — your reply is tied to the specific "account X needs a code" prompt message it's a reply to, so no new syntax (like typing the account name) is needed to disambiguate.
  - **Confirmed wrong password**: notify over Telegram **for awareness only** — "password file is wrong, fix it" — no code/value is ever typed back into Telegram. The password source chain has no escalation path; if none of watched-file/env/cache work, the run fails until the file is corrected out of band.
  - **No web capability-URL form.** Considered and cut 2026-09-22: it would need its own auth surface (HTTPS, reverse proxy) for a login use case explicitly kept out of MVP scope.
- **Telegram is mandatory, not optional (decided 2026-09-22).** It's the only channel capable of receiving a 2FA reply back (see `mfa_provider`'s cut reasoning in "Config schema" below); a deployment with no Telegram configured would eventually deadlock unattended on the first routine 2FA prompt with no way to resolve it. `icloudpd validate` requires `telegram.bot_token_file` to be set — refusing loudly at startup rather than working until the first 2FA need surfaces the gap at the worst possible time.
- **`allowed_chat_ids` stays one global list, not per-account (reaffirmed 2026-09-22).** Any allowed chat can act on any account's `/approve`, `/reject`, `/cancel`, `/resume`, `/force_reauth`. Considered adding per-account scoping and rejected: for the target deployment shape (a household running a handful of accounts), everyone on the allowlist is already trusted with every account, and per-account scoping would be config surface with no real isolation benefit for that case.
- The memory cache is what breaks **#28's deadlock**: proactive 2FA refresh works with no on-disk password. **Known accepted limitation (2026-09-22):** the cache is RAM-only and does not survive a process restart. A restart between initial auth and the next 2FA refresh can require a fresh 2FA prompt again — no worse than the pre-cache baseline, just not an improvement in that specific window. Persisting the cache to disk was considered and rejected: it would mean writing a working credential to disk, which is exactly what this design exists to avoid.
- **`allowed_chat_ids` cannot be empty if Telegram is configured (decided 2026-09-22).** `/approve`, `/force_reauth`, `/cancel`, `/resume` are the only surface that can trigger irreversible mutations (deletion-mirror execution, forced re-auth) in the whole rewrite — an empty allowlist with no defined semantics would either silently deny everyone (confusing) or silently allow everyone (the exact unauthenticated-mutation bug this rewrite exists to fix, just relocated to Telegram). `icloudpd validate` refuses to start if `telegram.bot_token_file` is set and `allowed_chat_ids` is empty.

**Delivery:** one binary, `serve` as container default, plus `validate` / `print-config` / `run-once` / `check-protocol` (manual live-protocol structure check, see "Testing" below — no CI, no dedicated test account). `auth-only` / `list-albums` / `list-libraries` are CLI-only diagnostic actions, not persisted config. **No `migrate` subcommand** — cut 2026-09-22, everything else is already a clean break (fresh auth, fresh manifest by scanning disk), so `migrate` had only one plausible job (convert the old Python YAML config) and `validate`/`print-config` already cover writing a new config by hand. **Clean break on state** — fresh auth, fresh manifest rebuilt by scanning existing files on disk; Apple's cookie format need not be ported. Session data lives under `state_dir`, no separate configurable path. **Rewrite in place on a long-lived branch**; the Python version stays available by release tag.

---

## Architecture

### Package layout

```
cmd/icloudpd/                 main(): subcommand dispatch
internal/cli/                 serve, validate, print-config, run-once, check-protocol, auth-only, list-albums, list-libraries
internal/app/                 COMPOSITION ROOT — the only package that wires concrete types

── domain (no outward deps) ──
internal/asset/               Key, Asset, Version, VersionSize, ItemType, Zone
internal/naming/               filename + folder-structure policy (pure functions). Straight port of the Python scheme: a format string applied to the asset's creation date (default `{:%Y/%m/%d}`), or literal `none` for flat — same config shape, Go's time-formatting verbs substituted for Python's. `file_match_policy` is DROPPED: the manifest now solves identity, so the filename-collision dedup it existed for is moot.
internal/xmp/                 sidecar generation (pure)

── protocol ──
internal/icloud/srp/          SRP-6a + PBKDF2 s2k. Pure crypto, no HTTP.
internal/icloud/auth/         sign-in, 2FA/2SA, trust, cookie jar, session persistence
internal/icloud/ckws/         CloudKit transport: records/query, batch, zones/list, records/modify
internal/icloud/photos/       CPLMaster/CPLAsset → asset.Asset; zone discovery; thumbnails; delete

── engine ──
internal/enumerate/           Enumerator interface + Change/Cursor/Capabilities
internal/enumerate/full/      full-sweep (startRank paging) — day-one implementation
internal/enumerate/delta/     syncToken enumerator — DEFERRED for v1, backlogged (see decision, 2026-09-08)
internal/syncengine/          per-account run loop: enumerate → decide → download → record
internal/download/            ranged resume, atomic temp+rename, integrity check against Apple's `fileChecksum` (already provided in asset-version metadata, currently unused in Python beyond building a temp-file name — verify it against downloaded bytes, not just size)
internal/mirror/              deletion POLICY: threshold, batch state, approval, submission
                              (detection lives in syncengine — see Deletion-mirroring below)
internal/scan/                filesystem backfill + volume-liveness sentinel

── state ──
internal/store/               Store interface + row types
internal/store/sqlite/        implementation, migrations (embedded .sql)

── platform ──
internal/schedule/            cron parse + timer-driven, context-cancellable Ticker
internal/secret/              secret.Value, Source chain, Provider, Escalation
internal/secret/watchfile/    fsnotify-backed source
internal/notify/              Notifier interface, Event, fanout, retry
internal/notify/telegram/     first-party notifier + command listener + bot command bus (see "Telegram bot commands" below)
internal/notify/webhook/      generic HTTP POST notifier: {event, account, timestamp, data} envelope, 3 retries exponential backoff, then log+drop
internal/control/             command bus: Cancel, Resume, ForceReauth, Approve/RejectBatch — invoked ONLY from internal/cli and internal/notify/telegram, never from a web handler
internal/ratelimit/           global (not per-account, decided 2026-09-22 — a shared budget bounds total request rate against Apple regardless of account count) token bucket. Default 2 req/s API (configurable), downloads unthrottled
internal/config/              YAML load, defaults, validation, redacted printing — schema in "Config schema" below
internal/obs/                 slog setup, metrics, retry classification
internal/web/health/          ALWAYS-ON internal listener, independent of dashboard.enabled: /healthz, /readyz, /metrics (Prometheus format) — see "Health/metrics listener" below

── presentation ──
internal/status/              READ-ONLY view model. No secret-capable types.
internal/web/dashboard/       optional, off by default. Read-only only — no mutating endpoint, no credential form, no thumbnail proxy. Imports status ONLY.
```

**Dropped 2026-09-22: `internal/web/thumbproxy/` and `internal/web/capability/`.** Both existed for reasons that are now gone — the credential-escalation web form is cut (Telegram inline-reply/notify-only instead), and the deletion-sync review surface moved to Telegram-native photo messages (see below), so there is no web consumer left needing a thumbnail proxy. The web surface collapses to a single package: the optional read-only dashboard. The "security domains" framing from earlier drafts is now moot — there is only one domain.

**Guiding rules:** domain types depend on nothing; only `internal/app` wires concrete implementations; secrets are a *type*, not a convention; the engine never knows how assets were discovered.

### The enumeration seam (most important)

The spike's outcome must not force restructuring. Model enumeration as a **stream of changes + opaque cursor + honest capability declaration** — not "give me a page," which would bake in offset paging:

```go
type Cursor []byte                      // opaque; persisted verbatim
type Change struct { Kind ChangeKind; Asset asset.Asset }   // Present | Removed
type Capabilities struct {
    ReportsRemovals bool   // source explicitly tells us about deletions
    Exhaustive      bool   // a completed run visited every live asset
    Resumable       bool   // mid-run cursor is safe to persist
}
type Enumerator interface {
    Capabilities() Capabilities
    Enumerate(ctx, from Cursor, yield func(context.Context, Change) error) (Cursor, error)
}
```

**The load-bearing contract rule:** the engine may conclude "asset X is gone from iCloud" only if the run completed without error **and** (`Exhaustive`, via not-seen-in-sweep) **or** (`ReportsRemovals`, via explicit `Removed`). This is what lets `full` and `delta` coexist and prevents a delta run from mass-pruning the manifest. Reconciliation branches on *capabilities*, never on a type switch.

`full` returns `{false, true, true}`; `delta` would return `{true, false, true}`. A **composite** (delta every 60s, full sweep nightly) satisfies the same interface with the engine unchanged — and is probably where this lands.

This also fixes a real bug: paging state becomes `{startRank, expected_count}` with dedup by `asset.Key` in the store rather than trust in offsets, so a mutating server index causes at worst re-visits, never skips. **Delete `increment_offset(-1)`** (`base.py:1238`).

### Store — failure semantics inverted

Today the manifest swallows every error "because it must never break the download loop." Now that it is the source of truth, **a store write failure is a fatal run error** for that account. Only telemetry writes stay best-effort. Cursors are keyed by `enumerator_id` so `full` and `delta` keep independent state — switching strategies is not a data migration.

### Manifest schema (essentials)

One DB for the whole service at `<state_dir>/icloudpd.db`, WAL mode — not one per download directory or per account. **Corrected 2026-09-22:** the original justification here ("cross-account mirror batches need a single transaction domain") was wrong — mirror batches are strictly per-account everywhere else in this doc (per-account threshold and trip state, `/approve <account>`, "one pending batch per account at a time"), so no cross-account transaction ever actually occurs. The real reason for one DB is operational simplicity: one WAL file, one backup target, one place to look — not a functional requirement. Per-account DBs would work too; they're just not worth the added complexity given the scale in "Where this design is most likely wrong," point 3.

- `assets` — PK `(account_id, zone_kind, zone_name, record_name)`. `record_name` is the **CPLMaster** recordName; `CPLAsset.recordName` is metadata versioning, *not* identity (preserve `_pick_newer_asset_record`'s newest-`addedDate`-wins duplicate collapsing). Carries `last_seen_run`, `removed_remote_utc`.
- `files` — 1:N from assets. `version_size` + `role` (`primary | live_photo_video | raw | sidecar_xmp`), `rel_path` **relative to the account download root** so remounting doesn't orphan the manifest, `missing_since_utc`.
- `cursors`, `mirror_batches`, `mirror_items`, `schema_migrations`.

Deletion-mirroring semantics fall out as one query: an asset is a candidate when **every** `files` row for it — excluding `role='sidecar_xmp'` — has been missing since at least the previous run (`missing_since_utc` set, confirmed missing again this run). That is exactly the "all rows missing" rule for Live Photo companions, multi-size, and RAW+JPEG. **Terminology fix (2026-09-22):** this is a fixed one-run debounce, not a time value — a previous draft of this line used the word "threshold" here too, which collides with `deletion_sync.threshold` (a batch-*size* trip point, unrelated). No such time-based config key exists; the debounce is inherent to the two-run detection rule below, not a separate setting.

### Config schema (decided 2026-09-22)

Every surviving key from the Python config, audited one at a time against what it actually does and whether the rewrite still needs it. Two-tier shape: one **global** block (process-wide) plus a list of **accounts**, each grouped by function.

```yaml
global:
  log_level: debug
  rate_limit_per_sec: 2          # unverified guess, not measured against Apple's real limits
  state_dir: /state              # separate volume, local block storage only, never NFS
  health:
    bind: 0.0.0.0                  # deliberately NOT loopback-only (decided 2026-09-22) — unlike the dashboard, K8s probes come from inside the pod but Prometheus scraping needs network reachability from another pod. Safe to expose: no credentials, account names, or status data on this listener (verified) — worst case exposure is healthy/unhealthy + counters.
    port: 9090                    # ALWAYS ON, independent of dashboard.enabled — see "Health/metrics listener" below
  dashboard:
    enabled: false                # optional, off by default, not in MVP
    bind: 127.0.0.1               # loopback only by default — deliberate, see "Web UI" section below
    port: 2011
  telegram:
    bot_token_file: /secrets/telegram_token
    allowed_chat_ids: []          # plain config, not secret-backed. EMPTY IS INVALID if telegram is configured — validate refuses to start, see credential model below
  webhook_notifier:
    url_file: /secrets/webhook_url # secret-backed like everything else — a webhook URL often embeds an auth token
                                    # {event, account, timestamp, data} envelope, 3 retries exponential backoff

accounts:
  - name: main                            # required, unique. Addresses this account in every Telegram command (/sync <account>, etc.), the manifest's account_id, and dashboard display. Never the apple_id — that's secret-backed and never meant to be typed into Telegram.
    credentials:
      apple_id_file: /secrets/apple_id    # file->env->cache chain
      apple_id_env: ICLOUDPD_APPLE_ID     # env source for the same chain — was missing from an earlier draft despite the credential model promising it exists
      password_file: /secrets/password
      password_env: ICLOUDPD_PASSWORD
      domain: com                          # com | cn, for China data-residency accounts
    sync_scope:
      library: PrimarySync                 # or a Shared Photo Library zone name
      albums: []
      sizes: [original]
      live_photo_size: original
      asset_types: [photos, live_photos, videos]   # opt-in array, not skip_* opt-out flags
      # skip_created_before/skip_created_after: CUT 2026-09-22. Same exhaustiveness hazard as the already-cut
      # recent/until_found — a date-scoped "full" sweep can still self-report Exhaustive: true, so real photos
      # outside the date range would look identical to deleted ones to deletion-sync's reconciliation logic.
    file_layout:
      directory: /data
      folder_structure: "{:%Y/%m/%d}"
      live_photo_mov_filename_policy: suffix
      align_raw: as-is
      keep_unicode_in_filenames: false
      xmp_sidecar: false
      set_exif_datetime: false
    deletion_sync:
      enabled: false                        # MASTER switch. false = feature fully off, nothing detected or acted on.
      threshold: -1                         # only meaningful when enabled=true. -1 = no cap (rclone --max-delete semantics: unbounded, NOT "feature off"). N = withheld for review once CUMULATIVE unresolved missing count reaches N — see "Circuit breaker" below, cumulative tracking decided 2026-09-22.
    schedule: "0 3 * * *"                  # required, per-account, no default applied if omitted — validate rejects a missing schedule rather than silently picking one
    session_expiry:
      warning_days: 7
      notification_interval_hours: 24
    dry_run: false                          # also covers the old only_print_filenames (merged in)
```

**Cut entirely, with reasoning:**
- `file_match_policy` — the manifest now solves the identity/dedup problem this existed for; only cosmetic value (id7-suffixed filenames) left, not worth a knob.
- `force_size` — always falls back to `original` when a requested size is missing; the skip-instead-of-fallback behavior wasn't worth the config surface.
- `keep_icloud_recent_days` — existed only to guard the already-cut autodelete feature; nothing left to guard.
- `no_progress_bar` — no progress-bar concept in a service; logs/metrics/dashboard replace it.
- `use_os_locale` — CLI-era concept (OS locale of the host machine); `folder_structure` is already ported literally, nothing depends on locale in a container.
- `threads_num` — already dead code in the current Python (plumbed into config, never consumed); concurrency is redesigned around per-account goroutines + the rate limiter instead.
- `mfa_provider` — only one channel (Telegram) can actually *receive* a 2FA reply back; a webhook is outbound-only and has no path for the code to come back, so there's nothing left to select between.
- `password_providers` — replaced by the two-axis credential model above.
- `watch_with_interval` — replaced by cron.
- `notification_script` / `notification_forwarder` — superseded by `webhook_notifier` + first-party Telegram.
- `cookie_directory` — session storage now lives under `state_dir` automatically, no separate path.
- `recent` / `until_found` (early-stop flags) — v1 is full-sweep-only (see the syncToken decision below); early stopping also conflicts with deletion-sync's exhaustive-run requirement.
- `skip_created_before` / `skip_created_after` — cut 2026-09-22 for the identical reason as `recent`/`until_found` above, caught late: a date-scoped sweep can self-report `Exhaustive: true` while still never visiting photos outside the range, so they'd look deleted to deletion-sync's reconciliation logic even though they're just out of scope.
- `only_print_filenames` — merged into `dry_run`.
- `migrate` — see "Delivery" above.

**CLI-only, not in the YAML schema:** `auth-only`, `list-albums`, `list-libraries` — one-shot diagnostics, not persistent config.

### Deletion-mirroring (#5) — locked-in design, carried forward

This design was settled over several prior sessions and is documented in issue #5's comments. It is **not open for re-derivation**; the Go rewrite ports it, with three gaps resolved below.

**Detection happens in the sync loop, not in a reconciliation pass.** When the engine processes an asset that is present in iCloud but whose local files are missing, it checks whether the manifest already holds a row for that `(record_name, rel_path)` **from a previous run**. If so, it is a deletion candidate rather than a re-download. This exists specifically to defeat the **auto-heal race** — a separate end-of-run pass would lose, because the normal loop would silently re-download the deleted file before deletion-sync ever saw it was gone. `internal/mirror` therefore owns *policy* (threshold, batching, approval, submission); `internal/syncengine` owns *detection*. Detection reuses the already-fetched asset, so no extra iCloud round trip.

**Only an exhaustive run may produce deletion candidates.** Truncated enumeration blinds detection: `until_found`/`recent` stop early, so locally-deleted assets past the stop point are never visited. Python had to solve this by **rejecting those flag combinations at startup** (fail fast, not a runtime warning). The Go `Enumerator` seam generalizes it: **a run may produce deletion candidates only if it completed without error and reported `Capabilities.Exhaustive`.** This is the same rule the store already uses to conclude "gone from iCloud," and it makes the composite enumerator safe by construction — a 60s delta tick simply never produces candidates, while the nightly full sweep does. No flag-combination bans needed.

**`state_dir` is a safety mechanism.** The manifest lives on its **own volume**, separate from `/data`. When the media mount drops (NFS/SMB reverting to an empty local directory), the manifest survives, so "manifest says 4,527 rows, filesystem shows 3" stays a loud signal instead of the manifest resetting to empty alongside it and having nothing to compare against. **Constraint:** `state_dir` must be **RWO local/block storage — never NFS** (SQLite's docs: buggy POSIX locking, unreliable `fsync`). `/data` may safely be RWX/NFS.

**Liveness gate.** A per-download-root sentinel file must be readable before any scan counts as authoritative. This is the classic rsync footgun — an unmounted source reading as "everything is gone" — and it runs *before* detection, not as a post-hoc sanity check.

**Circuit breaker.** Config keys `deletion_sync.enabled` and `deletion_sync.threshold` (renamed 2026-09-22 from `deletion_mirroring`), with precedence clarified the same day: **`enabled` is the master switch** — `false` means the feature is entirely off, nothing is ever detected or acted on, regardless of `threshold`. Only when `enabled: true` does `threshold` matter, and there `-1` means **no cap** (matching `rclone sync --max-delete`'s own `-1` semantics — unbounded, not "off"; `rclone` is the correct analog since this is one-directional like `sync`, not bidirectional like `bisync`), while a positive `N` compares against a **cumulative** count (see below), not a single run's batch. **No opinionated default for `threshold` when enabled** — deliberate: it's not a ceiling on how much can ever be deleted, it's a "pause and ask a human first" trip point, and the right number depends entirely on the account's library size and behavior. The user sets whatever value they want; the doc does not recommend one. **Note:** the shown example in the config schema pairs `enabled: false` with `threshold: -1` — that's the master switch off, not "safe because unbounded"; flipping only `enabled` to `true` against that unedited example yields an active, uncapped deletion pipeline. `icloudpd validate` warns (does not block) when `enabled: true` is paired with `threshold: -1`, since that combination is almost always a config left at its example value rather than an intentional choice.

**Cumulative, not per-run (decided 2026-09-22).** `threshold` compares against the **total count of unresolved candidates the account currently holds** (i.e. the size of its one pending/auto-executed-and-logged tracking, accumulated across runs), not the size of any single run's newly-found batch. This closes a real bypass: without it, a slow leak — a handful of "missing" files surfacing per night from a flaky mount, always under N in any one run — would auto-delete indefinitely and never trip the breaker, because nothing accounted for deletions *across* runs. `mirror_items` rows already track enough to support this (each carries its own detection run); the trip check sums outstanding/recently-auto-deleted rows within a rolling window (implementation detail for the iteration that builds `internal/mirror`, not fixed here) rather than a single run's find.
- *Below threshold:* delete, log, emit `deletion_sync_summary` (informational, after the fact). **Reaffirmed 2026-09-22:** below-threshold deletions stay fully automatic, no per-item review — reviewing every deletion would defeat the point of automating the common case, and the threshold is exactly the line between "routine" and "stop and ask."
- *At/above threshold:* **the entire batch is withheld, zero deletions execute**, emit `deletion_sync_threshold_tripped`, and **stay tripped across subsequent runs** until manually cleared. New candidates found on a later run **merge into the same pending batch** rather than opening a second one (see "Deletion-sync review surface" above) — resolving via `/approve` or `/reject` is still the only exit from limbo.

**Resolution.** `--resolve-deletions={approve,reject}` on the CLI, or `/approve <account>` / `/reject <account>` in Telegram (see "Telegram bot commands" above) — a single enum either way, never two booleans (which would let both or neither be passed). `reject` causes those files to be re-downloaded on the next normal pass. **Pending items are exempt from auto-redownload while undecided**, so resolving is the only exit from limbo; it never resolves itself.

**No undo/restore — deliberately out of scope.** Note for future sessions: restore is **confirmed technically possible** — a HAR capture of iCloud.com's own Recover button shows the same `records/modify` endpoint, same `CPLAsset` type, `operationType: update`, with `isDeleted: {"value": 0}`, returning 200. It is excluded anyway because iCloud's Recently Deleted already covers regret-recovery, and duplicating a UI Apple maintains is scope creep. **Do not "helpfully" add this.**

**Three gaps resolved for the rewrite:**

1. **Stale `recordChangeTag` on approval.** A withheld batch may sit for days, by which point the stored tag is stale and the asset may have changed or been deleted in iCloud already. **On approve, re-verify each item two ways** (corrected 2026-09-22 — an earlier draft only described the remote check, but claimed local-reappearance detection that a remote-only lookup cannot perform): a **remote** lookup against iCloud for a current `recordChangeTag` (items already gone remotely are marked `skipped_reappeared`/gone rather than erroring), and a **local** filesystem check at the item's `rel_path` (items whose file has reappeared locally since the batch was created are dropped from the batch, since they're no longer actually missing). Two lookups per item, and approval is correct regardless of how long the batch sat.
2. **Threshold scope under concurrency.** Accounts now run concurrently (they were sequential in Python), so the threshold is **per-account**, with per-account trip state. One account's bulk cleanup must not withhold another's legitimate deletions, and thresholds relate to library size, which differs per account.
3. **Event payload shape — updated 2026-09-22.** `deletion_sync_summary` / `deletion_sync_threshold_tripped` carry the **count plus the first page of real thumbnails**, delivered as Telegram photo messages (see "Deletion-sync review surface" above), not a capability URL — that mechanism is cut. A 4,000-item trip pages through 10 at a time via inline buttons rather than producing one unusable message or a link to a web page that no longer exists.

**Withheld-row data model:** `record_name`, filename, and asset date — enough to fetch a `THUMB`-size JPEG live on demand and send it directly in Telegram. Video records carry a JPEG poster-frame thumbnail in the same field, so no photo/video branching. Nothing is stored on disk.

**Now-moot interactions:** the issue lists open questions about `--auto-delete` / `--delete-after-download` interaction. Both are **cut**, so those questions disappear.

### Concurrency

One goroutine per account owning that account's session (no mutex; the runner *is* the serialization point). **Process-global `rate.Limiter` for API calls, shared across every account** (reaffirmed 2026-09-22 — a per-account budget was considered and rejected: it would multiply total request rate against Apple with account count, which is riskier, not safer, than the exact thing a global limiter exists to bound) — **downloads are unthrottled** (corrected 2026-09-22: an earlier draft of this paragraph also described a separate byte-rate limiter for downloads, contradicting the package-layout description and the earlier rate-limit decision, which scoped `rate_limit_per_sec` to API calls only; downloads are large sequential transfers already gated by the per-phase minimum-speed timeout below, and a byte-rate cap was never actually decided as a feature). **Timeouts are per phase, not per account** — auth, one enumeration page, one modify use the flat 30s timeout; **one file download uses a minimum-speed threshold instead**, not the flat deadline (a large file shouldn't be killed early just for being large). This is what actually fixes "one hung account starves the others." Use a **non-cancelling** errgroup: a per-account failure is logged and published to status, never aborts siblings.

**Cron overlap (decided 2026-09-22): skip, don't queue.** If an account's run is still in progress when its own next scheduled tick fires, that tick is skipped — it waits for the *next* scheduled time rather than queuing a second run back-to-back. Keeps each account's own timeline simple (no backlog to work through) at the cost of the schedule silently slipping for that one tick, which is visible in `/status` and `/metrics`.

**Shared-DB writes: a single serialized writer, not busy-timeout retry (decided 2026-09-22).** Multiple account goroutines can produce store writes concurrently, but SQLite allows exactly one writer at a time. Rather than have each goroutine retry-on-`SQLITE_BUSY`, all writes funnel through **one dedicated writer goroutine** that every account goroutine sends to over a channel — collisions become queueing, not errors, and this is a natural fit with "a store write failure is a fatal run error," since a write that reaches the writer either succeeds or fails for a real reason, never for losing a lock race.

Graceful shutdown: root cancel → HTTP `Shutdown` → runners stop *between assets* (partial downloads discarded via temp+rename) → store commits → close. Per-asset transactions mean `kill -9` loses at most one asset.

### Web UI, decided (2026-09-22) — single surface, read-only, optional

Earlier drafts split the web UI into two security domains (read-only dashboard + a capability server for credential escalation and thumbnail-proxying). Both of those reasons are gone:

- **Mutating actions** (`Approve`/`RejectBatch`, `ForceReauth`, `Cancel`, `Resume`, manual sync trigger) go through **Telegram slash commands and the CLI only** — never the web. There is no mutating web endpoint at all, which directly resolves the motivating problem (`POST /force-reauth` with no auth today).
- **Credential escalation** never touches the web either. 2FA codes are typed back as Telegram inline replies; a confirmed-wrong password gets a Telegram notification with no reply path (see credential model above). The capability-URL web form considered for this was cut — it would need its own HTTPS/reverse-proxy story for a case kept explicitly out of MVP scope.
- **Deletion-sync review** (thumbnails for a withheld batch) moved to Telegram-native photo messages — see "Deletion-sync review surface" below. No web thumbnail proxy needed.

What's left: `internal/web/dashboard` is **optional, off by default**, read-only, and imports only `internal/status` — nothing secret-capable. `internal/status` is its entire view model: stdlib + `internal/asset` only, with the `config + runtime → status.Snapshot` projection built explicitly, field by field, in `internal/app` (a whitelist by construction). `secret.Value` still has no exported field and overrides `String`/`GoString`/`MarshalJSON`/`MarshalText` → `[redacted]`, so even a mistake in the projection can't print one. `TestDashboardImportGraph` still shells `go list -deps ./internal/web/dashboard` and asserts the transitive set excludes `internal/secret`, `internal/config`, `internal/icloud/auth`, `internal/control`, `internal/store/sqlite` — one package, one test, no capability-server twin needed anymore.

**Default bind: `127.0.0.1`, not `0.0.0.0` (decided 2026-09-22).** The Context section names the Python dashboard's `0.0.0.0`-by-default bind as a concrete motivating problem; the new dashboard is read-only with no mutating endpoints, which lowers the stakes, but it still leaks account names, sync/error history, and pending-batch state to anyone who reaches the port. Loopback-only by default means someone who actually wants LAN/remote access sets `dashboard.bind` explicitly — opt-in, not opt-out, so the original bug can't silently recur.

### Health/metrics listener (decided 2026-09-22)

A **separate, always-on internal listener** (default `0.0.0.0:9090`, decided 2026-09-22 — see below), independent of `dashboard.enabled` — this exists whether or not the optional dashboard is turned on, which is required for the "ADD, none exist today" claim in the feature table to actually hold for a container-first service. Serves only `/healthz`, `/readyz`, `/metrics` — no status data, no account names, nothing the dashboard's read-only view model has. `/metrics` uses standard Prometheus exposition format via `prometheus/client_golang`, so any standard scraper (Prometheus, Grafana Agent) works without a translation layer. `/readyz` flips not-ready only on total failure (every account down); one hung account among several does not flip it.

**Bind default is `0.0.0.0`, not loopback like the dashboard (decided 2026-09-22).** K8s liveness/readiness probes come from the kubelet inside the pod's own network namespace, so loopback would work for those — but Prometheus normally scrapes from a separate pod, which needs real network reachability, not `127.0.0.1`. Exposing this listener carries much lower risk than the dashboard did: it carries no credentials, account identifiers, or status detail, just healthy/unhealthy and counters.

### Telegram bot commands (decided 2026-09-22)

Registered via BotFather. Telegram command names allow only lowercase letters, digits, and underscores — **no dashes** — so `force-reauth` is `/force_reauth`.

| Command | Effect |
|---|---|
| `/sync <account>` | Trigger an immediate full sweep now, outside the cron schedule. |
| `/approve <account>` | Release that account's pending deletion-sync batch — all items execute. |
| `/reject <account>` | Discard that account's pending batch — those files re-download next normal run. |
| `/cancel <account>` | Stop an in-progress sync run for that account. |
| `/resume <account>` | Undo a `/cancel`, or restart a paused account's schedule. |
| `/force_reauth <account>` | Discard the current session, force a fresh login. |
| `/status <account>` | Read-only: last sync time, error counts, pending mirror batch state. |

Every account-scoped command takes `<account>` explicitly — multiple accounts can have independent pending state (a sync run, a withheld batch) at the same time, so there is no implicit "current" account to fall back on.

### Deletion-sync review surface (decided 2026-09-22)

Replaces the earlier web-capability-URL design. When a batch trips the circuit breaker (or is updated — see below), the bot sends it as **real Telegram photo messages**, not just filenames: up to 10 `THUMB`-size JPEGs per message (Telegram's own per-message limit for an album), fetched live and never stored on disk. Video records use their JPEG poster-frame in the same field, so no photo/video branching.

- **Pagination**, not a forced full review: inline "next 10" / "previous 10" buttons walk the batch in either direction. Approving does **not** require having paged through everything first — that's the user's call, not something the bot enforces.
- **All-or-nothing approve/reject stays** (no per-item selection) — simpler state machine, and a rejected item just re-downloads and gets re-evaluated next run if it's still actually gone.
- **New candidates found on a later run merge into the same pending batch** rather than opening a second one — one pending batch per account at a time. **Dedup mechanism (decided 2026-09-22):** each run checks candidate `record_name`s against the account's `mirror_items` rows already in the pending batch. An item still missing that's already in `mirror_items` is a silent re-confirmation, no notify. A `record_name` not already present is genuinely new — only that triggers a **re-notify** with the updated count and a fresh page of thumbnails. It never grows silently, since you might otherwise approve against a count you saw days ago.
- Approval still re-verifies each item's `recordChangeTag` against iCloud regardless of how the batch got to its current size (unchanged from the original gap-1 resolution below).

### Libraries

Everything CGO-free so `CGO_ENABLED=0 go build` → distroless.

| Need | Choice | Note |
|---|---|---|
| SQLite | `modernc.org/sqlite` | Pure Go. **Reject `mattn/go-sqlite3`** — CGO breaks the static build. |
| Cron | `adhocore/gronx` (parser only) | Want `Next(t)` and to drive our own timer. **Do not adopt robfig's runner** — it owns the loop, which is the thing being fixed. |
| fsnotify | `fsnotify/fsnotify` | **Watch the parent directory, not the file** — K8s/Docker rotation is an atomic symlink swap and a file-level watch goes deaf. Debounce ~200ms, re-read + validate. |
| Telegram | `go-telegram/bot` | Zero deps, context-first, maintained. `go-telegram-bot-api` v5 is effectively unmaintained. |
| SRP | **hand-rolled**, `math/big` + `crypto/sha256` + `x/crypto/pbkdf2` | Apple's variant matches no off-the-shelf library. ~250 lines. Highest-uncertainty piece. |
| YAML / CLI / HTTP / logging / templates | `yaml.v3` (`KnownFields(true)`), stdlib `flag`, `net/http`, `log/slog`, `html/template` | Avoid viper and cobra — not earned at this size. |
| Rate limit / concurrency / diffing | `x/time/rate`, `x/sync/errgroup`+`singleflight`, `go-cmp` | Skip testify. |

Config layering (YAML → env → defaults) is hand-rolled ~150 lines because `print-config` must show **per-field provenance**.

### Testing — fixing the stale-cassette problem

The existing VCR cassettes record a record type **replaced in 2023**; zero cover the current `CPLAssetAndMasterByAssetDateWithoutHiddenOrDeleted`. Root cause: using recorded HTTP to test *logic*. Split three ways:

1. **Codec tests** — fixtures test only parse/serialize, each with `{recorded_at, record_type, redaction_version}` metadata. Two guards: a **freshness guard** (fixtures older than **90 days** fail loudly — quarterly re-verification against the live API, decided 2026-09-22 — with a `-tags=stale` escape hatch) and a **reachability guard** (every record type the client can emit has ≥1 fixture and vice versa). *The reachability guard is precisely what would have caught the 2023 change.*
2. **Fake CloudKit server** (`ckwstest`) — programmable in-memory library with fault injectors: mutate assets mid-pagination, duplicate CPLAssets per master, stale syncToken, 503 on page three, expired cookie. All engine/paging/retry/mirror tests run here. This is the only way to test pagination-under-mutation, which no recording can express.
3. **Live protocol check — manual CLI subcommand, not a scheduled CI job (redesigned 2026-09-22).** Originally speced as a nightly `-tags=live` CI job against a dedicated credentialed test account. Cut: it needs a second iCloud account/device to maintain, and would eventually stall on an unattended 2FA prompt with nobody present to answer it in CI — defeating the point of an automated nightly signal. Replaced by `icloudpd check-protocol`: authenticates with your real account through the normal credential flow (2FA via Telegram, same as any other run), asserts response *structure* only, never content, and prints pass/fail. Run by hand, whenever you want to check — no schedule, no second account, no CI stall risk. Trades automatic early-warning of Apple protocol drift for zero maintenance burden; that tradeoff is explicit, not silent. Fixture regeneration (tier-1, shared redaction) happens as a side effect of a successful `check-protocol` run instead of an automatic nightly job.

Plus: exhaustive table-driven tests for `naming` and `xmp`; a `mirror` test where **all files vanish at once ⇒ must refuse, not submit**; import-graph tests; injected `Clock` in `schedule` so no test sleeps.

---

## Process model: iteratively developed, not upfront-planned

This document is the **architectural constraint set**, not a complete spec. Feature-level design happens per iteration, as it comes up. The structural decisions above — the `Enumerator` seam, store-as-source-of-truth failure semantics, `state_dir` separation, the two-axis credential model, Telegram-only control/escalation surface — are **fixed**, because retrofitting them is expensive. Everything else is designed when its iteration starts.

Driven by the `iterative-development` plugin (`docs/superpowers/iterations/`).

### Governance (deviates from the plugin's defaults — deliberate)

The plugin is built to run unattended for hours and states it *"does NOT prompt 'should I continue?' between iterations."* That conflicts with the standing instruction to stop at every step boundary. Resolution:

- **Autonomous within an iteration.** Tasks inside an iteration run without interruption, gated by the plugin's PAR reviews.
- **STOP at every iteration boundary** — after the audit, before the next iteration — for an explicit go/no-go.
- **STOP on any spike result that changes the architecture** (SRP, syncToken).
- Escalation is *not* catastrophe-only here; the boundary gate is real.

### Sequence

1. **Land the spec.** Write this document into the repo as `docs/superpowers/specs/2026-08-14-go-rewrite-design.md` and commit. The plugin extracts requirements from repo spec collateral, so this must exist first.
2. **syncToken delta spike — standalone, throwaway, gated.** Resend the token Apple already returns (it is discarded today at `photos.py:415-419`) and observe whether the response is a true delta. **Run before scoping**, so the roadmap and `Enumerator` design are built on a known answer rather than revised immediately after. *Report result and stop for a decision.* **Closed 2026-09-08: `delta` deferred, v1 ships `full`-only — see the decision under "Where this design is most likely wrong," point 1.**
3. **`extracting-requirements`** on the spec → `requirements/`, `behavior-scenarios.md`, `behavior-corpus.md`.
4. **`scoping-the-simplest-core`** → `roadmap.md`. **ITER-0000 is the walking skeleton: authenticate → list one asset → download it → record it in the manifest → exit clean.** That is a real journey scenario threading every layer at minimum depth, and it *inherently proves SRP* — the highest-risk component gets validated by working software rather than throwaway spike code. If SRP cannot be made to work, that surfaces in the first iteration.
5. **Loop:** `running-an-iteration` → `auditing-progress` → **stop for go/no-go** → repeat.

Rough ordering for follow-on iterations, subject to the roadmap: harden protocol (`ckws`, `photos`, codec fixtures, `ckwstest`) → core sync (`naming`, `store`, `enumerate/full`, `download`, `syncengine`, `scan` backfill) → service surface (`notify`/`telegram` incl. bot commands, `control`, `status`, `dashboard`) → features (`xmp` with the #32 fixture, `mirror` + Telegram review surface). `delta`/composite is backlogged, not scheduled — see the decision under "Where this design is most likely wrong," point 1.

---

## Verification

- `CGO_ENABLED=0 go build ./...` produces a static binary; image builds `FROM scratch`/distroless and reports size.
- `go test ./...` green, including **import-graph tests** (dashboard cannot reach `secret`/`config`/`auth`/`control`/`sqlite`) and the fixture **freshness + reachability guards**.
- `icloudpd check-protocol`, run by hand against a real account, asserts response structure — no CI job, no dedicated test account (see "Testing" below).
- `icloudpd validate` rejects a malformed config with a clear error; `icloudpd print-config` shows per-field provenance.
- `icloudpd run-once` against a real account downloads, writes manifest rows, and generates XMP sidecars; a second `run-once` downloads **nothing** (manifest-as-source-of-truth proven).
- Rename the folder-structure setting and re-run: files are **not** re-downloaded — the specific failure mode that motivated promoting the manifest.
- `docker stop` mid-run exits within the grace period leaving no partial files and a consistent manifest.
- Rotate the secret file underneath a running container; the new value is picked up with **no restart**.
- Scan the dashboard port: status renders, and no credential form or mutating endpoint exists anywhere in the binary. A wrong password produces a Telegram notify-only message, no reply path; a 2FA prompt produces a Telegram message whose inline reply is accepted exactly once.
- **Deletion-sync, specifically:**
  - Dry-run against a download root whose volume is unmounted **refuses** (sentinel unreadable) rather than proposing deletions.
  - Delete one local file of a Live Photo pair → **no** candidate produced; delete both → candidate produced. Same for multi-size and RAW+JPEG sets.
  - Delete a file, then run with a **truncated** enumerator (`Exhaustive: false`) → **no** candidate produced; run a full sweep → candidate produced.
  - Exceed the threshold → **zero** deletions execute, batch withheld, `deletion_sync_threshold_tripped` fires with real thumbnails in Telegram, and the trip **persists** across a subsequent run.
  - A second run finds more candidates while the batch is still pending → they **merge** into the same batch and a re-notify fires with the updated count, rather than opening a second batch.
  - `/reject <account>` (or `--resolve-deletions=reject`) → files re-download next pass. Pending items are **not** auto-re-downloaded while undecided.
  - Approve a batch after mutating the asset in iCloud → re-verification fetches a fresh `recordChangeTag` and submits successfully; approve a batch whose asset was deleted in iCloud meanwhile → marked skipped, not an error.
  - Trip account A's threshold → account B's deletions still proceed (per-account scoping), and `/approve`/`/reject` without an account argument is rejected as ambiguous.
  - A batch over 10 items pages both directions via inline buttons; `/approve` succeeds without having paged through the whole batch first.
- `/metrics` exposes last-successful-sync timestamp and error counters; `/healthz` and `/readyz` respond correctly before and after a failed run — `/readyz` stays ready as long as at least one account can sync, and only flips not-ready when every account is failing.

---

## Where this design is most likely wrong

1. **The `Cursor`/`Change` seam presumes the delta is asset-shaped.** If `syncToken` turns out to be a cache-validity token ("your view is stale, re-query") rather than a change log, `delta` can never set `ReportsRemovals` and the abstraction degenerates to "full sweep that stops early." The seam survives, but drop the dead flag rather than keeping unused flexibility. **A third option may be what actually ships for 60s polling:** a cheap `HyperionIndexCountLookup` count probe as a *change detector*, with a full sweep only when the count moves. Spike before writing `syncengine`.

   **Decision, 2026-09-08 — deferred, not resolved.** The spike ran (see `2026-08-14-synctoken-delta-spike-findings.md`, updated same date). Confirmed: `syncToken` is a cache-validity/zone-version counter, not a change log, exactly as this point anticipated — `delta` cannot set `ReportsRemovals`. As a *change detector* it beat the count probe on the one case that matters most (a count-neutral edit, e.g. a favourite toggle, which the count probe missed entirely) and both signals correctly caught a real upload. But every result is n=1, on a 20-asset test account, never run against the 4,527-asset production library, and — critically — **no false-negative test has been run**: nothing has yet tried to find a real change the token fails to reflect, which is the case that actually matters for trusting it to gate a skip decision. A concrete follow-up test plan exists (tight-loop polling across five more mutation types — adjustment edits, metadata-only edits, album-only changes, and phone-originated delete/favorite — logged in this conversation, not yet written to a file) but has not been run.

   **Given that gap, v1 ships `full`-only, on a cron schedule, with no `delta`/`composite` enumerator.** Sync freshness equals the cron interval; there is no near-real-time path in v1. This is acceptable because the manifest already deduplicates on every run regardless of enumeration strategy — a full sweep only *downloads* what the manifest doesn't already have — so the cost of full-only is sweep time (~2m15s at production scale, see point 3 below), not redundant downloads. `internal/enumerate/delta/` and the count-probe/token watcher stay backlogged, not deleted: the `Enumerator` seam already accommodates them if latency later becomes a real requirement, and the false-negative test plan is the next step if this gets revisited.
2. **Deletion-mirroring remains the most dangerous feature, and "files are missing" is still a weak signal** even with the locked-in defences. An Immich move-into-managed-library, a rename, a case-sensitivity change, or a half-synced network mount all present identically to "the user deleted this" — and unlike the unmounted-volume case, the sentinel file does **not** catch them, because the volume is genuinely mounted and healthy. The sentinel plus the circuit breaker plus approval-time re-verification are three real layers, but none of them can distinguish intent. Expect this area to be revised at least twice after real-world use, and treat the threshold default of `-1` (off) as load-bearing: the feature should stay opt-in.
3. **One global SQLite DB with a single writer is a scaling guess** — though a safer one than I first assumed. The real production library is **4,527 assets**, and PR #30 already took a full no-op scan from ~8m to ~2m15s by batching manifest commits, so single-writer contention is not a near-term concern at this scale. It becomes one only if libraries grow an order of magnitude or several large accounts sweep concurrently. Escape hatch unchanged: batch writes within an account's run at asset boundaries, which `store.RunTx` already permits without touching callers.
   **However, that same 2m15s figure is decisive for the delta spike:** at ~2m per full sweep, 60-second polling is arithmetically impossible with full enumeration. Delta is therefore not a performance optimization — it is the only thing that makes near-real-time exist at all, and is irrelevant if hourly syncing is acceptable. Decide what you actually want from the spike's result before building on it.
4. **`internal/config` will become a god package** if the per-account config struct is passed whole into the engine. Pass narrow purpose-built structs (`syncengine.Options`, `naming.Policy`, `mirror.Policy`) built in `internal/app`. This is the *exact* discipline whose absence produced a 1,343-line `base.py`.

## Files to consult during implementation

- `src/pyicloud_ipd/services/photos.py` — the protocol surface to port: paging (`photos_request`, `_list_query_gen`, `increment_offset`), `desiredKeys`, zone discovery, duplicate-CPLAsset handling, and the `syncToken` TODO at line 415.
- `src/pyicloud_ipd/base.py` + `session.py` — SRP auth, 2FA/2SA, session/cookie handling.
- `src/icloudpd/base.py` — the 1,343 lines to decompose into `syncengine`, `naming`, `download`, `app`.
- `src/icloudpd/manifest.py` — current schema and best-effort semantics, both deliberately reversed.
- `src/icloudpd/xmp_sidecar.py` — the `adjustmentSimpleDataEnc` path that silently drops Orientation (#32).
