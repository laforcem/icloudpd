# EPIC-020 — Store failure semantics

**Summary:** Store failure semantics
**Stories:** STORY-0038, STORY-0039
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 1/2 done

## STORY-0038

**Epic:** EPIC-020 — Store failure semantics
**Title:** Treat store write failures as fatal run errors

**As a** operator
**I want** a manifest store write failure to abort the run for that account rather than being swallowed
**So that** the manifest can be trusted as the source of truth instead of silently drifting from reality

**Acceptance criteria:**
- AC-1: When a store write fails during a run, the run for that account terminates with a fatal error instead of continuing the download loop. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0027`
- AC-2: Telemetry writes remain best-effort: a telemetry write failure does not abort the run. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0027`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:145-147`

**Status:** done:ITER-0000

## STORY-0039

**Epic:** EPIC-020 — Store failure semantics
**Title:** Key cursors by enumerator_id so strategies keep independent state

**As a** operator
**I want** cursor state stored per (account, enumerator_id)
**So that** switching between full and delta enumeration strategies requires no data migration

**Acceptance criteria:**
- AC-1: The `cursors` table keys rows by enumerator_id (in addition to account), so a `full` cursor and a `delta` cursor for the same account are stored and read independently. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0028`
- AC-2: Switching an account's configured enumeration strategy (e.g. full to delta) does not require deleting or migrating existing cursor rows; the new strategy simply has no prior cursor for its own enumerator_id and starts fresh while the old strategy's cursor remains untouched. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0028`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:145-147`

**Status:** pending