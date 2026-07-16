# General Notification System — Design

## Context

icloudpd currently has exactly one notification path, and it is hardcoded to a single event: two-step/two-factor authentication expiring. `notificator_builder` (`src/icloudpd/base.py`) is wired to one call site, deep inside the auth flow (`base.py:936`), and offers two built-in delivery mechanisms:

- **Email**, via `send_2sa_notification` (`src/icloudpd/email_notifications.py`) — a hardcoded SMTP send with a fixed subject/body about 2FA expiry.
- **`notification_script`** — `subprocess.call([notification_script])` with no arguments, no stdin, no context. The script learns nothing about what happened; it's a bare "ping."

Neither path carries structured data. There is no event type, no payload, nothing a script could branch on. This is not a general notification system with one consumer — it is 2FA-expiry alerting that happens to be factored into functions with generic-sounding names.

This blocks the upcoming **sync-deletions-to-iCloud** feature (see issue #5 and `2026-07-15-persistent-asset-manifest-design.md` for the manifest infrastructure it depends on), which needs to alert on multiple distinct events (a deletion-sync run completed and deleted N assets; a run's deletion count exceeded a safety threshold and was withheld pending review) with real structured data (counts, filenames, recordNames). Bolting that onto the existing single-purpose hook would mean either hardcoding a second unrelated event into the same narrow function, or duplicating the subprocess-call plumbing a second time.

This sub-project tears down the existing notification path and replaces it with a small, general, single-transport mechanism. 2FA-expiry becomes the first consumer of the new mechanism rather than the only one; deletion-sync becomes the second when it lands.

## Scope

In scope:
- A new `notifications.py` module: one `notify()` function, one delivery mechanism (a user-configured script, invoked with a structured JSON payload on stdin).
- A closed, extensible event-type schema, starting with `session_expired` (migrated from today's 2FA path) and the two deletion-sync events (`deletion_sync_summary`, `deletion_sync_threshold_tripped` — see the deletion-sync design, to be written once this lands).
- Removal of `email_notifications.py`, `--smtp-*` flags, `--notification-email`, `--notification-email-from`.
- Migration of the existing 2FA-expiry call site to the new mechanism.

Out of scope:
- Any built-in transport other than the script hook (no built-in email, Slack, Telegram, etc. — see Architecture below).
- Event types beyond the two known consumers (no speculative "run completed," "download failed," etc. — YAGNI; add event types when a real consumer needs them).
- The deletion-sync feature itself (separate design, to follow this one).

## Architecture

**One transport: a user-configured script, invoked with a JSON payload on stdin.**

Three transport shapes were considered — JSON on stdin, environment variables, and CLI arguments — chosen against how a real deletion-sync payload looks (an event type, a human-readable summary, and potentially a list of up to hundreds of filenames). Env vars and CLI args both degrade badly for list-shaped or arbitrarily long data (shell arg-length limits, escaping hazards); JSON on stdin has neither problem and is the standard shape for webhook-style event delivery. Chosen.

**No built-in email (or any other) integration.** The existing SMTP path is deleted outright, not migrated. Rationale: a transport-agnostic script hook lets every user integrate whatever they actually use (email via `mail`/`msmtp`, Telegram, Slack, a webhook, a log aggregator) with a few lines of their own script, without this project taking on the maintenance burden of N built-in integrations it would need to keep working against N external APIs. This is a deliberate, real breaking change for any existing user of `--smtp-*` — acceptable here since the old path only ever covered one narrow event and this is a maintained fork, not an upstream-compatible release.

```python
def notify(logger: logging.Logger, script_path: str | None, event: NotificationEvent, timeout_s: float = 10.0) -> None: ...
```

`notify()` is called at each event site (today: only the auth-expiry site; later: the two deletion-sync sites). If `script_path` is `None` (not configured), it's a no-op. Otherwise it serializes `event` to JSON and runs the script with that JSON as stdin, via `subprocess.run(..., input=..., timeout=timeout_s)`.

## Event schema

```python
@dataclass(frozen=True)
class NotificationEvent:
    event_type: str          # closed set: "session_expired" | "deletion_sync_summary" | "deletion_sync_threshold_tripped"
    timestamp: str            # UTC ISO 8601
    username: str
    message: str              # human-readable one-liner; a script that does nothing but forward this verbatim still produces a sane alert
    data: dict[str, Any]      # event-specific structured fields
```

`message` exists so the simplest possible integration script (`cat stdin | jq -r .message | <send-it-somewhere>`) already works. `data` is where event-specific detail goes — e.g. for `deletion_sync_summary`: `{"count": int, "record_names": list[str]}` (list included only below whatever display threshold the deletion-sync feature settles on — its own design decision, not this one's). Adding a new event type later means adding a new `event_type` string and its `data` shape; `notify()` and the transport code never change.

## Config surface

Keeps the existing `notification_script: pathlib.Path | None` field on `UserConfig` (per-account, since a multi-account setup may reasonably want different scripts or none at all) as the sole configuration surface for this mechanism. `--smtp-username`, `--smtp-password`, `--smtp-host`, `--smtp-port`, `--smtp-no-tls`, `--notification-email`, `--notification-email-from` are removed from `cli.py` and `config.py`.

## Error handling

Matches the manifest module's established philosophy (`manifest.py`): best-effort, never raised into the caller. A missing script, non-zero exit code, or a run exceeding `timeout_s` are all logged as warnings and swallowed — a notification failing must never block or fail a download/deletion-sync run. This mirrors exactly how manifest write failures are handled, for the same reason: the feature this infrastructure serves must keep working even if the infrastructure itself is broken.

## Testing

- Unit tests for `notify()`: correct JSON shape on stdin per event type, script invoked with the right argv/stdin, and each failure mode (script missing, non-zero exit, timeout) logs a warning and does not raise.
- Migration test: the existing 2FA-expiry test (`test_email_notifications.py`, to be renamed/moved) asserts a `session_expired` event is constructed and passed to `notify()` at the same call site, replacing the old direct `send_2sa_notification`/`subprocess.call` assertions.
- `email_notifications.py` and its dedicated tests are deleted, not migrated.

## Open questions for later sub-projects (not blocking this design)

- Exact `data` shape for `deletion_sync_summary` / `deletion_sync_threshold_tripped` (e.g. the filename-list display threshold) is decided in the deletion-sync design, not here — this design only reserves the two event-type names.
- Whether any built-in integrations (e.g. a Telegram script the maintainer uses personally) get committed to the repo is a repo-governance question, not a design question — noted per-maintainer intent that any such integration would ship without a support/update commitment, documented in the README if it comes up.
