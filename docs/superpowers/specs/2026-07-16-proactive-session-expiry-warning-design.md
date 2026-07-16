# Proactive Session-Expiry Warning — Design

## Context

`notificator_builder` (`src/icloudpd/base.py`) fires a `session_expired` notification only at the moment `icloud.requires_2fa`/`requires_2sa` becomes true (`authentication.py:104-115`). In watch/unattended mode, that's the same run that needed the download — by the time the notification goes out, a scheduled sync has already stalled or been skipped. This is issue #9.

Apple's auth cookies (`X-APPLE-WEBAUTH-USER`, `X_APPLE_WEB_KB-<per-account-hash>`) carry their own `Expires` attribute, confirmed against real server responses in `tests/vcr_cassettes/2fa_flow_valid_code.yml:182-192` and the 2SA cookie fixtures under `tests/fixtures/test_2sa_required_*/cookie/`. Both attach `Expires` on both the 2FA and legacy 2SA flows, so an expiry check doesn't need to distinguish between them. `X_APPLE_WEB_KB` is not a fixed cookie name — it's a prefix (`X_APPLE_WEB_KB-<hash>`), one hash per account.

## Scope

In scope:
- A periodic check, once per successful authentication, that reads the soonest-expiring of the two relevant cookies and fires a new `session_expiring_soon` event (via the existing `notifications.notify()` mechanism, see `2026-07-15-notification-system-design.md`) once remaining time drops below a configurable threshold.
- A configurable warning window (days-before-expiry to start warning) and a configurable max notification cadence (how often to re-warn while inside the window), both per-user config.
- Small persistent state (last-warned timestamp) so cadence is honored across watch-loop iterations and process restarts.

- A `POST /force-reauth` endpoint and Telegram bot handling for `session_expiring_soon`, so a human can act on the warning instead of just reading it — see Telegram integration below.

Out of scope:
- Any change to the reactive `session_expired` event or its call site — that continues to fire exactly as it does today when a run actually hits the 2FA/2SA challenge.
- A general-purpose local key/value or SQL store. This feature's persistence need is a single timestamp; see Architecture for why that doesn't warrant new database infrastructure.
- Non-cookie-based expiry detection (e.g. probing an endpoint to ask iCloud how much session time is left) — cookie `Expires` is sufficient and requires no extra network calls.
- Any change to the `AWAITING_MFA_TRIGGER` state machine or the human-confirms-before-push design from `2026-07-15-telegram-2fa-sidecar-design.md` — the new endpoint below feeds into that machine unchanged, it doesn't alter it.

## Architecture

**Check timing:** once per successful authentication — i.e. every time `authenticator()` returns without raising. In watch mode this means once per `watch_interval` (each iteration re-authenticates and reloads the cookie jar from disk); in single-run, `auth_only`, and `list_*` modes it still runs the one time auth succeeds, since it depends only on the authenticated `PyiCloudService`, not on `user_config.directory` the way `manifest.py` does. This keeps the check aligned with the codebase's existing re-auth cadence rather than introducing new scheduling machinery (a background thread/timer).

**Expiry computation:** from the live `PyiCloudService`'s cookie jar (`icloud.session.cookies`), take the earliest non-`None` `expires` value across `X-APPLE-WEBAUTH-USER` and any cookie whose name starts with `X_APPLE_WEB_KB-` — the earliest is what actually governs when the session breaks, not the latest. If neither cookie is present with expiry data, skip the check silently (debug-log only) rather than warning or erroring; this can happen depending on account/flow variation and must never be treated as a failure.

**State persistence — a JSON file, not a database.** The only state this feature needs is "when did we last warn" per event type — a single timestamp, not a growing or queryable dataset. `manifest.py`'s SQLite approach was considered and rejected: that database is scoped to a download directory and opened only when a download is about to happen (`base.py:959-963`), which doesn't cover `auth_only`/`list_*` invocations and has a different lifecycle than session state (asset manifest lives/dies with a download directory; session state lives/dies with the cookie jar). A dedicated SQLite database for this feature was also considered and rejected as disproportionate to a single value with no concrete second use case in view — introducing a new kind of local-state infrastructure needs a real second consumer to justify it, not a hypothetical one. A small JSON file colocated with the cookie jar, keyed by `event_type` (matching `notifications.py`'s existing open-string `event_type` design — not a new extensibility axis), is proportionate to the actual data shape and reuses an idiom (best-effort local file, JSON) already established elsewhere in the codebase.

State file path mirrors `PyiCloudService.cookiejar_path`/`session_path` (`pyicloud_ipd/base.py:616-629`): same directory, same sanitized-`apple_id` naming scheme, distinct suffix.

```python
def check_and_notify(
    logger: logging.Logger,
    icloud: PyiCloudService,
    username: str,
    notification_script: str | None,
    warning_days: int,
    notification_interval_hours: int,
) -> None: ...
```

Called once, after `authenticator()` returns successfully. A no-op if `notification_script` is `None` (mirrors `notify()`'s own no-op-when-unconfigured behavior) or if no expiring cookie is found.

## State file schema

```json
{
  "session_expiring_soon": {
    "last_warned_utc": "2026-07-15T09:00:00+00:00"
  }
}
```

Keyed by `event_type` so a future second warning type doesn't require a schema change. Missing file, unreadable file, or corrupt JSON are all treated as "never warned" — logged at debug/warning and swallowed, matching `manifest.py`/`notifications.py`'s established "infrastructure must never break the core run" philosophy. Worst case from a corrupt state file is one extra notification, not a crash.

## Event

New `event_type`: `session_expiring_soon`, added to the closed set documented in `2026-07-15-notification-system-design.md`. Built via the existing `notifications.build_event()`:

```python
build_event(
    event_type="session_expiring_soon",
    username=username,
    message=f"{username}'s iCloud session expires in {days_remaining} day(s). Re-authenticate before it lapses to avoid a stalled run.",
    data={"days_remaining": days_remaining, "expires_at_utc": expires_at.isoformat()},
)
```

## Config surface

Two new fields on `UserConfig`, alongside `notification_script`:

- `session_expiry_warning_days: int` — default `7`. `--session-expiry-warning-days`.
- `session_expiry_notification_interval_hours: int` — default `24`. `--session-expiry-notification-interval-hours`.

Per-user (not global) because `notification_script` is already per-user, and these are refinements of that same per-account notification behavior — a multi-account setup may reasonably want different windows/cadences per account.

**On by default whenever `notification_script` is configured** — no separate enable flag. A user who's already set up a notification script for `session_expired` almost certainly wants the proactive version too; a silent opt-in flag nobody discovers would undercut the point of the feature. Setting `--session-expiry-warning-days 0` disables the proactive check for a user who wants `session_expired`-only behavior back.

## Error handling

Matches `manifest.py`/`notifications.py`: best-effort, never raised into the caller. Cookie-jar read issues, state-file read/write failures, and `notify()`'s own failure modes are all logged and swallowed — this check running (or failing to run) must never block or fail a download.

## Telegram integration

`2026-07-15-telegram-2fa-sidecar-design.md` builds a working, human-confirmed 2FA flow, but only *reactively*: it can only act once icloudpd has already hit `requires_2fa` and entered `AWAITING_MFA_TRIGGER`. `session_expiring_soon` fires earlier than that, while the session is still valid — tapping a button at that point can't reuse `/trigger-push` directly, because a plain re-authentication attempt right now would just silently pass the still-good session-token check (`PyiCloudService.authenticate()`, `pyicloud_ipd/base.py:291-298`) and never ask Apple for 2FA at all.

**The missing link is forcing a real login attempt, not skipping straight to the push.** `PyiCloudService` stores its session token in a file separate from the cookie jar — `session_path` (`pyicloud_ipd/base.py:130-137, 623-629`), `<cookie_directory>/<sanitized_apple_id>.session`. Deleting that file makes the next `authenticate()` call skip the token fast-path and perform a full fresh sign-in, which does trigger a real 2FA challenge (`requires_2fa` → `AWAITING_MFA_TRIGGER`) — exactly the state the existing sidecar flow already knows how to drive to completion. No changes to `status.py`'s state machine, `authentication.py`'s request functions, or the deliberate human-confirms-before-push design are needed; this only supplies the missing trigger to *enter* that machine before a run would have hit it on its own.

**New endpoint:**

```
POST /force-reauth
body: {"username": "..."}
```

Looks up the matching `UserConfig` via `StatusExchange.get_user_configs()` (already exposed, `status.py:115-121`), computes that account's `session_path` the same way `PyiCloudService` does, deletes it best-effort (missing file is a silent no-op, not an error), then sets `progress.resume = True` — reusing the existing `/resume` mechanism (`server/__init__.py:99-101`) that already wakes the watch loop early from its interval sleep. No new state-machine transitions.

**Bot flow addition (`integrations/telegram-bot/`):**

1. `session_expiring_soon` fires and is forwarded to the bot the same way `session_expired` is today (see the sidecar design's bot flow step 1).
2. Bot sends a DM naming the account and days remaining, with one button — e.g. "Refresh session now" — that calls `POST /force-reauth` with that `username`.
3. Within moments, the watch loop wakes, re-authenticates for real, and — because the session token was cleared — Apple requires 2FA. This fires `session_expired` and enters `AWAITING_MFA_TRIGGER`, which the bot already handles: it sends the existing "Start 2FA" message and button (sidecar design, bot flow step 2) completely unchanged.
4. From there, the rest of the flow (push trigger, code entry, success/failure) is exactly what's already built — no new code path.

This is a deliberate two-tap flow, not one button that also fires the push: the sidecar design specifically split "session needs 2FA" from "push has been sent" so a push is never sent without a human explicitly asking (`2026-07-15-telegram-2fa-sidecar-design.md`, "Problem with today's push behavior"). Collapsing that gate for this entry point only would mean two different code paths could trigger a real push to your phone — one gated, one not. Keeping `/force-reauth` and `/trigger-push` as separate, sequential taps preserves that guarantee everywhere.

This also means `2026-07-15-telegram-2fa-sidecar-design.md`'s non-goal ("Proactive expiry warning... is a separate, valuable feature, tracked as issue #9. Not part of this design.") is superseded for the specific piece of wiring a warning into the bot's existing state machine — the sidecar design's own flow and non-goals are otherwise unchanged.

## Testing

- Unit tests for expiry computation: earliest-of-two-cookies selection, missing-cookie skip, cookie present but no `expires` attribute.
- Unit tests for state-file read/write: fresh file creation, cadence suppression (warned recently → no second notify), cadence expiry (warned outside interval → notify again), corrupt/missing file treated as never-warned.
- Integration-style test at the `core_single_run` call site: successful auth with a near-expiry cookie fixture produces a `session_expiring_soon` event on the notification script's stdin, following the same pattern as the existing `test_2sa_required_notification_script_receives_json_event` style test.
- No new VCR cassette needed — expiry cookies already appear in existing fixtures/cassettes.
- `POST /force-reauth`: unit tests for username lookup (found/not-found → 404), session-file deletion (present/absent, both succeed), and `progress.resume` being set on success.
- Sidecar e2e (excluded from core CI, matching the sidecar design's existing testing section): full flow from a `session_expiring_soon` event through "Refresh session now", the automatic transition into the existing "Start 2FA" prompt, and on through code entry — run manually before cutting a release that includes it.
