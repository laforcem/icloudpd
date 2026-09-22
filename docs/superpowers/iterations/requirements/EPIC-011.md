# EPIC-011 — Operability

**Summary:** Operability
**Stories:** STORY-0017, STORY-0018
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/2 done

## STORY-0017

**Epic:** EPIC-011 — Operability
**Title:** Expose health, readiness, metrics, structured logs, and graceful shutdown with resumable downloads

**As a** operator running icloudpd under an orchestrator
**I want** always-on /healthz, /readyz, and /metrics, JSON structured logging, graceful shutdown, and resumable downloads
**So that** the service is observable and orchestrator-manageable, and a shutdown or restart doesn't lose in-flight download progress

**Acceptance criteria:**
- AC-1: internal/web/health runs an always-on internal listener independent of dashboard.enabled, exposing /healthz, /readyz, and Prometheus-format /metrics. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0009`
- AC-2: /readyz only flips to not-ready when every configured account is failing; a single hung account among several does not flip readiness to not-ready. · impact:`cross-surface` · seam:`app-level` · scenario:`SCENARIO-0009`
- AC-3: Logs are emitted in JSON via internal/obs' slog setup. · impact:`none` · seam:`unit`
- AC-4: On shutdown signal, the service cancels contexts gracefully and an in-progress download can be resumed (ranged resume) on the next run rather than restarting from scratch. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0009`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:42,89,103,118`

**Status:** pending

## STORY-0018

**Epic:** EPIC-011 — Operability
**Title:** Classify errors as retryable or fatal for logging and metrics

**As a** operator monitoring logs and metrics
**I want** internal/obs to classify each error as retryable or fatal before it is logged or counted
**So that** transient network hiccups are distinguishable from permanent failures in logs and dashboards

**Acceptance criteria:**
- AC-1: internal/obs classifies an error as retryable or fatal before emitting it to logs/metrics, and this classification is reflected in the emitted log fields or metric labels. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0113`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:109`

**Status:** pending