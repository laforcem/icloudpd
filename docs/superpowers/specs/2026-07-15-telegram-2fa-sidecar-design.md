# Telegram 2FA Sidecar — Design

## Context

icloudpd's WebUI (`src/icloudpd/server/`) already lets a human supply a 2FA code remotely: it exposes `GET /status`, `POST /code`, `POST /password`, `POST /resume`, `POST /cancel` over a `StatusExchange` state machine (`src/icloudpd/status.py`). Today the only client for this is a browser. `notifications.py` (see `2026-07-15-notification-system-design.md`) separately fires a `session_expired` event at a user-configured script — outbound only, fire-and-forget, no callback.

Running icloudpd unattended (watch mode, e.g. on vm101) means nobody is watching a browser tab when 2FA expires. The goal: get a Telegram message when 2FA is needed, and be able to supply the code from Telegram — with real buttons, not a bare text ping.

This is being prototyped against a spare, unused bot token before any change touches the production workload on vm101. No production migration happens until a stable release is cut from this work.

## Non-goals

- **Proactive expiry warning** (alerting before a run actually blocks on 2FA, using the cookie's own expiry timestamp) is a separate, valuable feature, tracked as [issue #9](https://github.com/laforcem/icloudpd/issues/9). Not part of this design.
- **Multi-device SMS selection.** The WebUI-driven auth path (`request_2fa_web`) only supports the single trusted-device push flow (`authentication.py:250-262`) — the SMS/device-index branch (`request_2fa`) is a separate console-only path the WebUI never uses. Nothing to select, so no device-choice buttons.
- **Group chat support.** Not designed against, but not deliberately prevented either — Telegram inline buttons work the same in group chats; if it happens to work there, fine, but DMs are the target.
- **Maintenance commitment.** This ships as an optional, unsupported integration (see Repo layout). It is explicitly not held to the same bar as core icloudpd — if Telegram's API changes and breaks it, that's a "fix it if you feel like it" problem, not a tracked bug.

## Problem with today's push behavior

`trigger_push_notification()` — a real `PUT /verify/trusteddevice/securitycode` call that causes Apple to push a code to your trusted device — currently fires unconditionally and immediately inside `request_2fa_web`, the instant icloudpd detects `requires_2fa`. It was added in `a20050f`/`67abe4a` to work around Apple's 2026 auth flow requiring this call before any code is delivered at all — not as a deliberate "push proactively" design choice.

Net effect: today, the moment a scheduled run finds an expired session, your phone gets a push immediately, with nobody having asked for it. This design defers that call until a human explicitly asks for it via Telegram.

## State machine changes

`Status` (`status.py`) is renamed for clarity (verb-first: `AWAITING_*` / `SUBMITTED_*` / `VALIDATING_*`) and gains one new value, splitting what "2FA is needed" used to mean into "known, not yet pushed" vs. "pushed, awaiting code":

| Old name | New name | Meaning |
|---|---|---|
| `NO_INPUT_NEEDED` | `IDLE` | Nothing pending |
| *(new)* | `AWAITING_MFA_TRIGGER` | 2FA required, notified, push **not yet** sent |
| `NEED_MFA` | `AWAITING_MFA_CODE` | Push sent, waiting for a code |
| `SUPPLIED_MFA` | `SUBMITTED_MFA_CODE` | Code handed off, not yet claimed for validation |
| `CHECKING_MFA` | `VALIDATING_MFA_CODE` | Atomically claimed, validating against Apple |
| `NEED_PASSWORD` | `AWAITING_PASSWORD` | Unrelated password flow, untouched |
| `SUPPLIED_PASSWORD` | `SUBMITTED_PASSWORD` | — |
| `CHECKING_PASSWORD` | `VALIDATING_PASSWORD` | — |

`SUBMITTED_MFA_CODE` → `VALIDATING_MFA_CODE` stays a distinct transition (not collapsed into one state): it's an atomic compare-and-swap that lets the polling auth thread claim the payload before reading it, preventing a race with the HTTP handler that just wrote it. The gap is milliseconds and not meant to be human-observable — it exists for correctness, not UX.

**New transitions:**
- `authenticator()` detecting `requires_2fa` now moves `IDLE → AWAITING_MFA_TRIGGER` and fires the `session_expired` notify event, but does **not** call `trigger_push_notification()`.
- A new `POST /trigger-push` endpoint moves `AWAITING_MFA_TRIGGER → AWAITING_MFA_CODE` and, only on that transition, calls `trigger_push_notification()`. Returns 409 if the current status isn't `AWAITING_MFA_TRIGGER`.
- On a failed code (`set_error`), the failure path now drops back to `AWAITING_MFA_TRIGGER` (not `AWAITING_MFA_CODE`) — a wrong code requires an explicit new push request, not silent retry against a stale one.

This is a core, platform-agnostic change (touches `status.py`, `authentication.py`, `server/__init__.py`) — not Telegram-specific logic. Any WebUI-style consumer benefits from not getting an unsolicited push.

## Bot flow (`integrations/telegram-bot/`)

1. `session_expired` fires (icloudpd is now in `AWAITING_MFA_TRIGGER`). The configured `notification_script` is a small, fast script that forwards the JSON payload it receives on stdin to a local endpoint on the always-running bot process, then exits immediately — it must not block waiting on human interaction, since `notify()` enforces a ~10s timeout.
2. The bot sends an informative Telegram DM naming the account (`username` from the event payload) with a "Start 2FA" button. No code is expected yet — you can ignore this message and do other things with the bot.
3. Tapping "Start 2FA" calls `POST /trigger-push` on icloudpd (over the shared Docker Compose network) and puts the bot into code-expecting mode for that chat.
4. You paste the 6-digit code as a plain message (no slash command) — only accepted because the bot is in that mode. The bot `POST`s it to `/code`.
5. On success: bot confirms authentication succeeded, *then* leaves code-expecting mode.
6. On failure: bot reports the failure with two buttons — "Try again" (re-invokes step 3) and "Exit" (leaves code-expecting mode; this is bot-side only — icloudpd's own wait loop has no cancel path and is unaffected, it just keeps waiting in `AWAITING_MFA_TRIGGER`/`AWAITING_MFA_CODE` as it always would with nobody watching).

**Multi-account:** icloudpd processes user configs sequentially against one shared `StatusExchange` (`base.py:310-321`, a plain `for` loop, not concurrent) — only one account can ever be pending at a time. No routing logic is needed in the bot or the endpoints; the `username` field already on `NotificationEvent` is enough to say which account each message is about.

## Network / auth model

Sidecar runs as its own container on the same Docker Compose network as icloudpd, reaching it by service name (e.g. `http://icloudpd:8080`). No auth is added to `/trigger-push` or the existing endpoints — the private compose network is the trust boundary, equivalent to localhost. This is acceptable for a personal, unsupported integration; revisit if the sidecar is ever placed on a network icloudpd doesn't also trust.

## Repo layout

`integrations/telegram-bot/` — own directory, own Dockerfile, own README stating no support/maintenance commitment, excluded from core CI/test/release surface. Named for the bot generally (not `telegram-2fa`) since it's expected to grow beyond 2FA into a general Telegram consumer of the notification system (e.g. future deletion-sync events) without a rename.

Bot implemented with **aiogram** (async-first, clean inline-keyboard/callback_query support).

## Testing

- Core (`status.py`, `authentication.py`, `server/__init__.py`): unit tests for the renamed states, the new `AWAITING_MFA_TRIGGER` transition, `/trigger-push` (success + 409-when-not-pending), and the failure path dropping back to `AWAITING_MFA_TRIGGER` instead of `AWAITING_MFA_CODE`.
- Sidecar: e2e test against a real, otherwise-unused Telegram bot token — full flow from `notify()` firing through button tap, code entry, and success confirmation. Excluded from core CI (matches its unsupported status), run manually before cutting a release that includes it.

## Open questions

None blocking. Proactive expiry warning (issue #9) is intentionally out of scope here.
