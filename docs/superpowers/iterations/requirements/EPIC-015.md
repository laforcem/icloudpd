# EPIC-015 — Credentials escalation

**Summary:** Credentials escalation
**Stories:** STORY-0023, STORY-0024, STORY-0025, STORY-0026, STORY-0027
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/5 done

## STORY-0023

**Epic:** EPIC-015 — Credentials escalation
**Title:** Escalate 2FA/2SA requirement via Telegram inline reply, disambiguated by message threading

**As a** operator managing multiple iCloud accounts through one Telegram chat
**I want** a 2FA/2SA prompt sent to Telegram, resolved by replying inline to that specific prompt message, using Telegram's native reply-to linking to disambiguate simultaneous requests
**So that** I never have to type an account name to say which account a code belongs to, even when two accounts need a code at once

**Acceptance criteria:**
- AC-1: On a 2FA/2SA-required auth result, the bot sends an "account X needs a code" prompt message to the chat and accepts a reply-to that message as the code for account X. · impact:`cross-surface` · seam:`app-level` · scenario:`SCENARIO-0006`
- AC-2: When two accounts request a code concurrently in the same chat, a reply to account A's prompt message is applied to account A even while account B's prompt is also outstanding, using Telegram's reply-to-message linkage rather than any new command syntax. · impact:`journey` · seam:`app-level` · scenario:`SCENARIO-0006`
- AC-3: The entered 2FA code is never persisted to disk; it is used ephemerally to complete the auth exchange. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:46-47`

**Status:** pending

## STORY-0024

**Epic:** EPIC-015 — Credentials escalation
**Title:** Notify-only on confirmed wrong password with no escalation path

**As a** operator
**I want** a confirmed wrong-password result to produce an awareness-only Telegram notification, never a prompt to type a password into Telegram
**So that** a real credential value is never entered into a chat, and the run correctly stays failed until the file is fixed

**Acceptance criteria:**
- AC-1: On a confirmed wrong-password auth result, the system sends a Telegram notification stating the password file is wrong; no inline-reply value is accepted or expected in response. · impact:`cross-surface` · seam:`app-level` · scenario:`SCENARIO-0005`
- AC-2: The account's sync run continues to fail on every subsequent attempt until the watched password file is corrected out of band; there is no automatic escalation path that resolves it otherwise. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0005`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:48-49`

**Status:** pending

## STORY-0025

**Epic:** EPIC-015 — Credentials escalation
**Title:** Require Telegram configuration at validate time

**As a** operator
**I want** `icloudpd validate` to refuse a config with no Telegram bot token configured
**So that** a deployment cannot silently run until the first routine 2FA prompt deadlocks with no way to resolve it

**Acceptance criteria:**
- AC-1: `icloudpd validate` fails with a clear error when `telegram.bot_token_file` is unset. · impact:`local` · seam:`process-level` · scenario:`SCENARIO-0018`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:51`

**Status:** pending

## STORY-0026

**Epic:** EPIC-015 — Credentials escalation
**Title:** Break the #28 deadlock via proactive 2FA refresh with no on-disk password

**As a** operator
**I want** proactive 2FA/session refresh to work using the in-memory credential cache without requiring a password on disk
**So that** the previously shipped deadlock between session-refresh and password-on-disk requirements cannot recur

**Acceptance criteria:**
- AC-1: Given a previously successful auth with the password cached only in memory, a proactive 2FA refresh can complete without reading a password from disk. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0016`
- AC-2: After a process restart occurring between initial auth and the next 2FA refresh, the memory cache is empty and a fresh 2FA prompt may be required; this is a documented accepted limitation, not a regression from a specific pre-cache baseline. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0016`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:57`

**Status:** pending

## STORY-0027

**Epic:** EPIC-015 — Credentials escalation
**Title:** Accept a 2FA inline reply exactly once per prompt

**As a** operator
**I want** a reply to an already-resolved 2FA prompt to be rejected or ignored
**So that** a stray or duplicate reply cannot be replayed against a prompt that already succeeded

**Acceptance criteria:**
- AC-1: After a 2FA prompt's inline reply has been accepted and the code consumed, a second reply to the same prompt message is not accepted and has no further effect. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0109`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:386`

**Status:** pending