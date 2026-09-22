# EPIC-006 — Credentials and session

**Summary:** Credentials and session
**Stories:** STORY-0008, STORY-0009
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/2 done

## STORY-0008

**Epic:** EPIC-006 — Credentials and session
**Title:** Refine session-expiry handling to be low-friction and Telegram-first

**As a** operator
**I want** routine 2FA-driven re-auth handled with a low-friction Telegram flow, and password re-entry requested only on a confirmed Apple auth failure
**So that** the ~99% routine case doesn't require touching a password, and password prompts aren't shown for expirations that are really just 2FA

**Acceptance criteria:**
- AC-1: On a session expiry that Apple resolves via 2FA/2SA, the system prompts via Telegram for a code, never for the password. · impact:`cross-surface` · seam:`app-level` · scenario:`SCENARIO-0004`
- AC-2: A password re-prompt notification is sent only when Apple's auth API returns a confirmed wrong-password/failed-login result (PyiCloudFailedLoginException-equivalent), not on routine session expiry. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0004`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:37,44-50`

**Status:** pending

## STORY-0009

**Epic:** EPIC-006 — Credentials and session
**Title:** Send proactive session-expiry warnings on a configurable cadence

**As a** operator
**I want** a warning notification before a session expires, repeating on an interval until resolved
**So that** I get advance notice rather than discovering an expired session only when a sync run fails

**Acceptance criteria:**
- AC-1: A session-expiry warning fires warning_days before the session is due to expire (default 7). · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0106`
- AC-2: While the warning condition remains unresolved, the warning repeats every notification_interval_hours (default 24) rather than firing only once. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0106`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:187-189`

**Status:** pending