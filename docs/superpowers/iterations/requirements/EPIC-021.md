# EPIC-021 — Manifest schema

**Summary:** Manifest schema
**Stories:** STORY-0040, STORY-0041, STORY-0042, STORY-0043, STORY-0044, STORY-0140
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/6 done

## STORY-0040

**Epic:** EPIC-021 — Manifest schema
**Title:** Use one shared SQLite manifest DB for the whole service

**As a** operator
**I want** a single WAL-mode database at <state_dir>/icloudpd.db shared across all accounts
**So that** operations stay simple (one WAL file, one backup target, one place to look) rather than requiring per-account or per-directory databases

**Acceptance criteria:**
- AC-1: The service opens exactly one database file at <state_dir>/icloudpd.db in WAL mode, regardless of the number of configured accounts or download directories. · impact:`local` · seam:`integration`
- AC-2: No cross-account database transaction is ever required or performed, since mirror batches, thresholds, and trip state are strictly per-account elsewhere in the design. · impact:`none` · seam:`integration`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:149-157`

**Status:** pending

## STORY-0041

**Epic:** EPIC-021 — Manifest schema
**Title:** Identify assets by CPLMaster recordName, collapsing metadata-only duplicates

**As a** engine developer
**I want** the assets table primary key to be (account_id, zone_kind, zone_name, record_name) where record_name is the CPLMaster recordName, and duplicate CPLAsset metadata versions to collapse by newest addedDate
**So that** CPLAsset.recordName churn (metadata versioning) does not create duplicate asset identities in the manifest

**Acceptance criteria:**
- AC-1: Two CPLAsset records with different recordName values but the same CPLMaster recordName resolve to a single row in the assets table, keyed on the CPLMaster recordName. · impact:`local` · seam:`integration`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:149-157`

**Status:** pending

## STORY-0140

**Epic:** EPIC-021 — Manifest schema
**Title:** Apply collision policy and removal tracking to asset identity

**As a** engine developer
**I want** duplicate CPLAsset metadata versions to collapse by newest addedDate, and the assets table to track last_seen_run and removed_remote_utc
**So that** the manifest correctly resolves record-name churn and supports later reconciliation

**Acceptance criteria:**
- AC-1: When duplicate asset records collide, the one with the newest addedDate wins (preserving the Python `_pick_newer_asset_record` semantics). · impact:`local` · seam:`unit`
- AC-2: The assets table tracks last_seen_run and removed_remote_utc per asset. · impact:`none` · seam:`integration`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:149-157`

**Split note:** split from STORY-0041 during ITER-0000 scope review — a single-asset, single-run walking skeleton never produces a colliding duplicate or a removal to exercise these ACs; committing to this policy now would be speculative design ahead of evidence. Deferred to the core-sync iteration alongside the rest of the manifest schema.

**Status:** pending

## STORY-0042

**Epic:** EPIC-021 — Manifest schema
**Title:** Store per-file rows relative to the account download root

**As a** operator
**I want** the files table (1:N from assets) to record version_size, role, rel_path relative to the account download root, and missing_since_utc
**So that** remounting the download volume at a different absolute path does not orphan the manifest

**Acceptance criteria:**
- AC-1: rel_path values stored in the files table are relative to the account's download root, not an absolute filesystem path. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0029`
- AC-2: After the account download root is remounted at a new absolute path, existing files rows still resolve to the correct on-disk files via their stored rel_path. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0029`
- AC-3: Each files row records a role of exactly one of primary, live_photo_video, raw, or sidecar_xmp. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:149-157`

**Status:** pending

## STORY-0043

**Epic:** EPIC-021 — Manifest schema
**Title:** Detect deletion candidates via the all-rows-missing rule

**As a** operator
**I want** an asset to become a deletion-mirroring candidate only when every non-sidecar files row for it has been missing since at least the previous run and is confirmed missing again this run
**So that** Live Photo companions, multi-size variants, and RAW+JPEG pairs are only mirrored-deleted when the whole asset is truly gone, via a fixed one-run debounce rather than a separate time-based threshold

**Acceptance criteria:**
- AC-1: An asset with at least one files row (excluding role='sidecar_xmp') that is present on disk this run is NOT a deletion candidate, even if its other file roles are missing. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0030`
- AC-2: An asset becomes a deletion candidate only after two consecutive runs confirm every non-sidecar files row missing (missing_since_utc set on the first run, reconfirmed missing on the second) — a fixed one-run debounce, not a configurable time-based threshold. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0030`
- AC-3: sidecar_xmp files rows are excluded from the all-rows-missing evaluation entirely; their presence or absence does not affect whether an asset is a deletion candidate. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0030`
- AC-4: There is no config key named `deletion_sync.debounce` or similar time-based debounce setting; the two-run debounce is inherent to the reconciliation query and is not user-configurable. (It must not be confused with `deletion_sync.threshold`, which is a batch-size trip point.) · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:149-157`

**Status:** pending

## STORY-0044

**Epic:** EPIC-021 — Manifest schema
**Title:** Preserve store.RunTx's per-asset-boundary batching escape hatch

**As a** engine developer
**I want** store.RunTx to permit batching writes at asset boundaries within an account's run
**So that** a future scale-driven need to reduce write overhead doesn't require changing caller code

**Acceptance criteria:**
- AC-1: store.RunTx supports batching multiple asset writes into a single transaction at asset boundaries, without requiring changes to the calling code in syncengine. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:409`

**Status:** pending