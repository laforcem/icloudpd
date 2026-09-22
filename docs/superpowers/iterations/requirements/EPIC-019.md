# EPIC-019 — Enumeration seam

**Summary:** Enumeration seam
**Stories:** STORY-0033, STORY-0034, STORY-0035, STORY-0036, STORY-0037
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 1/5 done

## STORY-0033

**Epic:** EPIC-019 — Enumeration seam
**Title:** Model enumeration as a change stream with capability declaration

**As a** engine developer
**I want** an Enumerator interface that yields a stream of Present/Removed changes plus an opaque cursor and a Capabilities struct
**So that** the engine can support multiple enumeration strategies (full, delta, composite) without restructuring

**Acceptance criteria:**
- AC-1: Enumerator.Capabilities() returns a struct with ReportsRemovals, Exhaustive, and Resumable booleans, and Enumerate(ctx, from Cursor, yield) returns an updated opaque Cursor that is persisted verbatim without the engine interpreting its contents. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0117`
- AC-2: The `full` enumerator reports Capabilities{ReportsRemovals:false, Exhaustive:true, Resumable:true}. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0117`

**Scope fix (ITER-0000 PAR scope review):** AC-2 previously also required a `delta` enumerator reporting `{true, false, true}`. The design spec (`docs/superpowers/specs/2026-08-14-go-rewrite-design.md:88`) explicitly marks `internal/enumerate/delta/` "DEFERRED for v1, backlogged" — not just deferred to a later iteration but excluded from v1 entirely. Committing a delta-enumerator capability assertion to the very first iteration contradicted that decision. The delta clause is cut; if delta is ever un-backlogged, its capability contract is scoped to whichever iteration actually builds it. Added scenario:`SCENARIO-0117` (new, dedicated integration test — JOURNEY-0001's single-account run doesn't itself exercise Capabilities() field values).

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:121-143`

**Status:** done:ITER-0000

## STORY-0034

**Epic:** EPIC-019 — Enumeration seam
**Title:** Reconcile deletions only when the run's capabilities justify it

**As a** engine developer
**I want** reconciliation logic to conclude an asset is gone only if the run completed without error AND (Exhaustive with not-seen-in-sweep OR ReportsRemovals with an explicit Removed change)
**So that** a delta run can never mass-prune the manifest and full/delta can coexist safely

**Acceptance criteria:**
- AC-1: Given a run that reports Exhaustive=true and ReportsRemovals=false, an asset not observed during the sweep is treated as removed only if the run completed without error. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0023`
- AC-2: Given a run that reports Exhaustive=false and ReportsRemovals=false (e.g. a delta run with no explicit removal signal), no asset absent from that run's stream is marked as removed, regardless of run outcome. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0023`
- AC-3: Reconciliation branches on the Capabilities values returned by the enumerator, never on a type switch or name check against the enumerator implementation. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:121-143`

**Status:** pending

## STORY-0035

**Epic:** EPIC-019 — Enumeration seam
**Title:** Support a composite enumerator combining delta and full sweeps

**As a** operator
**I want** a composite enumerator (delta every 60s, full sweep nightly) that satisfies the same Enumerator interface
**So that** the engine requires no changes to support mixed-cadence enumeration strategies

**Acceptance criteria:**
- AC-1: A composite enumerator implementing delta-every-60s plus nightly-full runs through the identical engine code path as a standalone full or delta enumerator, with no engine-side special-casing. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0025`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:121-143`

**Status:** pending

## STORY-0036

**Epic:** EPIC-019 — Enumeration seam
**Title:** Deduplicate enumeration pages by asset key instead of trusting offsets

**As a** engine developer
**I want** paging state to be {startRank, expected_count} with dedup by asset.Key performed in the store
**So that** a mutating server-side index causes at worst re-visits, never silent skips of assets

**Acceptance criteria:**
- AC-1: When the server-side index shifts mid-enumeration (causing rank/offset drift), the store deduplicates re-visited assets by asset.Key rather than the enumerator relying on offset arithmetic to avoid duplicates. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0026`
- AC-2: The Python `increment_offset(-1)` workaround (base.py:1238) has no equivalent in the Go implementation; offset-decrementing logic is not present. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:121-143`

**Status:** pending

## STORY-0037

**Epic:** EPIC-019 — Enumeration seam
**Title:** Support syncing a Shared Photo Library zone via sync_scope.library

**As a** operator with a Shared Photo Library
**I want** sync_scope.library to accept a Shared Photo Library zone name instead of only PrimarySync
**So that** I can sync a shared library the same way I sync my primary library

**Acceptance criteria:**
- AC-1: Setting sync_scope.library to a Shared Photo Library zone name causes that zone to be enumerated and synced instead of PrimarySync. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0111`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:191`

**Status:** pending