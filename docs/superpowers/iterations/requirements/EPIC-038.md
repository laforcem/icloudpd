# EPIC-038 — Enumerator Strategy (v1 scope)

**Summary:** Enumerator Strategy (v1 scope)
**Stories:** STORY-0131
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0131

**Epic:** EPIC-038 — Enumerator Strategy (v1 scope)
**Title:** Ship v1 with a full-sweep-only enumerator, no delta/composite

**As a** maintainer
**I want** v1 to use only the `full` enumeration strategy on a cron schedule, keeping `delta`/count-probe code backlogged but not deleted
**So that** shipping isn't blocked on the unresolved trust question of whether syncToken can safely gate a skip decision

**Acceptance criteria:**
- AC-1: v1's Enumerator ships with `full` only; no `delta` or `composite` enumerator is scheduled or wired into `syncengine`. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0103`
- AC-2: Sync freshness in v1 equals the configured cron interval; there is no near-real-time enumeration path. · impact:`none` · seam:`integration`
- AC-3: `internal/enumerate/delta/` and the count-probe/token-watcher code remain present in the codebase as backlogged, not deleted, so the `Enumerator` seam can accommodate them later. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:401-403`

**Status:** pending