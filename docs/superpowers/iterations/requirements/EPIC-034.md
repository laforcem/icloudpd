# EPIC-034 — Secret Management

**Summary:** Secret Management
**Stories:** STORY-0118
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0118

**Epic:** EPIC-034 — Secret Management
**Title:** Pick up rotated secrets without a restart

**As a** operator
**I want** secret-file rotation to take effect while the container keeps running
**So that** credential rotation never requires downtime

**Acceptance criteria:**
- AC-1: Rotating the secret file underneath a running container causes the new value to be picked up with no restart. · impact:`journey` · seam:`process-level` · scenario:`SCENARIO-0090`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:385`

**Status:** pending