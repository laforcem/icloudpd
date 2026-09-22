# EPIC-009 — Scheduling

**Summary:** Scheduling
**Stories:** STORY-0015
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0015

**Epic:** EPIC-009 — Scheduling
**Title:** Run scheduling on cron expressions with required per-account schedule

**As a** operator configuring multiple accounts
**I want** cron-expression scheduling per account (with `every: 1h` sugar desugaring to the same engine), required in config with no implicit default
**So that** schedules are precise (e.g. "3am nightly") and I can't accidentally run with an unintended default schedule

**Acceptance criteria:**
- AC-1: `icloudpd validate` rejects a config that omits `schedule` for an account; it does not silently apply `0 3 * * *` or any other default. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0007`
- AC-2: An `every: 1h` schedule value is desugared into the same cron-based timer engine as an explicit cron expression, producing equivalent scheduled runs. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0007`
- AC-3: The scheduler is timer-driven and context-cancellable, replacing the 1-second sleep/tqdm polling loop; it does not wake every second when idle. · impact:`none` · seam:`unit`
- AC-4: A `/sync <account>` Telegram command triggers an immediate run for that account in addition to its schedule. · impact:`cross-surface` · seam:`app-level` · scenario:`SCENARIO-0007`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:5,40`

**Status:** pending