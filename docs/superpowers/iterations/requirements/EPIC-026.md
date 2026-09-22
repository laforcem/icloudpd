# EPIC-026 — Telegram bot commands

**Summary:** Telegram bot commands
**Stories:** STORY-0082, STORY-0083, STORY-0084, STORY-0085, STORY-0086, STORY-0087, STORY-0088, STORY-0089
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/8 done

## STORY-0082

**Epic:** EPIC-026 — Telegram bot commands
**Title:** Trigger immediate sync via bot command

**As a** bot operator
**I want** to send /sync <account> to trigger an immediate full sweep for that account
**So that** I don't have to wait for the cron schedule when I need a sync now

**Acceptance criteria:**
- AC-1: /sync <account> triggers an immediate full sweep for the named account, running outside the cron schedule. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0066`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:296-301`

**Status:** pending

## STORY-0083

**Epic:** EPIC-026 — Telegram bot commands
**Title:** Approve pending deletion batch via bot command

**As a** bot operator
**I want** to send /approve <account> to release that account's pending deletion-sync batch
**So that** reviewed deletions can proceed

**Acceptance criteria:**
- AC-1: /approve <account> releases the named account's pending deletion-sync batch and all items in it execute. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0067`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:296-301`

**Status:** pending

## STORY-0084

**Epic:** EPIC-026 — Telegram bot commands
**Title:** Reject pending deletion batch via bot command

**As a** bot operator
**I want** to send /reject <account> to discard that account's pending batch
**So that** files I don't want deleted are preserved and simply re-downloaded

**Acceptance criteria:**
- AC-1: /reject <account> discards the named account's pending batch; the corresponding files re-download on the next normal run. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0068`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:296-301`

**Status:** pending

## STORY-0085

**Epic:** EPIC-026 — Telegram bot commands
**Title:** Cancel in-progress sync via bot command

**As a** bot operator
**I want** to send /cancel <account> to stop an in-progress sync run for that account
**So that** I can halt a run without waiting for it to finish

**Acceptance criteria:**
- AC-1: /cancel <account> stops the in-progress sync run for the named account. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0069`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:296-303`

**Status:** pending

## STORY-0086

**Epic:** EPIC-026 — Telegram bot commands
**Title:** Resume account sync via bot command

**As a** bot operator
**I want** to send /resume <account> to undo a cancel or restart a paused account's schedule
**So that** I can bring an account back into normal operation

**Acceptance criteria:**
- AC-1: /resume <account> undoes a prior /cancel for that account, or restarts a paused account's schedule. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0069`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:296-304`

**Status:** pending

## STORY-0087

**Epic:** EPIC-026 — Telegram bot commands
**Title:** Force re-authentication via bot command

**As a** bot operator
**I want** to send /force_reauth <account> to discard the current session and force a fresh login
**So that** I can recover an account stuck on a bad/expired session

**Acceptance criteria:**
- AC-1: /force_reauth <account> discards the account's current session and forces a fresh login on the next attempt. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0070`
- AC-2: The command is registered with BotFather as /force_reauth (underscore), not /force-reauth (dash), since Telegram command names permit only lowercase letters, digits, and underscores. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0070`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:296-305`

**Status:** pending

## STORY-0088

**Epic:** EPIC-026 — Telegram bot commands
**Title:** Read-only status via bot command

**As a** bot operator
**I want** to send /status <account> to see last sync time, error counts, and pending mirror batch state
**So that** I can check on an account without triggering any side effects

**Acceptance criteria:**
- AC-1: /status <account> returns last sync time, error counts, and pending mirror batch state, and causes no state change (read-only). · impact:`local` · seam:`integration` · scenario:`SCENARIO-0071`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:296-306`

**Status:** pending

## STORY-0089

**Epic:** EPIC-026 — Telegram bot commands
**Title:** Require explicit account argument on every account-scoped command

**As a** operator managing multiple iCloud accounts
**I want** every account-scoped bot command to require an explicit <account> argument
**So that** commands are never misapplied to the wrong account when multiple accounts have independent pending state simultaneously

**Acceptance criteria:**
- AC-1: Every account-scoped command (/sync, /approve, /reject, /cancel, /resume, /force_reauth, /status) requires an explicit <account> argument with no implicit 'current account' fallback, even when only one account is configured. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0072`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:308-310`

**Status:** pending