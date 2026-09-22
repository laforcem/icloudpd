# EPIC-023 — Deletion-mirroring

**Summary:** Deletion-mirroring
**Stories:** STORY-0060, STORY-0061, STORY-0062, STORY-0063, STORY-0064, STORY-0065, STORY-0066, STORY-0067, STORY-0068, STORY-0069, STORY-0070, STORY-0071, STORY-0072, STORY-0073
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/14 done

## STORY-0060

**Epic:** EPIC-023 — Deletion-mirroring
**Title:** Detect local deletions during the sync loop, not in a separate pass

**As a** sync engine
**I want** to check the manifest for a prior-run row when an iCloud asset's local files are missing
**So that** the deletion candidate is caught before the normal loop silently re-downloads it (defeating the auto-heal race)

**Acceptance criteria:**
- AC-1: When processing an asset present in iCloud but missing locally, the engine checks the manifest for an existing (record_name, rel_path) row from a previous run before treating it as a fresh download. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0042`
- AC-2: internal/syncengine owns detection; internal/mirror owns policy (threshold, batching, approval, submission) — detection logic must not implement threshold/approval behavior and vice versa. · impact:`none` · seam:`unit`
- AC-3: Detection reuses the asset already fetched during the sync loop and issues no additional iCloud API round trip. · impact:`none` · seam:`integration`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:236-244`

**Status:** pending

## STORY-0061

**Epic:** EPIC-023 — Deletion-mirroring
**Title:** Restrict deletion-candidate production to exhaustive runs

**As a** sync engine
**I want** to produce deletion candidates only from runs that completed without error and reported Capabilities.Exhaustive
**So that** truncated enumerations (until_found/recent) never falsely flag unseen assets as deleted

**Acceptance criteria:**
- AC-1: A run may produce deletion candidates only if its Enumerator completed without error AND reported Capabilities.Exhaustive. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0043`
- AC-2: Enumerations using until_found or recent modes never produce deletion candidates, since they stop before visiting all assets past the stop point. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0043`
- AC-3: In a composite enumerator, a 60s delta tick (non-exhaustive) produces no deletion candidates while a nightly full sweep (exhaustive) does, with no flag-combination bans required at startup. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0043`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:245-249`

**Status:** pending

## STORY-0062

**Epic:** EPIC-023 — Deletion-mirroring
**Title:** Isolate manifest state from media storage failures

**As a** operator
**I want** the manifest to live on its own volume separate from /data
**So that** a dropped media mount produces a loud manifest-vs-filesystem mismatch instead of a silent manifest reset

**Acceptance criteria:**
- AC-1: The manifest database resides at state_dir, a location distinct from the /data media mount. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0044`
- AC-2: state_dir must be RWO local/block storage; NFS is disallowed for state_dir due to SQLite's documented issues with buggy POSIX locking and unreliable fsync. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0044`
- AC-3: /data may safely be RWX/NFS without affecting manifest integrity. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:250-252`

**Status:** pending

## STORY-0063

**Epic:** EPIC-023 — Deletion-mirroring
**Title:** Gate scans on a liveness sentinel before treating them as authoritative

**As a** sync engine
**I want** to require a per-download-root sentinel file to be readable before any scan counts as authoritative
**So that** an unmounted source is never misread as "everything is gone" (the rsync footgun)

**Acceptance criteria:**
- AC-1: A per-download-root sentinel file must be successfully read before a scan's results are treated as authoritative. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0045`
- AC-2: The liveness check runs before deletion detection, not as a post-hoc sanity check after candidates are already produced. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0045`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:253-254`

**Status:** pending

## STORY-0064

**Epic:** EPIC-023 — Deletion-mirroring
**Title:** Enforce deletion-sync circuit breaker precedence between enabled and threshold

**As a** operator
**I want** deletion_sync.enabled to act as the master switch over deletion_sync.threshold
**So that** a disabled feature never detects or acts on anything, and threshold semantics only apply once the feature is on

**Acceptance criteria:**
- AC-1: When deletion_sync.enabled is false, nothing is ever detected or acted on, regardless of the value of threshold. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0046`
- AC-2: When enabled is true and threshold is -1, deletions are unbounded (no cap), matching rclone sync --max-delete's -1 semantics. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0046`
- AC-3: When enabled is true and threshold is a positive N, it is compared against a cumulative count, not a single run's batch size. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0046`
- AC-4: No opinionated default value is shipped for threshold when enabled; the user must supply a value. · impact:`none` · seam:`unit`
- AC-5: icloudpd validate emits a warning (does not block) when enabled: true is paired with threshold: -1, since this combination is almost always an unedited example value rather than an intentional choice. · impact:`local` · seam:`app-level` · scenario:`SCENARIO-0046`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:255-260`

**Status:** pending

## STORY-0065

**Epic:** EPIC-023 — Deletion-mirroring
**Title:** Track deletion threshold cumulatively across runs, not per run

**As a** operator
**I want** threshold to compare against the total count of unresolved candidates the account currently holds
**So that** a slow leak of a few missing files per night from a flaky mount cannot bypass the breaker by always staying under N in any single run

**Acceptance criteria:**
- AC-1: The trip check sums outstanding/recently-auto-deleted mirror_items rows within a rolling window across runs, not just the newly-found batch of the current run. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0048`
- AC-2: A sequence of several runs, each individually finding fewer than N missing files, still trips the breaker once the cumulative count reaches N. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0048`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:260-262`

**Status:** pending

## STORY-0066

**Epic:** EPIC-023 — Deletion-mirroring
**Title:** Automate below-threshold deletions without per-item review

**As a** operator
**I want** deletions below the threshold to execute automatically
**So that** the common case is fully automated and reviewing every deletion doesn't defeat the point of automation

**Acceptance criteria:**
- AC-1: When the cumulative candidate count stays below threshold, matching items are deleted and logged automatically with no per-item review gate, and a deletion_sync_summary event is emitted informationally after the fact. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0049`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:262-263`

**Status:** pending

## STORY-0067

**Epic:** EPIC-023 — Deletion-mirroring
**Title:** Withhold the entire batch and stay tripped until manually cleared

**As a** operator
**I want** the whole batch withheld with zero deletions once threshold is reached, remaining tripped until I resolve it
**So that** a large unexpected deletion event pauses for human review instead of partially executing

**Acceptance criteria:**
- AC-1: At/above threshold, the entire batch is withheld (zero deletions execute) and a deletion_sync_threshold_tripped event is emitted. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0050`
- AC-2: The tripped state persists across subsequent runs until manually cleared via /approve or /reject. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0050`
- AC-3: New candidates discovered on later runs while tripped merge into the same pending batch rather than opening a second batch. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0050`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:263-266`

**Status:** pending

## STORY-0068

**Epic:** EPIC-023 — Deletion-mirroring
**Title:** Resolve a withheld deletion batch via a single approve/reject enum

**As a** operator
**I want** a single --resolve-deletions={approve,reject} CLI flag or /approve, /reject Telegram command
**So that** resolution can't be expressed as an invalid state (both or neither flag set) and pending items only leave limbo via explicit decision

**Acceptance criteria:**
- AC-1: Resolution is exposed as a single enum (approve|reject) via --resolve-deletions on the CLI and /approve <account> / /reject <account> in Telegram — never as two independent booleans. · impact:`cross-surface` · seam:`app-level` · scenario:`SCENARIO-0051`
- AC-2: Choosing reject causes the affected files to be re-downloaded on the next normal sync pass. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0051`
- AC-3: Pending items are exempt from auto-redownload while undecided; resolving the batch is the only exit from limbo. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0051`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:255-267`

**Status:** pending

## STORY-0069

**Epic:** EPIC-023 — Deletion-mirroring
**Title:** Re-verify withheld items both remotely and locally before approving deletion

**As a** sync engine
**I want** each withheld item re-checked against iCloud and against the local filesystem at approval time
**So that** an approval acted on days after the batch was created is still correct despite a stale recordChangeTag or a locally-reappeared file

**Acceptance criteria:**
- AC-1: On approve, each item gets a remote lookup for a current recordChangeTag; items already gone remotely are marked skipped_reappeared/gone instead of erroring. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0051`
- AC-2: On approve, each item also gets a local filesystem check at its rel_path; items whose file has reappeared locally since the batch was created are dropped from the batch. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0051`
- AC-3: Approval produces a correct outcome regardless of how long the batch sat withheld (both checks run per item, not just the remote one). · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0051`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:236-266`

**Status:** pending

## STORY-0070

**Epic:** EPIC-023 — Deletion-mirroring
**Title:** Scope deletion threshold and trip state per account under concurrency

**As a** operator running multiple accounts concurrently
**I want** the deletion threshold and its trip state tracked per account
**So that** one account's bulk cleanup cannot withhold or interfere with another account's legitimate deletions

**Acceptance criteria:**
- AC-1: threshold and trip state are maintained independently per account. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0053`
- AC-2: A batch tripping the breaker for account A does not withhold or block deletions for account B. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0053`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:236-266`

**Status:** pending

## STORY-0071

**Epic:** EPIC-023 — Deletion-mirroring
**Title:** Deliver deletion review payloads as paged Telegram thumbnails

**As a** operator reviewing a withheld batch
**I want** deletion_sync_summary and deletion_sync_threshold_tripped events to include the count plus a first page of real thumbnails delivered as Telegram photo messages
**So that** I can review even a large trip without a capability URL to a page that no longer exists

**Acceptance criteria:**
- AC-1: deletion_sync_summary and deletion_sync_threshold_tripped carry count plus first page of real thumbnails delivered as Telegram photo messages; no capability URL is used. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0054`
- AC-2: A 4,000-item trip pages through the review 10 items at a time via inline buttons rather than a single unusable message. · impact:`local` · seam:`e2e` · scenario:`SCENARIO-0054`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:236-266`

**Status:** pending

## STORY-0072

**Epic:** EPIC-023 — Deletion-mirroring
**Title:** Store minimal withheld-row data and fetch thumbnails on demand

**As a** sync engine
**I want** withheld rows to store only record_name, filename, and asset date
**So that** thumbnails can be fetched live for Telegram without persisting image data on disk

**Acceptance criteria:**
- AC-1: A withheld row stores exactly record_name, filename, and asset date — enough to fetch a THUMB-size JPEG on demand. · impact:`none` · seam:`unit`
- AC-2: Thumbnails are fetched live from iCloud when needed and are never stored on disk. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0054`
- AC-3: Video records carry a JPEG poster-frame thumbnail in the same field, so review code needs no photo/video branching. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0054`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:236-266`

**Status:** pending

## STORY-0073

**Epic:** EPIC-023 — Deletion-mirroring
**Title:** Keep deletion undo/restore explicitly out of scope

**As a** product owner
**I want** no undo/restore feature built even though it is technically possible
**So that** the feature doesn't duplicate iCloud's own Recently Deleted UI

**Acceptance criteria:**
- AC-1: No restore/undo capability is implemented for deletion-mirroring, despite a confirmed-feasible remote records/modify path with isDeleted: {value: 0}. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:236-266`

**Status:** pending