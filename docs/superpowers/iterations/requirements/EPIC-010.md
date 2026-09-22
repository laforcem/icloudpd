# EPIC-010 — Multi-account concurrency

**Summary:** Multi-account concurrency
**Stories:** STORY-0016
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0016

**Epic:** EPIC-010 — Multi-account concurrency
**Title:** Run multiple accounts concurrently with a shared rate limiter and per-phase timeouts

**As a** operator running several iCloud accounts on one deployment
**I want** each account to run in its own goroutine under a shared global rate limiter, with per-phase timeouts and a minimum-speed download threshold
**So that** one hung or slow account cannot starve the others

**Acceptance criteria:**
- AC-1: Accounts run concurrently, one goroutine each; a stalled account does not block progress on other accounts' scheduled runs. · impact:`journey` · seam:`app-level` · scenario:`SCENARIO-0009`
- AC-2: internal/ratelimit enforces one global (not per-account) token bucket across all accounts, defaulting to 2 req/s for API calls and configurable; downloads are unthrottled by this limiter. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0009`
- AC-3: Auth, a single listing page, and a single API call each enforce a 30s per-phase timeout. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0009`
- AC-4: Downloads are bounded by a minimum-speed threshold rather than a flat deadline, so large-but-progressing downloads are not killed by a fixed timeout. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0009`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:14,41,101`

**Status:** pending