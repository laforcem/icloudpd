# EPIC-024 — Concurrency

**Summary:** Concurrency
**Stories:** STORY-0074, STORY-0075, STORY-0076, STORY-0077, STORY-0078, STORY-0079
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/6 done

## STORY-0074

**Epic:** EPIC-024 — Concurrency
**Title:** Run each account's sync in its own isolated goroutine

**As a** system running multiple iCloud accounts
**I want** one goroutine per account owning that account's session with no shared mutex
**So that** the runner itself is the serialization point and one account's failure never aborts another

**Acceptance criteria:**
- AC-1: Each account is owned by exactly one goroutine holding that account's session state; no mutex guards cross-account session access. · impact:`none` · seam:`process-level`
- AC-2: A non-cancelling errgroup is used: a per-account failure is logged and published to status, but never aborts sibling account goroutines. · impact:`cross-surface` · seam:`process-level` · scenario:`SCENARIO-0055`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:268-269`

**Status:** pending

## STORY-0075

**Epic:** EPIC-024 — Concurrency
**Title:** Throttle API calls with a single process-global rate limiter

**As a** system with multiple accounts
**I want** one process-global rate.Limiter shared across every account for API calls
**So that** adding accounts never multiplies total request rate against Apple

**Acceptance criteria:**
- AC-1: A single process-global rate.Limiter governs API calls and is shared across every account goroutine (not one limiter per account). · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0055`
- AC-2: Downloads are unthrottled by any byte-rate limiter; rate_limit_per_sec scopes only to API calls. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0055`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:268-272`

**Status:** pending

## STORY-0076

**Epic:** EPIC-024 — Concurrency
**Title:** Apply per-phase timeouts instead of a per-account timeout

**As a** system processing many accounts
**I want** auth/enumeration-page/modify calls bound by a flat 30s timeout, and downloads bound by a minimum-speed threshold instead
**So that** one hung account or one large file cannot starve or kill other work

**Acceptance criteria:**
- AC-1: Auth, one enumeration page, and one modify call each use a flat 30s timeout. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0055`
- AC-2: One file download is bounded by a minimum-speed threshold, not the flat 30s deadline, so a large file isn't killed early just for being large. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0055`
- AC-3: A hung phase in one account's goroutine does not starve or delay other accounts' progress. · impact:`journey` · seam:`process-level` · scenario:`SCENARIO-0055`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:268-272`

**Status:** pending

## STORY-0077

**Epic:** EPIC-024 — Concurrency
**Title:** Skip an overlapping cron tick instead of queuing it

**As a** scheduler
**I want** to skip a scheduled tick when that account's previous run is still in progress
**So that** each account's timeline stays simple with no backlog to work through

**Acceptance criteria:**
- AC-1: If an account's run is still in progress when its next scheduled tick fires, that tick is skipped rather than queued. · impact:`local` · seam:`process-level` · scenario:`SCENARIO-0057`
- AC-2: The skipped tick is not made up; the account waits for its next regularly scheduled time. · impact:`local` · seam:`process-level` · scenario:`SCENARIO-0057`
- AC-3: A skipped tick is visible in /status and /metrics. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0057`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:273`

**Status:** pending

## STORY-0078

**Epic:** EPIC-024 — Concurrency
**Title:** Serialize all SQLite writes through one dedicated writer goroutine

**As a** system with multiple account goroutines sharing a store
**I want** all store writes funneled through a single writer goroutine over a channel
**So that** write collisions become queueing rather than SQLITE_BUSY retries or spurious errors

**Acceptance criteria:**
- AC-1: All store writes across every account goroutine are sent to and executed by one dedicated writer goroutine, never issued directly by multiple goroutines concurrently. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0058`
- AC-2: No busy-timeout/retry-on-SQLITE_BUSY logic is used per account goroutine; collisions are resolved by queueing at the writer. · impact:`none` · seam:`integration`
- AC-3: A write that reaches the writer goroutine either succeeds or fails for a real reason — never fails from losing a lock race. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0058`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:274`

**Status:** pending

## STORY-0079

**Epic:** EPIC-024 — Concurrency
**Title:** Shut down gracefully without corrupting in-flight work

**As a** operator stopping the service
**I want** shutdown to stop runners between assets, discard partial downloads, and commit completed store state before closing
**So that** kill -9 or a graceful stop loses at most one in-progress asset

**Acceptance criteria:**
- AC-1: Shutdown sequence is: root cancel → HTTP Shutdown → runners stop between assets → store commits → close. · impact:`journey` · seam:`process-level` · scenario:`SCENARIO-0059`
- AC-2: Partial downloads in progress at shutdown are discarded via the temp+rename pattern, never left as corrupt partial files at the final path. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0059`
- AC-3: Because transactions are per-asset, a kill -9 loses at most one asset's worth of progress. · impact:`journey` · seam:`process-level` · scenario:`SCENARIO-0059`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:275-276`

**Status:** pending