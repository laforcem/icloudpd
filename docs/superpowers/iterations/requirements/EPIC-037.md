# EPIC-037 — Observability

**Summary:** Observability
**Stories:** STORY-0130
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0130

**Epic:** EPIC-037 — Observability
**Title:** Expose sync health via metrics and Kubernetes-style health probes

**As a** operator
**I want** /metrics, /healthz, and /readyz endpoints that reflect real per-account sync state
**So that** I can monitor sync freshness and gate orchestration on whether syncing is actually working

**Acceptance criteria:**
- AC-1: `/metrics` exposes last-successful-sync timestamp and error counters. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0102`
- AC-2: `/healthz` and `/readyz` respond correctly both before and after a failed run. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0102`
- AC-3: `/readyz` stays ready as long as at least one account can sync, and flips not-ready only when every account is failing. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0102`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:398-399`

**Status:** pending