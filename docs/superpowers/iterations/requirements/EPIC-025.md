# EPIC-025 — Health/metrics

**Summary:** Health/metrics
**Stories:** STORY-0080, STORY-0081
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/2 done

## STORY-0080

**Epic:** EPIC-025 — Health/metrics
**Title:** Expose an always-on health/metrics listener independent of the dashboard

**As a** container orchestrator or Prometheus scraper
**I want** a separate listener serving /healthz, /readyz, /metrics that runs regardless of dashboard.enabled
**So that** liveness/readiness/metrics work for a container-first deployment even with the optional dashboard turned off

**Acceptance criteria:**
- AC-1: The health/metrics listener starts and runs independent of dashboard.enabled — it exists whether or not the dashboard is turned on. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0063`
- AC-2: The listener serves only /healthz, /readyz, and /metrics; it exposes no status data and no account names. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0063`
- AC-3: /metrics uses standard Prometheus exposition format via prometheus/client_golang, scrapable by any standard scraper without a translation layer. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0063`
- AC-4: /readyz flips to not-ready only on total failure (every account down); one hung account among several does not flip it. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0063`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:290-292`

**Status:** pending

## STORY-0081

**Epic:** EPIC-025 — Health/metrics
**Title:** Bind the health/metrics listener to all interfaces by default

**As a** Prometheus operator scraping from a separate pod
**I want** the health/metrics listener to default to 0.0.0.0:9090
**So that** the scraper has real network reachability instead of only loopback, since this listener carries no credentials or account data

**Acceptance criteria:**
- AC-1: The health/metrics listener's default bind is 0.0.0.0:9090, unlike the dashboard's loopback default. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0065`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:293-294`

**Status:** pending