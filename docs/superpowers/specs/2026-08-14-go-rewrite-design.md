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
| **Web UI** | **KEEP, split into two security domains** (below). |
| **Scheduling** | **REPLACE.** Cron expressions primary, `every: 1h` sugar desugared into the same engine. Timer-driven, context-cancellable. |
| **Multi-account** | **REPLACE.** Concurrent, one goroutine per account, global rate limiter, per-phase timeouts. |
| **Health/readiness, JSON logging, Prometheus metrics, graceful shutdown + resumable downloads** | **ADD** — all four. None exist today. |
| **Review surface (#29)** | **ADD.** Needs live `THUMB`-size thumbnails (~46KB) fetched on demand and never stored, since withheld items are by definition absent locally. |

**Secrets:** vendor-agnostic. One interface — a **file containing the value, watched with fsnotify** so external rotation (Doco-CD + Bitwarden Secrets Manager, Docker secrets, K8s volumes, Vault Agent) is picked up live without restart. **No vendor SDK.** This upgrades today's read-once-at-startup behavior, which the current spec lists as an explicit non-goal.

**Credential model** (resolves #27's flattened `password_providers` list) — two axes:
- *Source chain*, all non-interactive: watched file → env var → in-memory cache (last known-good, RAM only, never serialized).
- *Escalation policy*: when no source yields a **working** credential, notify over Telegram → capability URL or inline reply → value lands only in the memory cache.
- The memory cache is what breaks **#28's deadlock**: proactive 2FA refresh works with no on-disk password.

**Delivery:** one binary, `serve` as container default, plus `validate` / `print-config` / `run-once` / `migrate`. **Clean break on state** — fresh auth, fresh manifest rebuilt by scanning existing files on disk; Apple's cookie format need not be ported. **Rewrite in place on a long-lived branch**; the Python version stays available by release tag.

---

## Architecture

### Package layout

```
cmd/icloudpd/                 main(): subcommand dispatch
internal/cli/                 serve, validate, print-config, run-once, migrate
internal/app/                 COMPOSITION ROOT — the only package that wires concrete types

── domain (no outward deps) ──
internal/asset/               Key, Asset, Version, VersionSize, ItemType, Zone
internal/naming/              filename + folder-structure policy (pure functions)
internal/xmp/                 sidecar generation (pure)

── protocol ──
internal/icloud/srp/          SRP-6a + PBKDF2 s2k. Pure crypto, no HTTP.
internal/icloud/auth/         sign-in, 2FA/2SA, trust, cookie jar, session persistence
internal/icloud/ckws/         CloudKit transport: records/query, batch, zones/list, records/modify
internal/icloud/photos/       CPLMaster/CPLAsset → asset.Asset; zone discovery; thumbnails; delete

── engine ──
internal/enumerate/           Enumerator interface + Change/Cursor/Capabilities
internal/enumerate/full/      full-sweep (startRank paging) — day-one implementation
internal/enumerate/delta/     syncToken enumerator — post-spike, may never exist
internal/syncengine/          per-account run loop: enumerate → decide → download → record
internal/download/            ranged resume, atomic temp+rename, integrity check
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
internal/notify/telegram/     first-party notifier + command listener
internal/notify/webhook/      generic HTTP POST notifier
internal/control/             command bus: Cancel, Resume, ForceReauth, Approve/RejectBatch
internal/ratelimit/           global + per-account token buckets
internal/config/              YAML load, defaults, validation, redacted printing
internal/obs/                 slog setup, metrics, retry classification

── presentation, split by security domain ──
internal/status/              READ-ONLY view model. No secret-capable types. 
internal/web/dashboard/       always-on read-only server. Imports status + thumbproxy ONLY.
internal/web/thumbproxy/      opaque-handle thumbnail proxy
internal/web/capability/      ephemeral credential entry: single-use URLs, TTL
```

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

One DB for the whole service at `<state_dir>/icloudpd.db`, WAL mode — not one per download directory, because cross-account mirror batches need a single transaction domain.

- `assets` — PK `(account_id, zone_kind, zone_name, record_name)`. `record_name` is the **CPLMaster** recordName; `CPLAsset.recordName` is metadata versioning, *not* identity (preserve `_pick_newer_asset_record`'s newest-`addedDate`-wins duplicate collapsing). Carries `last_seen_run`, `removed_remote_utc`.
- `files` — 1:N from assets. `version_size` + `role` (`primary | live_photo_video | raw | sidecar_xmp`), `rel_path` **relative to the account download root** so remounting doesn't orphan the manifest, `missing_since_utc`.
- `cursors`, `mirror_batches`, `mirror_items`, `schema_migrations`.

Deletion-mirroring semantics fall out as one query: an asset is a candidate when **every** `files` row for it — excluding `role='sidecar_xmp'` — has `missing_since_utc` older than the threshold. That is exactly the "all rows missing" rule for Live Photo companions, multi-size, and RAW+JPEG.

### Deletion-mirroring (#5) — locked-in design, carried forward

This design was settled over several prior sessions and is documented in issue #5's comments. It is **not open for re-derivation**; the Go rewrite ports it, with three gaps resolved below.

**Detection happens in the sync loop, not in a reconciliation pass.** When the engine processes an asset that is present in iCloud but whose local files are missing, it checks whether the manifest already holds a row for that `(record_name, rel_path)` **from a previous run**. If so, it is a deletion candidate rather than a re-download. This exists specifically to defeat the **auto-heal race** — a separate end-of-run pass would lose, because the normal loop would silently re-download the deleted file before deletion-sync ever saw it was gone. `internal/mirror` therefore owns *policy* (threshold, batching, approval, submission); `internal/syncengine` owns *detection*. Detection reuses the already-fetched asset, so no extra iCloud round trip.

**Only an exhaustive run may produce deletion candidates.** Truncated enumeration blinds detection: `until_found`/`recent` stop early, so locally-deleted assets past the stop point are never visited. Python had to solve this by **rejecting those flag combinations at startup** (fail fast, not a runtime warning). The Go `Enumerator` seam generalizes it: **a run may produce deletion candidates only if it completed without error and reported `Capabilities.Exhaustive`.** This is the same rule the store already uses to conclude "gone from iCloud," and it makes the composite enumerator safe by construction — a 60s delta tick simply never produces candidates, while the nightly full sweep does. No flag-combination bans needed.

**`state_directory` is a safety mechanism.** The manifest lives on its **own volume**, separate from `/data`. When the media mount drops (NFS/SMB reverting to an empty local directory), the manifest survives, so "manifest says 4,527 rows, filesystem shows 3" stays a loud signal instead of the manifest resetting to empty alongside it and having nothing to compare against. **Constraint:** `state_directory` must be **RWO local/block storage — never NFS** (SQLite's docs: buggy POSIX locking, unreliable `fsync`). `/data` may safely be RWX/NFS.

**Liveness gate.** A per-download-root sentinel file must be readable before any scan counts as authoritative. This is the classic rsync footgun — an unmounted source reading as "everything is gone" — and it runs *before* detection, not as a post-hoc sanity check.

**Circuit breaker.** Absolute count, **not** a percentage. Default `-1` (off), matching `rclone sync --max-delete` — the correct analog, since this is one-directional like `sync`, not bidirectional like `bisync`.
- *Below threshold:* delete, log, emit `deletion_sync_summary` (informational, after the fact).
- *At/above threshold:* **the entire batch is withheld, zero deletions execute**, emit `deletion_sync_threshold_tripped`, and **stay tripped across subsequent runs** until manually cleared.

**Resolution.** `--resolve-deletions={approve,reject}` — a single enum, never two booleans (which would let both or neither be passed). `reject` causes those files to be re-downloaded on the next normal pass. **Pending items are exempt from auto-redownload while undecided**, so resolving is the only exit from limbo; it never resolves itself.

**No undo/restore — deliberately out of scope.** Note for future sessions: restore is **confirmed technically possible** — a HAR capture of iCloud.com's own Recover button shows the same `records/modify` endpoint, same `CPLAsset` type, `operationType: update`, with `isDeleted: {"value": 0}`, returning 200. It is excluded anyway because iCloud's Recently Deleted already covers regret-recovery, and duplicating a UI Apple maintains is scope creep. **Do not "helpfully" add this.**

**Three gaps resolved for the rewrite:**

1. **Stale `recordChangeTag` on approval.** A withheld batch may sit for days, by which point the stored tag is stale and the asset may have changed or been deleted in iCloud already. **On approve, re-verify each item against iCloud** to obtain a current tag before submitting. Items already gone remotely are marked `skipped_reappeared`/gone rather than erroring; items that reappeared locally are dropped from the batch. One lookup per item, and approval is correct regardless of how long the batch sat.
2. **Threshold scope under concurrency.** Accounts now run concurrently (they were sequential in Python), so the threshold is **per-account**, with per-account trip state. One account's bulk cleanup must not withhold another's legitimate deletions, and thresholds relate to library size, which differs per account.
3. **Event payload shape.** `deletion_sync_summary` / `deletion_sync_threshold_tripped` carry the **count plus a capped sample (~10 filenames + dates), plus a capability URL to the review surface.** A 4,000-item trip must not produce an unusable Telegram message or exceed message size limits, but the full list stays one tap away.

**Withheld-row data model:** `record_name`, filename, and asset date — enough for the review surface to render something recognizable by fetching a `THUMB`-size JPEG live on demand. Video records carry a JPEG poster-frame thumbnail in the same field, so no photo/video branching. Nothing is stored.

**Now-moot interactions:** the issue lists open questions about `--auto-delete` / `--delete-after-download` interaction. Both are **cut**, so those questions disappear.

### Concurrency

One goroutine per account owning that account's session (no mutex; the runner *is* the serialization point). Process-global `rate.Limiter` for API calls and a separate one for download bytes. **Timeouts are per phase, not per account** — auth, one enumeration page, one file download, one modify — which is what actually fixes "one hung account starves the others." Use a **non-cancelling** errgroup: a per-account failure is logged and published to status, never aborts siblings.

Graceful shutdown: root cancel → HTTP `Shutdown` → runners stop *between assets* (partial downloads discarded via temp+rename) → store commits → close. Per-asset transactions mean `kill -9` loses at most one asset.

### Web UI security domains — enforced, not conventional

1. **Type-level.** `secret.Value` has no exported field and overrides `String`, `GoString`, `MarshalJSON`, `MarshalText` → `[redacted]`. `%v`, `json.Marshal`, and `html/template` cannot print it. Only escape hatch is `Use(func([]byte) error)`.
2. **Package-level.** `internal/status` is the dashboard's *entire* view model and imports only stdlib + `internal/asset`. The projection `config + runtime → status.Snapshot` happens explicitly in `internal/app`, field by field — a whitelist by construction, not a redaction pass.
3. **Enforced by test.** `TestDashboardImportGraph` shells `go list -deps ./internal/web/dashboard` and asserts the transitive set excludes `internal/secret`, `internal/config`, `internal/icloud/auth`, `internal/control`, `internal/web/capability`, `internal/store/sqlite`. **This turns "don't do that" into a red build.** Mirror test for `capability`.

**Thumbnail proxy** is the one real leak and gets a narrow seam: the dashboard holds only a `Fetcher` interface plus opaque `Handle`s that arrived on a `status.Snapshot`. It cannot enumerate, cannot fetch originals, cannot mint a handle for an asset it wasn't given. Handles are minted only when a batch enters `withheld` and expire with it.

**Capability server** owns a listener that does not exist until `Escalation.Request` is called: mints a 256-bit path segment, publishes the URL via `notify`, blocks on submit/cancel/TTL, then `Shutdown`s and zeroes the route. Single-use via an `atomic.Bool` swapped before form parsing. No persistent route table means no "form exists but unreachable" state to get wrong.

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

1. **Codec tests** — fixtures test only parse/serialize, each with `{recorded_at, record_type, redaction_version}` metadata. Two guards: a **freshness guard** (fixtures older than N days fail loudly, with a `-tags=stale` escape hatch) and a **reachability guard** (every record type the client can emit has ≥1 fixture and vice versa). *The reachability guard is precisely what would have caught the 2023 change.*
2. **Fake CloudKit server** (`ckwstest`) — programmable in-memory library with fault injectors: mutate assets mid-pagination, duplicate CPLAssets per master, stale syncToken, 503 on page three, expired cookie. All engine/paging/retry/mirror tests run here. This is the only way to test pagination-under-mutation, which no recording can express.
3. **Live contract test** (`-tags=live`, nightly, credentialed) — asserts *structure* only, never content; failure opens an issue. Recordings cannot detect protocol drift; only a live probe can. This job also regenerates tier-1 fixtures with shared redaction, so freshness is automatic.

Plus: exhaustive table-driven tests for `naming` and `xmp`; a `mirror` test where **all files vanish at once ⇒ must refuse, not submit**; import-graph tests; injected `Clock` in `schedule` so no test sleeps.

---

## Process model: iteratively developed, not upfront-planned

This document is the **architectural constraint set**, not a complete spec. Feature-level design happens per iteration, as it comes up. The structural decisions above — the security-domain package split, the `Enumerator` seam, store-as-source-of-truth failure semantics, `state_directory` separation, the two-axis credential model — are **fixed**, because retrofitting them is expensive. Everything else is designed when its iteration starts.

Driven by the `iterative-development` plugin (`docs/superpowers/iterations/`).

### Governance (deviates from the plugin's defaults — deliberate)

The plugin is built to run unattended for hours and states it *"does NOT prompt 'should I continue?' between iterations."* That conflicts with the standing instruction to stop at every step boundary. Resolution:

- **Autonomous within an iteration.** Tasks inside an iteration run without interruption, gated by the plugin's PAR reviews.
- **STOP at every iteration boundary** — after the audit, before the next iteration — for an explicit go/no-go.
- **STOP on any spike result that changes the architecture** (SRP, syncToken).
- Escalation is *not* catastrophe-only here; the boundary gate is real.

### Sequence

1. **Land the spec.** Write this document into the repo as `docs/superpowers/specs/2026-08-14-go-rewrite-design.md` and commit. The plugin extracts requirements from repo spec collateral, so this must exist first.
2. **syncToken delta spike — standalone, throwaway, gated.** Resend the token Apple already returns (it is discarded today at `photos.py:415-419`) and observe whether the response is a true delta. **Run before scoping**, so the roadmap and `Enumerator` design are built on a known answer rather than revised immediately after. *Report result and stop for a decision.*
3. **`extracting-requirements`** on the spec → `requirements/`, `behavior-scenarios.md`, `behavior-corpus.md`.
4. **`scoping-the-simplest-core`** → `roadmap.md`. **ITER-0000 is the walking skeleton: authenticate → list one asset → download it → record it in the manifest → exit clean.** That is a real journey scenario threading every layer at minimum depth, and it *inherently proves SRP* — the highest-risk component gets validated by working software rather than throwaway spike code. If SRP cannot be made to work, that surfaces in the first iteration.
5. **Loop:** `running-an-iteration` → `auditing-progress` → **stop for go/no-go** → repeat.

Rough ordering for follow-on iterations, subject to the roadmap: harden protocol (`ckws`, `photos`, codec fixtures, `ckwstest`) → core sync (`naming`, `store`, `enumerate/full`, `download`, `syncengine`, `scan` backfill) → service surface (`notify`/`telegram`, `control`, `status`, `dashboard`, `capability`, escalation) → features (`xmp` with the #32 fixture, `mirror` + review surface, `delta`/composite if the spike succeeded).

---

## Verification

- `CGO_ENABLED=0 go build ./...` produces a static binary; image builds `FROM scratch`/distroless and reports size.
- `go test ./...` green, including **import-graph tests** (dashboard cannot reach `secret`/`config`/`auth`/`control`/`capability`/`sqlite`) and the fixture **freshness + reachability guards**.
- `go test -tags=live` authenticates against a real account and asserts response structure.
- `icloudpd validate` rejects a malformed config with a clear error; `icloudpd print-config` shows per-field provenance.
- `icloudpd run-once` against a real account downloads, writes manifest rows, and generates XMP sidecars; a second `run-once` downloads **nothing** (manifest-as-source-of-truth proven).
- Rename the folder-structure setting and re-run: files are **not** re-downloaded — the specific failure mode that motivated promoting the manifest.
- `docker stop` mid-run exits within the grace period leaving no partial files and a consistent manifest.
- Rotate the secret file underneath a running container; the new value is picked up with **no restart**.
- Scan the dashboard port: status renders, and no credential form or mutating endpoint exists. Trigger an auth escalation; confirm the capability URL arrives over Telegram, works exactly once, and 404s after.
- **Deletion-mirroring, specifically:**
  - Dry-run against a download root whose volume is unmounted **refuses** (sentinel unreadable) rather than proposing deletions.
  - Delete one local file of a Live Photo pair → **no** candidate produced; delete both → candidate produced. Same for multi-size and RAW+JPEG sets.
  - Delete a file, then run with a **truncated** enumerator (`Exhaustive: false`) → **no** candidate produced; run a full sweep → candidate produced.
  - Exceed the threshold → **zero** deletions execute, batch withheld, `deletion_sync_threshold_tripped` fires, and the trip **persists** across a subsequent run.
  - `--resolve-deletions=reject` → files re-download next pass. Pending items are **not** auto-re-downloaded while undecided.
  - Approve a batch after mutating the asset in iCloud → re-verification fetches a fresh `recordChangeTag` and submits successfully; approve a batch whose asset was deleted in iCloud meanwhile → marked skipped, not an error.
  - Trip account A's threshold → account B's deletions still proceed (per-account scoping).
- `/metrics` exposes last-successful-sync timestamp and error counters; `/healthz` and `/readyz` respond correctly before and after a failed run.

---

## Where this design is most likely wrong

1. **The `Cursor`/`Change` seam presumes the delta is asset-shaped.** If `syncToken` turns out to be a cache-validity token ("your view is stale, re-query") rather than a change log, `delta` can never set `ReportsRemovals` and the abstraction degenerates to "full sweep that stops early." The seam survives, but drop the dead flag rather than keeping unused flexibility. **A third option may be what actually ships for 60s polling:** a cheap `HyperionIndexCountLookup` count probe as a *change detector*, with a full sweep only when the count moves. Spike before writing `syncengine`.
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
