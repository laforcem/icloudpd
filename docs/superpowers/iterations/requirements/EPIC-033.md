# EPIC-033 — Process Lifecycle & Reliability

**Summary:** Process Lifecycle & Reliability
**Stories:** STORY-0117
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0117

**Epic:** EPIC-033 — Process Lifecycle & Reliability
**Title:** Shut down cleanly within a grace period

**As a** operator
**I want** the process to exit promptly on stop, leaving no partial files and a consistent manifest
**So that** interrupting a running container never corrupts on-disk state

**Acceptance criteria:**
- AC-1: `docker stop` issued mid-run causes the process to exit within the configured grace period. · impact:`journey` · seam:`process-level` · scenario:`SCENARIO-0089`
- AC-2: After such a stop, no partial files remain on disk. · impact:`journey` · seam:`process-level` · scenario:`SCENARIO-0089`
- AC-3: After such a stop, the manifest is left in a consistent state. · impact:`journey` · seam:`process-level` · scenario:`SCENARIO-0089`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:384`

**Status:** pending