# Proactive Session-Expiry Warning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Warn a human before an iCloud session's auth cookies actually expire (not just after), and let them act on that warning from Telegram by forcing a fresh login attempt that reuses the existing 2FA sidecar flow.

**Architecture:** A new `session_expiry.py` module reads the soonest-expiring of two Apple auth cookies off the live `PyiCloudService`, tracks "last warned" in a small JSON file colocated with the cookie jar, and fires a `session_expiring_soon` notification event through the existing `notifications.py` mechanism. A new `POST /force-reauth` endpoint lets a human clear a stored session token on demand, forcing the next login to actually challenge 2FA — which the already-built Telegram sidecar flow then drives to completion unchanged.

**Tech Stack:** Python, Flask (icloudpd's WebUI), aiogram + aiohttp (Telegram sidecar), pytest, VCR cassettes, freezegun.

**Specs:** `docs/superpowers/specs/2026-07-16-proactive-session-expiry-warning-design.md`, `docs/superpowers/specs/2026-07-15-telegram-2fa-sidecar-design.md`, `docs/superpowers/specs/2026-07-15-notification-system-design.md`.

---

## File Structure

New files:
- `src/icloudpd/session_expiry.py` — expiry detection, state-file cadence tracking, notify orchestration.
- `tests/test_pyicloud_session_paths.py` — unit tests for the extracted path-sanitizing helpers.
- `tests/test_session_expiry.py` — unit tests for `session_expiry.py`.
- `tests/test_session_expiry_notification.py` — end-to-end test through the real CLI/auth path.

Modified files:
- `src/pyicloud_ipd/base.py` — extract `sanitize_apple_id`/`session_file_path` as module-level functions (needed by both `session_expiry.py` and the new endpoint, without instantiating a `PyiCloudService`).
- `src/icloudpd/config.py` — two new `UserConfig` fields.
- `src/icloudpd/cli.py` — two new CLI flags, wired into `map_to_config`.
- `src/icloudpd/base.py` — call `session_expiry.check_and_notify(...)` after a successful `authenticator()` call in `core_single_run`.
- `src/icloudpd/server/__init__.py` — new `POST /force-reauth` endpoint.
- `tests/test_server.py` — tests for the new endpoint.
- `integrations/telegram-bot/bot/notify_listener.py` — dispatch `session_expiring_soon` to a second handler.
- `integrations/telegram-bot/bot/messages.py` — new text/keyboard for the warning + force-reauth button.
- `integrations/telegram-bot/bot/icloudpd_client.py` — `force_reauth()` method.
- `integrations/telegram-bot/bot/handlers.py` — `handle_force_reauth` + router wiring.
- `integrations/telegram-bot/bot/main.py` — wire the new handler into `build_notify_app`.
- `integrations/telegram-bot/tests/*` — corresponding tests for the four files above.
- `integrations/telegram-bot/E2E_CHECKLIST.md` — new manual steps for the "Refresh session now" flow.

---

### Task 1: Extract cookie/session path helpers in pyicloud_ipd

**Files:**
- Modify: `src/pyicloud_ipd/base.py:59` (insert new functions), `src/pyicloud_ipd/base.py:615-629` (refactor properties)
- Test: `tests/test_pyicloud_session_paths.py`

- [ ] **Step 1: Write the failing tests**

```python
import os

from pyicloud_ipd.base import sanitize_apple_id, session_file_path


def test_sanitize_apple_id_strips_non_word_characters() -> None:
    assert sanitize_apple_id("jdoe@gmail.com") == "jdoegmailcom"


def test_session_file_path_matches_naming_scheme() -> None:
    assert session_file_path("/tmp/cookies", "jdoe@gmail.com") == "/tmp/cookies/jdoegmailcom.session"


def test_session_file_path_expands_user_and_normalizes() -> None:
    result = session_file_path("~/cookies/../cookies", "jdoe@gmail.com")
    assert result == os.path.join(os.path.expanduser("~/cookies"), "jdoegmailcom.session")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pyicloud_session_paths.py -v`
Expected: FAIL with `ImportError: cannot import name 'sanitize_apple_id'`

- [ ] **Step 3: Add the module-level functions**

In `src/pyicloud_ipd/base.py`, immediately after `origin_referer_headers` (currently ending at line 59, right before `class TrustedPhoneContextProvider`), add:

```python
def sanitize_apple_id(apple_id: str) -> str:
    """Strip an Apple ID down to word characters only, for safe use in filenames."""
    return "".join(c for c in apple_id if match(r"\w", c))


def session_file_path(cookie_directory: str, apple_id: str) -> str:
    """Path to an account's session-token file, without needing a live PyiCloudService.

    Mirrors PyiCloudService.session_path's naming scheme so callers that
    don't hold a live session (e.g. a force-reauth trigger) can still
    locate the file to clear it.
    """
    normalized_dir = path.expanduser(path.normpath(cookie_directory))
    return path.join(normalized_dir, sanitize_apple_id(apple_id) + ".session")
```

- [ ] **Step 4: Refactor the existing properties to use the new function**

In `src/pyicloud_ipd/base.py`, replace:

```python
    @property
    def cookiejar_path(self) -> str:
        """Get path for cookiejar file."""
        return path.join(
            self._cookie_directory,
            "".join([c for c in self.apple_id if match(r"\w", c)]),
        )

    @property
    def session_path(self) -> str:
        """Get path for session data file."""
        return path.join(
            self._cookie_directory,
            "".join([c for c in self.apple_id if match(r"\w", c)]) + ".session",
        )
```

with:

```python
    @property
    def cookiejar_path(self) -> str:
        """Get path for cookiejar file."""
        return path.join(self._cookie_directory, sanitize_apple_id(self.apple_id))

    @property
    def session_path(self) -> str:
        """Get path for session data file."""
        return path.join(self._cookie_directory, sanitize_apple_id(self.apple_id) + ".session")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_pyicloud_session_paths.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the full pyicloud auth test suite to confirm no regression**

Run: `pytest tests/test_authentication.py tests/test_two_step_auth.py tests/test_session_expired_notification.py -v`
Expected: PASS (properties behave identically, just DRY'd up)

- [ ] **Step 7: Commit**

```bash
git add src/pyicloud_ipd/base.py tests/test_pyicloud_session_paths.py
git commit -m "refactor: extract sanitize_apple_id/session_file_path as pure functions"
```

---

### Task 2: Add config fields and CLI flags

**Files:**
- Modify: `src/icloudpd/config.py:35` (add fields), `src/icloudpd/cli.py:145-152` (add flags), `src/icloudpd/cli.py:417` (wire into `map_to_config`)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py` (near the other option-specific tests, e.g. after `test_cli_parser`):

```python
def test_session_expiry_options_parse_custom_values() -> None:
    _global_config, user_configs = parse(
        [
            "--directory",
            "abc",
            "--username",
            "u1",
            "--session-expiry-warning-days",
            "3",
            "--session-expiry-notification-interval-hours",
            "12",
        ]
    )
    assert user_configs[0].session_expiry_warning_days == 3
    assert user_configs[0].session_expiry_notification_interval_hours == 12


def test_session_expiry_options_default_values() -> None:
    _global_config, user_configs = parse(["--directory", "abc", "--username", "u1"])
    assert user_configs[0].session_expiry_warning_days == 7
    assert user_configs[0].session_expiry_notification_interval_hours == 24
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -k session_expiry -v`
Expected: FAIL with `argparse` error `unrecognized arguments: --session-expiry-warning-days`

- [ ] **Step 3: Add the two fields to `_DefaultConfig`**

In `src/icloudpd/config.py`, add after `notification_script: pathlib.Path | None` (line 35):

```python
    notification_script: pathlib.Path | None
    session_expiry_warning_days: int = 7
    session_expiry_notification_interval_hours: int = 24
```

Defaults are set directly on the dataclass (matching the CLI defaults below) so existing `UserConfig(...)` construction sites elsewhere in the test suite that don't mention these fields keep working unchanged.

- [ ] **Step 4: Add the CLI flags**

In `src/icloudpd/cli.py`, add after the `--notification-script` block (currently ending at line 152):

```python
    cloned.add_argument(
        "--session-expiry-warning-days",
        type=int,
        help="Start warning this many days before the iCloud session's auth cookies expire. "
        "Set to 0 to disable the proactive warning (the reactive session_expired event, "
        "fired when a run actually hits the 2FA/2SA challenge, is unaffected). "
        "Default: %(default)s",
        default=7,
    )
    cloned.add_argument(
        "--session-expiry-notification-interval-hours",
        type=int,
        help="Minimum hours between repeated session-expiry warnings while inside the "
        "warning window. Default: %(default)s",
        default=24,
    )
```

- [ ] **Step 5: Wire into `map_to_config`**

In `src/icloudpd/cli.py`, in `map_to_config` (currently line 393-430), add after `notification_script=user_ns.notification_script,` (line 417):

```python
        notification_script=user_ns.notification_script,
        session_expiry_warning_days=user_ns.session_expiry_warning_days,
        session_expiry_notification_interval_hours=user_ns.session_expiry_notification_interval_hours,
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_cli.py -k session_expiry -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Run the full CLI test suite to confirm no regression**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (`test_cli_parser`'s literal `UserConfig(...)` expectations don't mention the two new fields, so they compare equal against the parsed defaults of 7/24)

- [ ] **Step 8: Commit**

```bash
git add src/icloudpd/config.py src/icloudpd/cli.py tests/test_cli.py
git commit -m "feat: add --session-expiry-warning-days and --session-expiry-notification-interval-hours"
```

---

### Task 3: `session_expiry.py` — earliest relevant cookie expiry

**Files:**
- Create: `src/icloudpd/session_expiry.py`
- Test: `tests/test_session_expiry.py`

- [ ] **Step 1: Write the failing test**

```python
import datetime
from types import SimpleNamespace

from icloudpd.session_expiry import earliest_relevant_expiry


def _cookie(name: str, expires: float | None) -> SimpleNamespace:
    return SimpleNamespace(name=name, expires=expires)


def test_earliest_relevant_expiry_picks_soonest_of_two_cookies() -> None:
    later = datetime.datetime(2024, 2, 11, tzinfo=datetime.timezone.utc).timestamp()
    sooner = datetime.datetime(2024, 1, 12, tzinfo=datetime.timezone.utc).timestamp()
    cookies = [
        _cookie("X_APPLE_WEB_KB-ONHCNAXFAIPPFDMR5UZVNO6NIMY", later),
        _cookie("X-APPLE-WEBAUTH-USER", sooner),
        _cookie("X-APPLE-WEBAUTH-LOGIN", None),
    ]

    result = earliest_relevant_expiry(cookies)

    assert result == datetime.datetime.fromtimestamp(sooner, tz=datetime.timezone.utc)


def test_earliest_relevant_expiry_ignores_unrelated_cookies() -> None:
    cookies = [_cookie("dslang", 9999999999.0), _cookie("site", 9999999999.0)]

    assert earliest_relevant_expiry(cookies) is None


def test_earliest_relevant_expiry_returns_none_when_no_expires_present() -> None:
    cookies = [_cookie("X-APPLE-WEBAUTH-USER", None)]

    assert earliest_relevant_expiry(cookies) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_expiry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'icloudpd.session_expiry'`

- [ ] **Step 3: Create `session_expiry.py` with the expiry-computation piece**

```python
"""Proactive warning before an iCloud session's auth cookies actually expire.

Apple's login cookies (X-APPLE-WEBAUTH-USER, X_APPLE_WEB_KB-<hash>) carry
their own Expires timestamp. This module reads the soonest of the two off
the live session's cookie jar and, once remaining time drops under a
configurable threshold, fires a session_expiring_soon notification event
at most once per a configurable interval.

All operations here are best-effort: failures are logged and swallowed
rather than raised, matching notifications.py and manifest.py - this
check running (or failing to run) must never block or fail a download.
"""

from __future__ import annotations

import datetime
from typing import Iterable, Protocol

_EVENT_TYPE = "session_expiring_soon"
_EXACT_COOKIE_NAMES = ("X-APPLE-WEBAUTH-USER",)
_COOKIE_PREFIX = "X_APPLE_WEB_KB-"


class _CookieLike(Protocol):
    name: str
    expires: float | None


def _is_relevant_cookie(name: str) -> bool:
    return name in _EXACT_COOKIE_NAMES or name.startswith(_COOKIE_PREFIX)


def earliest_relevant_expiry(cookies: Iterable[_CookieLike]) -> datetime.datetime | None:
    """Earliest Expires timestamp across the cookies that govern session validity.

    Returns None if neither relevant cookie is present, or neither carries
    expiry data - callers should skip the check silently in that case.
    """
    expiries = [
        cookie.expires
        for cookie in cookies
        if _is_relevant_cookie(cookie.name) and cookie.expires is not None
    ]
    if not expiries:
        return None
    return datetime.datetime.fromtimestamp(min(expiries), tz=datetime.timezone.utc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_expiry.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd/session_expiry.py tests/test_session_expiry.py
git commit -m "feat: add earliest_relevant_expiry cookie-expiry detection"
```

---

### Task 4: `session_expiry.py` — state file (cadence tracking)

**Files:**
- Modify: `src/icloudpd/session_expiry.py`
- Test: `tests/test_session_expiry.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_session_expiry.py`:

```python
import json
import os

import pytest

from icloudpd.logger import setup_logger
from icloudpd.session_expiry import _load_last_warned, _save_last_warned, state_file_path


def test_state_file_path_colocated_with_cookie_jar(tmp_path: object) -> None:
    result = state_file_path(str(tmp_path), "jdoe@gmail.com")

    assert result == os.path.join(str(tmp_path), "jdoegmailcom.notify_state.json")


def test_load_last_warned_returns_none_when_file_missing(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "state.json")

    assert _load_last_warned(setup_logger(), path) is None


def test_save_then_load_round_trips(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "state.json")
    when = datetime.datetime(2026, 7, 15, 9, 0, tzinfo=datetime.timezone.utc)

    _save_last_warned(setup_logger(), path, when)

    assert _load_last_warned(setup_logger(), path) == when


def test_load_last_warned_treats_corrupt_json_as_never_warned(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "state.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not valid json")

    assert _load_last_warned(setup_logger(), path) is None


def test_save_last_warned_preserves_other_event_types(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "state.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"some_other_event": {"last_warned_utc": "2020-01-01T00:00:00+00:00"}}, f)

    _save_last_warned(
        setup_logger(), path, datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc)
    )

    with open(path, encoding="utf-8") as f:
        state = json.load(f)
    assert state["some_other_event"]["last_warned_utc"] == "2020-01-01T00:00:00+00:00"
    assert state["session_expiring_soon"]["last_warned_utc"] == "2026-07-15T00:00:00+00:00"
```

Add `import datetime` to the top of `tests/test_session_expiry.py` alongside the existing imports.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_expiry.py -v`
Expected: FAIL with `ImportError: cannot import name '_load_last_warned'`

- [ ] **Step 3: Add state-file functions to `session_expiry.py`**

Add near the top of `src/icloudpd/session_expiry.py`, after the existing imports:

```python
import json
import logging
import os

from pyicloud_ipd.base import sanitize_apple_id
```

Add after `earliest_relevant_expiry`:

```python
def state_file_path(cookie_directory: str, username: str) -> str:
    normalized_dir = os.path.expanduser(os.path.normpath(cookie_directory))
    return os.path.join(normalized_dir, sanitize_apple_id(username) + ".notify_state.json")


def _load_last_warned(logger: logging.Logger, path: str) -> datetime.datetime | None:
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as ex:
        logger.warning("Could not read notification state %s: %s", path, ex)
        return None

    raw = state.get(_EVENT_TYPE, {}).get("last_warned_utc")
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(raw)
    except ValueError as ex:
        logger.warning("Could not parse notification state %s: %s", path, ex)
        return None


def _save_last_warned(logger: logging.Logger, path: str, when: datetime.datetime) -> None:
    state: dict[str, dict[str, str]] = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, json.JSONDecodeError):
            state = {}

    state[_EVENT_TYPE] = {"last_warned_utc": when.isoformat()}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError as ex:
        logger.warning("Could not write notification state %s: %s", path, ex)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_expiry.py -v`
Expected: PASS (8 tests total)

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd/session_expiry.py tests/test_session_expiry.py
git commit -m "feat: add session_expiry state-file cadence tracking"
```

---

### Task 5: `session_expiry.py` — `check_and_notify` orchestration

**Files:**
- Modify: `src/icloudpd/session_expiry.py`
- Test: `tests/test_session_expiry.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_session_expiry.py`:

```python
from unittest.mock import patch

from freezegun import freeze_time

from icloudpd.session_expiry import check_and_notify


def _cookies_expiring(expires_str: str) -> list[SimpleNamespace]:
    expires = datetime.datetime.fromisoformat(expires_str).timestamp()
    return [_cookie("X-APPLE-WEBAUTH-USER", expires)]


class _FakeSession:
    def __init__(self, cookies: list[SimpleNamespace]) -> None:
        self.cookies = cookies


class _FakeIcloud:
    def __init__(self, cookies: list[SimpleNamespace]) -> None:
        self.session = _FakeSession(cookies)


@freeze_time("2026-07-10T00:00:00+00:00")
def test_check_and_notify_fires_when_inside_warning_window(tmp_path: object) -> None:
    icloud = _FakeIcloud(_cookies_expiring("2026-07-13T00:00:00+00:00"))  # 3 days out

    with patch("icloudpd.notifications.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""
        check_and_notify(
            setup_logger(),
            icloud,
            "jdoe@gmail.com",
            str(tmp_path),
            "./notify.sh",
            warning_days=7,
            notification_interval_hours=24,
        )

    run_mock.assert_called_once()
    args, kwargs = run_mock.call_args
    payload = json.loads(kwargs["input"])
    assert payload["event_type"] == "session_expiring_soon"
    assert payload["username"] == "jdoe@gmail.com"
    assert payload["data"]["days_remaining"] == pytest.approx(3.0, abs=0.1)


@freeze_time("2026-01-01T00:00:00+00:00")
def test_check_and_notify_skips_when_outside_warning_window(tmp_path: object) -> None:
    icloud = _FakeIcloud(_cookies_expiring("2026-07-13T00:00:00+00:00"))  # ~193 days out

    with patch("icloudpd.notifications.subprocess.run") as run_mock:
        check_and_notify(
            setup_logger(),
            icloud,
            "jdoe@gmail.com",
            str(tmp_path),
            "./notify.sh",
            warning_days=7,
            notification_interval_hours=24,
        )

    run_mock.assert_not_called()


def test_check_and_notify_skips_when_no_notification_script(tmp_path: object) -> None:
    icloud = _FakeIcloud(_cookies_expiring("2026-07-13T00:00:00+00:00"))

    with patch("icloudpd.notifications.subprocess.run") as run_mock:
        check_and_notify(
            setup_logger(),
            icloud,
            "jdoe@gmail.com",
            str(tmp_path),
            None,
            warning_days=7,
            notification_interval_hours=24,
        )

    run_mock.assert_not_called()


def test_check_and_notify_skips_when_warning_days_is_zero(tmp_path: object) -> None:
    icloud = _FakeIcloud(_cookies_expiring("2026-07-13T00:00:00+00:00"))

    with patch("icloudpd.notifications.subprocess.run") as run_mock:
        check_and_notify(
            setup_logger(),
            icloud,
            "jdoe@gmail.com",
            str(tmp_path),
            "./notify.sh",
            warning_days=0,
            notification_interval_hours=24,
        )

    run_mock.assert_not_called()


def test_check_and_notify_skips_when_no_expiring_cookie(tmp_path: object) -> None:
    icloud = _FakeIcloud([])

    with patch("icloudpd.notifications.subprocess.run") as run_mock:
        check_and_notify(
            setup_logger(),
            icloud,
            "jdoe@gmail.com",
            str(tmp_path),
            "./notify.sh",
            warning_days=7,
            notification_interval_hours=24,
        )

    run_mock.assert_not_called()


@freeze_time("2026-07-10T00:00:00+00:00")
def test_check_and_notify_respects_cadence(tmp_path: object) -> None:
    icloud = _FakeIcloud(_cookies_expiring("2026-07-13T00:00:00+00:00"))

    with patch("icloudpd.notifications.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""
        check_and_notify(
            setup_logger(), icloud, "jdoe@gmail.com", str(tmp_path), "./notify.sh",
            warning_days=7, notification_interval_hours=24,
        )
        # A second check an hour later, well inside the 24h cadence, must not re-fire.
        with freeze_time("2026-07-10T01:00:00+00:00"):
            check_and_notify(
                setup_logger(), icloud, "jdoe@gmail.com", str(tmp_path), "./notify.sh",
                warning_days=7, notification_interval_hours=24,
            )

    run_mock.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_expiry.py -v`
Expected: FAIL with `ImportError: cannot import name 'check_and_notify'`

- [ ] **Step 3: Add `check_and_notify` to `session_expiry.py`**

Add `from icloudpd import notifications` and `from pyicloud_ipd.base import PyiCloudService` to the imports at the top of `src/icloudpd/session_expiry.py`, and add at the end of the file:

```python
def check_and_notify(
    logger: logging.Logger,
    icloud: PyiCloudService,
    username: str,
    cookie_directory: str,
    notification_script: str | None,
    warning_days: int,
    notification_interval_hours: int,
) -> None:
    """Warn once per notification_interval_hours if the session expires within warning_days.

    No-op if notification_script is unset, warning_days is 0 or negative, or
    neither relevant cookie carries expiry data. Never raises.
    """
    if notification_script is None or warning_days <= 0:
        return

    expires_at = earliest_relevant_expiry(icloud.session.cookies)
    if expires_at is None:
        logger.debug("No expiring session cookie found for %s, skipping expiry check", username)
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    days_remaining = (expires_at - now).total_seconds() / 86400
    if days_remaining > warning_days:
        return

    path = state_file_path(cookie_directory, username)
    last_warned = _load_last_warned(logger, path)
    if last_warned is not None:
        hours_since = (now - last_warned).total_seconds() / 3600
        if hours_since < notification_interval_hours:
            return

    event = notifications.build_event(
        event_type=_EVENT_TYPE,
        username=username,
        message=(
            f"{username}'s iCloud session expires in {max(days_remaining, 0):.1f} day(s). "
            "Re-authenticate before it lapses to avoid a stalled run."
        ),
        data={
            "days_remaining": round(days_remaining, 1),
            "expires_at_utc": expires_at.isoformat(),
        },
    )
    notifications.notify(logger, notification_script, event)
    _save_last_warned(logger, path, now)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_expiry.py -v`
Expected: PASS (14 tests total)

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd/session_expiry.py tests/test_session_expiry.py
git commit -m "feat: add check_and_notify session-expiry orchestration"
```

---

### Task 6: Wire `check_and_notify` into `core_single_run`

**Files:**
- Modify: `src/icloudpd/base.py:40` (import), `src/icloudpd/base.py:896-917` (call site)

- [ ] **Step 1: Add the import**

In `src/icloudpd/base.py`, change:

```python
from icloudpd import download, exif_datetime, manifest, notifications
```

to:

```python
from icloudpd import download, exif_datetime, manifest, notifications, session_expiry
```

- [ ] **Step 2: Add the call site**

In `src/icloudpd/base.py`, in `core_single_run`, after:

```python
            # turn off response capture
            icloud.response_observer = None
```

(currently line 917), add:

```python
            session_expiry.check_and_notify(
                logger,
                icloud,
                user_config.username,
                user_config.cookie_directory,
                str(user_config.notification_script) if user_config.notification_script else None,
                user_config.session_expiry_warning_days,
                user_config.session_expiry_notification_interval_hours,
            )
```

- [ ] **Step 3: Run the existing base/auth test suite to confirm no regression**

Run: `pytest tests/test_authentication.py tests/test_two_step_auth.py tests/test_session_expired_notification.py tests/test_cli.py -v`
Expected: PASS (no existing test configures a `--notification-script` with a cookie set that carries a near-expiry cookie, so `check_and_notify` is a no-op in all of them - either `notification_script` is unset or the cookie's expiry is decades away relative to the frozen/real clock)

- [ ] **Step 4: Commit**

```bash
git add src/icloudpd/base.py
git commit -m "feat: call session_expiry.check_and_notify after successful auth"
```

---

### Task 7: End-to-end test through the real CLI/auth path

**Files:**
- Create: `tests/test_session_expiry_notification.py`

- [ ] **Step 1: Write the test**

Model this closely on `tests/test_session_expired_notification.py`. `tests/vcr_cassettes/auth_non_2fa.yml` performs a full fresh SRP login (no 2FA challenge) and sets `X-APPLE-WEBAUTH-USER` with `Expires=Fri, 12-Jan-2024 05:06:31 GMT` and `X_APPLE_WEB_KB-...` with a later expiry - freezing time a few days before the earlier of the two puts the check inside the default 7-day warning window.

```python
import inspect
import json
import os
from unittest import TestCase
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from tests.helpers import path_from_project_root, recreate_path, run_cassette


class SessionExpiringSoonNotificationTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self) -> None:
        self.root_path = path_from_project_root(__file__)
        self.fixtures_path = os.path.join(self.root_path, "fixtures")
        self.vcr_path = os.path.join(self.root_path, "vcr_cassettes")

    @freeze_time("2024-01-08")
    def test_session_expiring_soon_fires_inside_warning_window(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])
        cookie_dir = os.path.join(base_dir, "cookie")

        recreate_path(base_dir)
        recreate_path(cookie_dir)

        with patch("icloudpd.notifications.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            run_mock.return_value.stderr = ""
            result = run_cassette(
                os.path.join(self.vcr_path, "auth_non_2fa.yml"),
                [
                    "--username",
                    "jdoe@gmail.com",
                    "--password",
                    "password1",
                    "--notification-script",
                    "./test_script.sh",
                    "--cookie-directory",
                    cookie_dir,
                    "--auth-only",
                ],
            )
            self.assertEqual(result.exit_code, 0, "exit code")

            run_mock.assert_called_once()
            args, kwargs = run_mock.call_args
            self.assertEqual(args[0], ["test_script.sh"])
            payload = json.loads(kwargs["input"])
            self.assertEqual(payload["event_type"], "session_expiring_soon")
            self.assertEqual(payload["username"], "jdoe@gmail.com")
            self.assertIn("expires in", payload["message"])

    @freeze_time("2018-01-01")
    def test_session_expiring_soon_does_not_fire_far_from_expiry(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])
        cookie_dir = os.path.join(base_dir, "cookie")

        recreate_path(base_dir)
        recreate_path(cookie_dir)

        with patch("icloudpd.notifications.subprocess.run") as run_mock:
            result = run_cassette(
                os.path.join(self.vcr_path, "auth_non_2fa.yml"),
                [
                    "--username",
                    "jdoe@gmail.com",
                    "--password",
                    "password1",
                    "--notification-script",
                    "./test_script.sh",
                    "--cookie-directory",
                    cookie_dir,
                    "--auth-only",
                ],
            )
            self.assertEqual(result.exit_code, 0, "exit code")
            run_mock.assert_not_called()
```

- [ ] **Step 2: Run test to verify both pass**

Run: `pytest tests/test_session_expiry_notification.py -v`
Expected: PASS (2 tests). If the first test fails with `run_mock` not called, double check the frozen date is before the `X-APPLE-WEBAUTH-USER` cookie's `Expires` (2024-01-12) and within 7 days of it.

- [ ] **Step 3: Commit**

```bash
git add tests/test_session_expiry_notification.py
git commit -m "test: add end-to-end coverage for session_expiring_soon"
```

---

### Task 8: `POST /force-reauth` endpoint

**Files:**
- Modify: `src/icloudpd/server/__init__.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_server.py`:

```python
import os

from icloudpd.config import UserConfig
from pyicloud_ipd.file_match import FileMatchPolicy
from pyicloud_ipd.live_photo_mov_filename_policy import LivePhotoMovFilenamePolicy
from pyicloud_ipd.raw_policy import RawTreatmentPolicy
from pyicloud_ipd.version_size import AssetVersionSize, LivePhotoVersionSize


def _user_config(username: str, cookie_directory: str) -> UserConfig:
    return UserConfig(
        username=username,
        password=None,
        directory="/tmp/does-not-matter",
        auth_only=True,
        cookie_directory=cookie_directory,
        sizes=[AssetVersionSize.ORIGINAL],
        live_photo_size=LivePhotoVersionSize.ORIGINAL,
        recent=None,
        until_found=None,
        albums=[],
        list_albums=False,
        library="PrimarySync",
        list_libraries=False,
        skip_videos=False,
        skip_live_photos=False,
        xmp_sidecar=False,
        force_size=False,
        auto_delete=False,
        folder_structure="{:%Y/%m/%d}",
        set_exif_datetime=False,
        notification_script=None,
        delete_after_download=False,
        keep_icloud_recent_days=None,
        dry_run=False,
        keep_unicode_in_filenames=False,
        live_photo_mov_filename_policy=LivePhotoMovFilenamePolicy.SUFFIX,
        align_raw=RawTreatmentPolicy.AS_IS,
        file_match_policy=FileMatchPolicy.NAME_SIZE_DEDUP_WITH_SUFFIX,
        skip_created_before=None,
        skip_created_after=None,
        skip_photos=False,
    )


def test_force_reauth_deletes_session_file_and_wakes_watch_loop(tmp_path: object) -> None:
    cookie_dir = str(tmp_path)
    session_path = os.path.join(cookie_dir, "jdoegmailcom.session")
    with open(session_path, "w", encoding="utf-8") as f:
        f.write("{}")

    status_exchange = StatusExchange()
    status_exchange.set_user_configs([_user_config("jdoe@gmail.com", cookie_dir)])
    client = make_client(status_exchange)

    response = client.post("/force-reauth", data={"username": "jdoe@gmail.com"})

    assert response.status_code == 204
    assert not os.path.exists(session_path)
    assert status_exchange.get_progress().resume is True


def test_force_reauth_is_a_no_op_when_session_file_absent(tmp_path: object) -> None:
    cookie_dir = str(tmp_path)
    status_exchange = StatusExchange()
    status_exchange.set_user_configs([_user_config("jdoe@gmail.com", cookie_dir)])
    client = make_client(status_exchange)

    response = client.post("/force-reauth", data={"username": "jdoe@gmail.com"})

    assert response.status_code == 204
    assert status_exchange.get_progress().resume is True


def test_force_reauth_rejects_unknown_username() -> None:
    status_exchange = StatusExchange()
    status_exchange.set_user_configs([_user_config("jdoe@gmail.com", "/tmp/wherever")])
    client = make_client(status_exchange)

    response = client.post("/force-reauth", data={"username": "unknown@gmail.com"})

    assert response.status_code == 404
    assert status_exchange.get_progress().resume is False


def test_force_reauth_rejects_missing_username() -> None:
    status_exchange = StatusExchange()
    client = make_client(status_exchange)

    response = client.post("/force-reauth", data={})

    assert response.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_server.py -k force_reauth -v`
Expected: FAIL with 404 (route not found) on all four

- [ ] **Step 3: Add the endpoint**

In `src/icloudpd/server/__init__.py`, change the import line:

```python
from icloudpd.status import Status, StatusExchange
```

to:

```python
from icloudpd.status import Status, StatusExchange
from pyicloud_ipd.base import session_file_path
```

Add after the `/trigger-push` route (currently lines 93-97):

```python
    @app.route("/force-reauth", methods=["POST"])
    def force_reauth() -> Response:
        username = request.form.get("username")
        if not username:
            return make_response("Missing username", 400)

        matching = next(
            (uc for uc in _status_exchange.get_user_configs() if uc.username == username),
            None,
        )
        if matching is None:
            return make_response("Unknown username", 404)

        path = session_file_path(matching.cookie_directory, matching.username)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as ex:
            logger.warning("Could not remove session file %s: %s", path, ex)

        _status_exchange.get_progress().resume = True
        return make_response("", 204)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_server.py -v`
Expected: PASS (all tests, including the 4 new ones)

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd/server/__init__.py tests/test_server.py
git commit -m "feat: add POST /force-reauth endpoint"
```

---

### Task 9: Telegram bot — dispatch `session_expiring_soon` in `notify_listener.py`

**Files:**
- Modify: `integrations/telegram-bot/bot/notify_listener.py`
- Test: `integrations/telegram-bot/tests/test_notify_listener.py`

- [ ] **Step 1: Write the failing test**

Add to `integrations/telegram-bot/tests/test_notify_listener.py`:

```python
@pytest.mark.asyncio
async def test_session_expiring_soon_event_invokes_its_own_handler() -> None:
    expired: list[dict[str, Any]] = []
    expiring: list[dict[str, Any]] = []

    async def on_session_expired(event: dict[str, Any]) -> None:
        expired.append(event)

    async def on_session_expiring_soon(event: dict[str, Any]) -> None:
        expiring.append(event)

    app = build_notify_app(on_session_expired, on_session_expiring_soon)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/notify",
            json={
                "event_type": "session_expiring_soon",
                "timestamp": "2026-07-15T00:00:00+00:00",
                "username": "jdoe@icloud.com",
                "message": "session expires in 3.0 day(s)",
                "data": {"days_remaining": 3.0},
            },
        )

        assert response.status == 204
    assert expired == []
    assert len(expiring) == 1
    assert expiring[0]["event_type"] == "session_expiring_soon"
```

Update the two existing tests in this file to pass a second no-op handler, since `build_notify_app`'s signature is changing:

```python
async def _noop(event: dict[str, Any]) -> None:
    pass
```

and change both `build_notify_app(on_session_expired)` calls to `build_notify_app(on_session_expired, _noop)`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd integrations/telegram-bot && python -m pytest tests/test_notify_listener.py -v`
Expected: FAIL with `TypeError: build_notify_app() missing 1 required positional argument`

- [ ] **Step 3: Update `build_notify_app`**

Replace the contents of `integrations/telegram-bot/bot/notify_listener.py`:

```python
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiohttp import web

logger = logging.getLogger(__name__)

NotifyHandler = Callable[[dict[str, Any]], Awaitable[None]]


def build_notify_app(
    on_session_expired: NotifyHandler,
    on_session_expiring_soon: NotifyHandler,
) -> web.Application:
    app = web.Application()

    async def handle_notify(request: web.Request) -> web.Response:
        event = await request.json()
        event_type = event.get("event_type")
        if event_type == "session_expired":
            await on_session_expired(event)
        elif event_type == "session_expiring_soon":
            await on_session_expiring_soon(event)
        else:
            logger.debug("Ignoring unhandled event_type=%s", event_type)
        return web.Response(status=204)

    app.router.add_post("/notify", handle_notify)
    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd integrations/telegram-bot && python -m pytest tests/test_notify_listener.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd integrations/telegram-bot
git add bot/notify_listener.py tests/test_notify_listener.py
git commit -m "feat: dispatch session_expiring_soon to its own handler"
```

---

### Task 10: Telegram bot — messages for the warning and force-reauth button

**Files:**
- Modify: `integrations/telegram-bot/bot/messages.py`
- Test: `integrations/telegram-bot/tests/test_messages.py`

- [ ] **Step 1: Write the failing tests**

Add to `integrations/telegram-bot/tests/test_messages.py`, updating the import block to include the new names:

```python
from bot.messages import (
    code_accepted_success_text,
    code_failed_keyboard,
    code_failed_text,
    code_requested_text,
    connection_lost_text,
    force_reauth_keyboard,
    force_reauth_not_found_text,
    force_reauth_requested_text,
    session_expired_text,
    session_expiring_soon_text,
    start_2fa_keyboard,
)


def test_session_expiring_soon_text_includes_username_and_message() -> None:
    text = session_expiring_soon_text("jdoe@icloud.com", "session expires in 3.0 day(s)")

    assert "jdoe@icloud.com" in text
    assert "3.0 day(s)" in text


def test_force_reauth_keyboard_embeds_username_in_callback_data() -> None:
    keyboard = force_reauth_keyboard("jdoe@icloud.com")

    assert keyboard.inline_keyboard[0][0].callback_data == "force_reauth:jdoe@icloud.com"


def test_force_reauth_requested_text_includes_username() -> None:
    assert "jdoe@icloud.com" in force_reauth_requested_text("jdoe@icloud.com")


def test_force_reauth_not_found_text_is_non_empty() -> None:
    assert force_reauth_not_found_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd integrations/telegram-bot && python -m pytest tests/test_messages.py -v`
Expected: FAIL with `ImportError: cannot import name 'session_expiring_soon_text'`

- [ ] **Step 3: Add the new functions**

Add to `integrations/telegram-bot/bot/messages.py`:

```python
def session_expiring_soon_text(username: str, message: str) -> str:
    return f"⏳ {username}: {message}"


def force_reauth_keyboard(username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Refresh session now", callback_data=f"force_reauth:{username}"
                )
            ]
        ]
    )


def force_reauth_requested_text(username: str) -> str:
    return f"Refreshing session for {username}. This may take a few seconds."


def force_reauth_not_found_text() -> str:
    return "That account isn't configured on this icloudpd instance."
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd integrations/telegram-bot && python -m pytest tests/test_messages.py -v`
Expected: PASS (all tests, including the 4 new ones)

- [ ] **Step 5: Commit**

```bash
cd integrations/telegram-bot
git add bot/messages.py tests/test_messages.py
git commit -m "feat: add session_expiring_soon and force-reauth messages"
```

---

### Task 11: Telegram bot — `IcloudpdClient.force_reauth`

**Files:**
- Modify: `integrations/telegram-bot/bot/icloudpd_client.py`
- Test: `integrations/telegram-bot/tests/test_icloudpd_client.py`

- [ ] **Step 1: Write the failing tests**

Add to `integrations/telegram-bot/tests/test_icloudpd_client.py`:

```python
@responses.activate
def test_force_reauth_success() -> None:
    responses.add(responses.POST, "http://icloudpd:8080/force-reauth", status=204)
    client = IcloudpdClient("http://icloudpd:8080")

    assert client.force_reauth("jdoe@icloud.com") is True


@responses.activate
def test_force_reauth_unknown_username() -> None:
    responses.add(responses.POST, "http://icloudpd:8080/force-reauth", status=404)
    client = IcloudpdClient("http://icloudpd:8080")

    assert client.force_reauth("unknown@icloud.com") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd integrations/telegram-bot && python -m pytest tests/test_icloudpd_client.py -v`
Expected: FAIL with `AttributeError: 'IcloudpdClient' object has no attribute 'force_reauth'`

- [ ] **Step 3: Add the method**

Add to `integrations/telegram-bot/bot/icloudpd_client.py`, after `trigger_push`:

```python
    def force_reauth(self, username: str) -> bool:
        response = requests.post(
            f"{self._base_url}/force-reauth", data={"username": username}, timeout=self._timeout
        )
        return response.status_code == 204
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd integrations/telegram-bot && python -m pytest tests/test_icloudpd_client.py -v`
Expected: PASS (all tests, including the 2 new ones)

- [ ] **Step 5: Commit**

```bash
cd integrations/telegram-bot
git add bot/icloudpd_client.py tests/test_icloudpd_client.py
git commit -m "feat: add IcloudpdClient.force_reauth"
```

---

### Task 12: Telegram bot — `handle_force_reauth` and router wiring

**Files:**
- Modify: `integrations/telegram-bot/bot/handlers.py`
- Test: `integrations/telegram-bot/tests/test_handlers.py`

- [ ] **Step 1: Write the failing tests**

Add to `integrations/telegram-bot/tests/test_handlers.py`:

```python
class ForceReauthClient(FakeClient):
    def __init__(self, force_reauth_result: bool = True, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.force_reauth_result = force_reauth_result
        self.force_reauth_calls: list[str] = []

    def force_reauth(self, username: str) -> bool:
        self.force_reauth_calls.append(username)
        return self.force_reauth_result


class ForceReauthRaisesClient(FakeClient):
    def force_reauth(self, username: str) -> bool:
        raise requests.exceptions.ConnectionError("Remote end closed connection")


@pytest.mark.asyncio
async def test_force_reauth_ignores_disallowed_chat() -> None:
    client = ForceReauthClient()
    callback = make_callback(chat_id=1, data="force_reauth:jdoe@icloud.com")

    await handle_force_reauth(callback, client, allowed_chat_ids=frozenset({2}))

    callback.answer.assert_awaited_once_with()
    callback.message.answer.assert_not_called()
    assert client.force_reauth_calls == []


@pytest.mark.asyncio
async def test_force_reauth_calls_client_with_embedded_username() -> None:
    client = ForceReauthClient(force_reauth_result=True)
    callback = make_callback(chat_id=1, data="force_reauth:jdoe@icloud.com")

    await handle_force_reauth(callback, client, allowed_chat_ids=frozenset({1}))

    assert client.force_reauth_calls == ["jdoe@icloud.com"]
    callback.answer.assert_awaited_once()
    callback.message.answer.assert_awaited_once()
    assert "jdoe@icloud.com" in callback.message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_force_reauth_alerts_when_username_unknown() -> None:
    client = ForceReauthClient(force_reauth_result=False)
    callback = make_callback(chat_id=1, data="force_reauth:unknown@icloud.com")

    await handle_force_reauth(callback, client, allowed_chat_ids=frozenset({1}))

    callback.answer.assert_awaited_once()
    callback.message.answer.assert_not_called()


@pytest.mark.asyncio
async def test_force_reauth_alerts_on_connection_error() -> None:
    client = ForceReauthRaisesClient()
    callback = make_callback(chat_id=1, data="force_reauth:jdoe@icloud.com")

    await handle_force_reauth(callback, client, allowed_chat_ids=frozenset({1}))

    callback.answer.assert_awaited_once()
    callback.message.answer.assert_not_called()
```

Update the `from bot.handlers import ...` line at the top of the test file to also import `handle_force_reauth`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd integrations/telegram-bot && python -m pytest tests/test_handlers.py -v`
Expected: FAIL with `ImportError: cannot import name 'handle_force_reauth'`

- [ ] **Step 3: Add the handler and router wiring**

In `integrations/telegram-bot/bot/handlers.py`, update the `from bot.messages import (...)` block to add:

```python
from bot.messages import (
    code_accepted_success_text,
    code_failed_keyboard,
    code_failed_text,
    code_requested_text,
    connection_lost_text,
    exited_text,
    force_reauth_not_found_text,
    force_reauth_requested_text,
    push_not_pending_text,
)
```

Add after `handle_exit`:

```python
async def handle_force_reauth(
    callback: CallbackQuery,
    client: IcloudpdClient,
    allowed_chat_ids: frozenset[int],
) -> None:
    chat_id = callback.message.chat.id
    if chat_id not in allowed_chat_ids:
        await callback.answer()
        return

    username = (callback.data or "").removeprefix("force_reauth:")
    try:
        triggered = await asyncio.to_thread(client.force_reauth, username)
    except requests.exceptions.RequestException:
        await callback.answer(connection_lost_text(), show_alert=True)
        return

    if not triggered:
        await callback.answer(force_reauth_not_found_text(), show_alert=True)
        return

    await callback.answer()
    await callback.message.answer(force_reauth_requested_text(username))
```

In `build_router`, add:

```python
    @router.callback_query(F.data.startswith("force_reauth:"))
    async def _force_reauth(callback: CallbackQuery) -> None:
        await handle_force_reauth(callback, client, allowed_chat_ids)
```

(place it before the catch-all `@router.message()` handler, alongside the other `callback_query` registrations)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd integrations/telegram-bot && python -m pytest tests/test_handlers.py -v`
Expected: PASS (all tests, including the 4 new ones)

- [ ] **Step 5: Commit**

```bash
cd integrations/telegram-bot
git add bot/handlers.py tests/test_handlers.py
git commit -m "feat: add handle_force_reauth and wire force_reauth: callback"
```

---

### Task 13: Telegram bot — wire `session_expiring_soon` into `main.py`

**Files:**
- Modify: `integrations/telegram-bot/bot/main.py`

- [ ] **Step 1: Update `main.py`**

Replace the contents of `integrations/telegram-bot/bot/main.py`:

```python
from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, Dispatcher
from aiohttp import web

from bot.config import load_config
from bot.handlers import build_router
from bot.icloudpd_client import IcloudpdClient
from bot.messages import (
    force_reauth_keyboard,
    session_expired_text,
    session_expiring_soon_text,
    start_2fa_keyboard,
)
from bot.notify_listener import build_notify_app
from bot.state import ChatState

logger = logging.getLogger(__name__)


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()

    bot = Bot(token=config.bot_token)
    dispatcher = Dispatcher()
    client = IcloudpdClient(config.icloudpd_base_url)
    state = ChatState()
    dispatcher.include_router(build_router(client, state, config.allowed_chat_ids))

    async def on_session_expired(event: dict[str, Any]) -> None:
        text = session_expired_text(
            event.get("username", "unknown account"), event.get("message", "")
        )
        for chat_id in config.allowed_chat_ids:
            await bot.send_message(chat_id, text, reply_markup=start_2fa_keyboard())

    async def on_session_expiring_soon(event: dict[str, Any]) -> None:
        username = event.get("username", "unknown account")
        text = session_expiring_soon_text(username, event.get("message", ""))
        for chat_id in config.allowed_chat_ids:
            await bot.send_message(chat_id, text, reply_markup=force_reauth_keyboard(username))

    notify_app = build_notify_app(on_session_expired, on_session_expiring_soon)
    runner = web.AppRunner(notify_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.notify_listener_port)
    await site.start()
    logger.info(
        "Notify listener on :%d, starting Telegram polling", config.notify_listener_port
    )

    try:
        await dispatcher.start_polling(bot)
    finally:
        await runner.cleanup()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the full bot test suite to confirm no regression**

Run: `cd integrations/telegram-bot && python -m pytest -v`
Expected: PASS (all tests across all bot test files)

- [ ] **Step 3: Commit**

```bash
cd integrations/telegram-bot
git add bot/main.py
git commit -m "feat: wire session_expiring_soon into the bot's notify listener"
```

---

### Task 14: Update the manual E2E checklist

**Files:**
- Modify: `integrations/telegram-bot/E2E_CHECKLIST.md`

- [ ] **Step 1: Add new steps**

Append to `integrations/telegram-bot/E2E_CHECKLIST.md`, before the final "Record the outcome" line:

```markdown
## Proactive session-expiry warning (issue #9)

10. Run icloudpd against an account/fixture whose stored session is inside the
    configured `--session-expiry-warning-days` window (e.g. `--session-expiry-warning-days 9999`
    against any valid session, to avoid needing an actual near-expiry cookie).
11. Confirm the bot DMs you a warning message ("`<username>`'s iCloud session expires
    in N day(s)...") with a **Refresh session now** button, separate from the
    **Start 2FA** message used by the reactive flow.
12. Tap **Refresh session now**. Confirm the bot replies confirming the refresh was
    requested, and that icloudpd's own logs show a new login attempt starting shortly
    after (within one watch-loop wake, not waiting out the full `--watch-with-interval`).
13. Confirm this new login attempt actually challenges 2FA (since the stored session
    token was cleared) and that the existing **Start 2FA** flow (steps 4-9 above) takes
    over from there, completing normally.
14. Tap **Refresh session now** for a username not configured on this icloudpd instance
    (simulate via a stale/incorrect `TELEGRAM_ALLOWED_CHAT_IDS` setup or a manually
    crafted callback if needed). Confirm the bot shows an alert and does not crash.
```

- [ ] **Step 2: Commit**

```bash
cd integrations/telegram-bot
git add E2E_CHECKLIST.md
git commit -m "docs: add E2E checklist steps for the force-reauth flow"
```

---

### Task 15: Run the manual E2E checklist

**This task requires a human, not an agent.** It needs a real, otherwise-unused Telegram bot token, a real (or disposable) Apple ID, and a person tapping buttons in Telegram and watching for a real push notification to arrive on a trusted device — none of which an agent can do unattended. If you're an agentic worker executing this plan, stop here and hand back to the user with:

> "Implementation and automated tests are complete. Task 15 (the manual E2E checklist in `integrations/telegram-bot/E2E_CHECKLIST.md`) needs to be run by a human against a real Telegram bot token and Apple ID before this is done. Let me know when you've run it, or if you'd like help setting up the environment (`.env`, `docker-compose.example.yml`) first."

- [ ] **Step 1: Set up the environment**

```bash
cd integrations/telegram-bot
cp .env.example .env
```

Fill in `TELEGRAM_BOT_TOKEN` (a spare, unused bot token — see `docs/superpowers/specs/2026-07-15-telegram-2fa-sidecar-design.md`'s Context section) and `TELEGRAM_ALLOWED_CHAT_IDS` (your own chat ID) in `.env`.

- [ ] **Step 2: Bring up the stack**

```bash
docker compose -f docker-compose.example.yml up --build
```

- [ ] **Step 3: Run through `E2E_CHECKLIST.md` in full**, including the new steps 10-14 added in Task 14, and record pass/fail for each step.

- [ ] **Step 4: Record the outcome in the PR description** before merging, per the checklist's existing closing instruction.

- [ ] **Step 5: If any step fails, stop and report back** rather than proceeding to merge — this checklist exists specifically to catch what unit tests can't (real Apple push delivery, real Telegram button rendering, real timing of the watch-loop wake).
