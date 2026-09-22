# EPIC-004 — Deletion mirroring

**Summary:** Deletion mirroring
**Stories:** STORY-0006
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0006

**Epic:** EPIC-004 — Deletion mirroring
**Title:** Mirror local deletions to iCloud Recently Deleted

**As a** operator who deletes local files
**I want** local deletions detected and mirrored as a move to iCloud's Recently Deleted, gated by policy
**So that** local library cleanup stays in sync with iCloud without permanently destroying assets

**Acceptance criteria:**
- AC-1: Deletion detection happens in internal/syncengine by comparing manifest state to filesystem scan results. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0003`
- AC-2: internal/mirror enforces a threshold, batches deletions, requires approval, and only then submits the move-to-Recently-Deleted request to iCloud. · impact:`cross-surface` · seam:`app-level` · scenario:`SCENARIO-0003`
- AC-3: Deletion-mirroring is functionally distinct from and does not resurrect the cut autodelete-after-download feature. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:36,97-98`

**Status:** pending