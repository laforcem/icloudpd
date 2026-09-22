# EPIC-003 — Notifications

**Summary:** Notifications
**Stories:** STORY-0004, STORY-0005
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/2 done

## STORY-0004

**Epic:** EPIC-003 — Notifications
**Title:** Provide extensible notifier interface with first-party webhook channel

**As a** operator or contributor
**I want** a generic Notifier interface with a webhook implementation as the extension point
**So that** new notification channels can be added via PR without modifying core sync logic

**Acceptance criteria:**
- AC-1: internal/notify defines a Notifier interface and Event type consumed by fanout/retry logic, independent of any specific channel implementation. · impact:`none` · seam:`unit`
- AC-2: The webhook notifier POSTs a JSON envelope {event, account, timestamp, data} to a configured URL, retries 3 times with exponential backoff on failure, then logs and drops the event. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0002`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:34,111-113`

**Status:** pending

## STORY-0005

**Epic:** EPIC-003 — Notifications
**Title:** Ship Telegram bot as first-party reference notifier and control channel

**As a** operator
**I want** Telegram bundled into the main project as the reference notifier plus 2FA/control channel
**So that** I don't need a separate sidecar integration to get 2FA handling and control commands

**Acceptance criteria:**
- AC-1: Telegram notifier and command listener live under internal/notify/telegram in the main binary, not a separate integrations/telegram-bot project. · impact:`none` · seam:`unit`
- AC-2: The Telegram bot serves both as an Event notifier and as the bot-command bus entry point into internal/control. · impact:`cross-surface` · seam:`app-level`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:35,109-110`

**Status:** pending