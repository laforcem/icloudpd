# General Notification System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace icloudpd's hardcoded, 2FA-only notification path with a general, structured, script-based event mechanism, so 2FA-expiry and the future deletion-sync feature (issue #5) can share one transport instead of each growing their own.

**Architecture:** A new standalone module `src/icloudpd/notifications.py` defines a `NotificationEvent` dataclass (event type, timestamp, username, human-readable message, event-specific `data` dict) and one delivery function, `notify()`, which serializes the event to JSON and runs a user-configured script with that JSON on stdin (`subprocess.run(..., input=..., timeout=...)`). This is the *only* built-in transport — the existing SMTP path is deleted outright, not migrated, so users integrate whatever they actually use (email, Telegram, Slack, a webhook) via a few lines of their own script. `notify()` is best-effort like `manifest.py`: failures are logged and swallowed, never raised into the caller. The existing 2FA-expiry call site in `base.py`'s `notificator_builder` becomes the first (and, in this plan, only) consumer, now constructing a `session_expired` event instead of directly calling SMTP/subprocess code.

**Tech Stack:** Python 3.10+ stdlib `subprocess`/`json`/`dataclasses` (no new dependency), pytest + `unittest.TestCase` + `unittest.mock.patch` (matching existing test style), `freezegun` for timestamp assertions, mypy `--strict`, ruff.

**Spec:** `docs/superpowers/specs/2026-07-15-notification-system-design.md`

---

## Task 1: `NotificationEvent` and `build_event`

**Files:**
- Create: `src/icloudpd/notifications.py`
- Test: `tests/test_notifications.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_notifications.py
import logging
from unittest import TestCase

import pytest
from freezegun import freeze_time

from icloudpd import notifications


class BuildEventTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self) -> None:
        self.logger = logging.getLogger("test_notifications")

    @freeze_time("2018-01-01T00:00:00+00:00")
    def test_build_event_sets_fields(self) -> None:
        event = notifications.build_event(
            event_type="session_expired",
            username="jdoe@gmail.com",
            message="hello",
        )
        self.assertEqual(event.event_type, "session_expired")
        self.assertEqual(event.username, "jdoe@gmail.com")
        self.assertEqual(event.message, "hello")
        self.assertEqual(event.timestamp, "2018-01-01T00:00:00+00:00")
        self.assertEqual(event.data, {})

    def test_build_event_carries_data(self) -> None:
        event = notifications.build_event(
            event_type="deletion_sync_summary",
            username="jdoe@gmail.com",
            message="Deleted 3 assets",
            data={"count": 3, "record_names": ["A", "B", "C"]},
        )
        self.assertEqual(event.data, {"count": 3, "record_names": ["A", "B", "C"]})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_notifications.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'icloudpd.notifications'` (or `ImportError`)

- [ ] **Step 3: Write minimal implementation**

```python
# src/icloudpd/notifications.py
"""General event notification mechanism.

Delivers structured events (2FA/session expiry, deletion-sync summaries,
etc.) to a single user-configured script as JSON on stdin. This is the
only built-in transport: icloudpd never talks to email/Telegram/Slack/etc.
directly, so it never has to maintain N integrations against N external
APIs. `event_type` is deliberately a plain string, not an enum - adding a
new event type is just a new consumer picking a new string, with no
changes required here.

All operations here are best-effort: failures are logged and swallowed
rather than raised, because a notification failing must never block or
fail a download/deletion-sync run.
"""

from __future__ import annotations

import datetime
import json
import logging
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class NotificationEvent:
    event_type: str
    timestamp: str
    username: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)


def _now_utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def build_event(
    event_type: str,
    username: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> NotificationEvent:
    return NotificationEvent(
        event_type=event_type,
        timestamp=_now_utc_iso(),
        username=username,
        message=message,
        data=data if data is not None else {},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_notifications.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd/notifications.py tests/test_notifications.py
git commit -m "feat: add NotificationEvent and build_event"
```

---

## Task 2: `notify()` — script delivery with structured payload

**Files:**
- Modify: `src/icloudpd/notifications.py`
- Test: `tests/test_notifications.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_notifications.py`:

```python
import dataclasses
import subprocess
from unittest.mock import MagicMock, patch


class NotifyTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self) -> None:
        self.logger = MagicMock(spec=logging.Logger)
        self.event = notifications.build_event(
            event_type="session_expired",
            username="jdoe@gmail.com",
            message="hello",
        )

    def test_notify_is_noop_when_script_path_is_none(self) -> None:
        with patch("icloudpd.notifications.subprocess.run") as run_mock:
            notifications.notify(self.logger, None, self.event)
            run_mock.assert_not_called()

    def test_notify_invokes_script_with_json_on_stdin(self) -> None:
        with patch("icloudpd.notifications.subprocess.run") as run_mock:
            run_mock.return_value = MagicMock(returncode=0, stderr="")
            notifications.notify(self.logger, "./notify.sh", self.event)
            run_mock.assert_called_once()
            args, kwargs = run_mock.call_args
            self.assertEqual(args[0], ["./notify.sh"])
            sent_payload = json.loads(kwargs["input"])
            self.assertEqual(sent_payload, dataclasses.asdict(self.event))
            self.assertEqual(kwargs["timeout"], 10.0)
            self.assertTrue(kwargs["text"])

    def test_notify_logs_warning_on_nonzero_exit(self) -> None:
        with patch("icloudpd.notifications.subprocess.run") as run_mock:
            run_mock.return_value = MagicMock(returncode=1, stderr="boom")
            notifications.notify(self.logger, "./notify.sh", self.event)
            self.logger.warning.assert_called_once()

    def test_notify_logs_warning_on_missing_script(self) -> None:
        with patch(
            "icloudpd.notifications.subprocess.run",
            side_effect=OSError("no such file"),
        ):
            notifications.notify(self.logger, "./missing.sh", self.event)
            self.logger.warning.assert_called_once()

    def test_notify_logs_warning_on_timeout(self) -> None:
        with patch(
            "icloudpd.notifications.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="./notify.sh", timeout=10.0),
        ):
            notifications.notify(self.logger, "./notify.sh", self.event)
            self.logger.warning.assert_called_once()

    def test_notify_respects_custom_timeout(self) -> None:
        with patch("icloudpd.notifications.subprocess.run") as run_mock:
            run_mock.return_value = MagicMock(returncode=0, stderr="")
            notifications.notify(self.logger, "./notify.sh", self.event, timeout_s=2.5)
            _, kwargs = run_mock.call_args
            self.assertEqual(kwargs["timeout"], 2.5)
```

Also add `import json` and `from unittest import TestCase` if not already present at top of the file from Task 1 (they are).

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_notifications.py -v`
Expected: FAIL with `AttributeError: module 'icloudpd.notifications' has no attribute 'notify'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/icloudpd/notifications.py`:

```python
def notify(
    logger: logging.Logger,
    script_path: str | None,
    event: NotificationEvent,
    timeout_s: float = 10.0,
) -> None:
    if script_path is None:
        return
    payload = json.dumps(asdict(event))
    try:
        result = subprocess.run(
            [script_path],
            input=payload,
            timeout=timeout_s,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning(
                "Notification script %s exited with code %d: %s",
                script_path,
                result.returncode,
                result.stderr,
            )
    except OSError as ex:
        logger.warning("Could not run notification script %s: %s", script_path, ex)
    except subprocess.TimeoutExpired:
        logger.warning(
            "Notification script %s timed out after %.1fs", script_path, timeout_s
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_notifications.py -v`
Expected: PASS (8 tests total)

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd/notifications.py tests/test_notifications.py
git commit -m "feat: add notify() script delivery with structured JSON payload"
```

---

## Task 3: Wire `notifications.py` into the 2FA-expiry call site

**Files:**
- Modify: `src/icloudpd/base.py:46` (import)
- Modify: `src/icloudpd/base.py:10` (import)
- Modify: `src/icloudpd/base.py:422-434` (notificator partial)
- Modify: `src/icloudpd/base.py:463-497` (`notificator_builder`)

This task rewires the *existing* 2FA-expiry notification to go through `notifications.notify()` instead of calling SMTP/subprocess directly. It does not yet remove the SMTP config surface (cli.py/config.py) — that's Task 4, kept separate so this task's diff is reviewable on its own.

- [ ] **Step 1: Update imports**

In `src/icloudpd/base.py`, three import changes:

1. Remove the now-unused `subprocess` import (line 10, only used inside the function this task rewrites):

```python
# Delete this line entirely:
import subprocess
```

2. Change line 41 from:

```python
from icloudpd import download, exif_datetime, manifest
```

to:

```python
from icloudpd import download, exif_datetime, manifest, notifications
```

3. Delete line 46 entirely (the email import is no longer needed):

```python
# Delete this line entirely:
from icloudpd.email_notifications import send_2sa_notification
```

- [ ] **Step 2: Simplify the `notificator` partial**

Find this block (around line 422):

```python
            notificator = partial(
                notificator_builder,
                logger,
                user_config.username,
                user_config.smtp_username,
                user_config.smtp_password,
                user_config.smtp_host,
                user_config.smtp_port,
                user_config.smtp_no_tls,
                user_config.notification_email,
                user_config.notification_email_from,
                str(user_config.notification_script) if user_config.notification_script else None,
            )
```

Replace with:

```python
            notificator = partial(
                notificator_builder,
                logger,
                user_config.username,
                str(user_config.notification_script) if user_config.notification_script else None,
            )
```

- [ ] **Step 3: Rewrite `notificator_builder`**

Find this block (around line 463):

```python
def notificator_builder(
    logger: logging.Logger,
    username: str,
    smtp_username: str | None,
    smtp_password: str | None,
    smtp_host: str,
    smtp_port: int,
    smtp_no_tls: bool,
    notification_email: str | None,
    notification_email_from: str | None,
    notification_script: str | None,
) -> None:
    try:
        if notification_script is not None:
            logger.debug("Executing notification script...")
            subprocess.call([notification_script])
        else:
            pass
        if smtp_username is not None or notification_email is not None:
            send_2sa_notification(
                logger,
                username,
                smtp_username,
                smtp_password,
                smtp_host,
                smtp_port,
                smtp_no_tls,
                notification_email,
                notification_email_from,
            )
        else:
            pass
    except Exception as error:
        logger.error("Notification of the required MFA failed")
        logger.debug(error)
```

Replace with:

```python
def notificator_builder(
    logger: logging.Logger,
    username: str,
    notification_script: str | None,
) -> None:
    event = notifications.build_event(
        event_type="session_expired",
        username=username,
        message=(
            f"{username}'s two-step authentication has expired for icloudpd. "
            "Please log in to your server and run the script manually to update "
            "two-step authentication."
        ),
    )
    notifications.notify(logger, notification_script, event)
```

(No `try`/`except` needed here — `notify()` is already best-effort internally and never raises.)

- [ ] **Step 4: Run the full test suite to see current breakage**

Run: `python3 -m pytest tests/test_email_notifications.py tests/test_cli.py -v`
Expected: FAIL — `test_cli.py`'s `UserConfig(...)` fixtures still pass `smtp_username=...` etc. (now-removed parameters don't exist on `notificator_builder`, but `UserConfig` itself is untouched until Task 4, so `test_cli.py` failures here are expected and will be fixed in Task 6). `test_email_notifications.py`'s SMTP-based tests will fail since `send_2sa_notification` is no longer called. This is expected — do not fix them in this task.

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd/base.py
git commit -m "feat: route 2FA-expiry notification through notifications.notify()"
```

---

## Task 4: Remove the SMTP/email config surface

**Files:**
- Modify: `src/icloudpd/config.py:35-41`
- Modify: `src/icloudpd/cli.py:145-190`
- Modify: `src/icloudpd/cli.py:455-462`

- [ ] **Step 1: Remove SMTP/email fields from `UserConfig`**

In `src/icloudpd/config.py`, in `_DefaultConfig`, delete these 7 lines:

```python
    smtp_username: str | None
    smtp_password: str | None
    smtp_host: str
    smtp_port: int
    smtp_no_tls: bool
    notification_email: str | None
    notification_email_from: str | None
```

Keep `notification_script: pathlib.Path | None` — it's still the (only) way to configure notifications.

- [ ] **Step 2: Remove the SMTP/email CLI flags**

In `src/icloudpd/cli.py`, delete this block (the flags between `--set-exif-datetime` and `--notification-script`):

```python
    cloned.add_argument(
        "--smtp-username",
        help="SMTP username for sending email notifications when two-step authentication expires.",
        default=None,
    )
    cloned.add_argument(
        "--smtp-password",
        help="SMTP password for sending email notifications when two-step authentication expires.",
        default=None,
    )
    cloned.add_argument(
        "--smtp-host",
        help="SMTP server host for notifications",
        default="smtp.gmail.com",
    )
    cloned.add_argument(
        "--smtp-port",
        help="SMTP server port. Default: %(default)i",
        type=int,
        default=587,
    )
    cloned.add_argument(
        "--smtp-no-tls",
        help="Disable TLS for SMTP (TLS is required for Gmail)",
        action="store_true",
    )
    cloned.add_argument(
        "--notification-email",
        help="Email address where you would like to receive email notifications. "
        "Default: SMTP username",
        default=None,
        type=str,
    )
    cloned.add_argument(
        "--notification-email-from",
        help="Email address from which you would like to receive email notifications. "
        "Default: SMTP username or notification-email",
        default=None,
        type=str,
    )
```

Update the remaining `--notification-script` argument's help text to reflect its now-general purpose:

```python
    cloned.add_argument(
        "--notification-script",
        type=pathlib.Path,
        help="Path to external script to run when a notification event occurs "
        "(e.g. two-step authentication expiring). Invoked with a JSON payload "
        "describing the event on stdin.",
        default=None,
    )
```

- [ ] **Step 3: Remove the fields from `map_to_config`**

In `src/icloudpd/cli.py`, in `map_to_config`, delete these 7 lines:

```python
        smtp_username=user_ns.smtp_username,
        smtp_password=user_ns.smtp_password,
        smtp_host=user_ns.smtp_host,
        smtp_port=user_ns.smtp_port,
        smtp_no_tls=user_ns.smtp_no_tls,
        notification_email=user_ns.notification_email,
        notification_email_from=user_ns.notification_email_from,
```

Keep `notification_script=user_ns.notification_script,`.

- [ ] **Step 4: Run mypy to confirm no dangling references**

Run: `python3 -m mypy src --strict --python-version 3.10`
Expected: errors only in `base.py`'s now-unused `send_2sa_notification` import (already removed in Task 3) and `email_notifications.py` itself if it references removed config — none expected here since Task 3 already removed the import. If clean, expect no errors related to this task's files.

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd/config.py src/icloudpd/cli.py
git commit -m "feat: remove SMTP/email config surface, notification-script is now general"
```

---

## Task 5: Delete `email_notifications.py` and migrate its tests

**Files:**
- Delete: `src/icloudpd/email_notifications.py`
- Delete: `tests/test_email_notifications.py`
- Create: `tests/test_session_expired_notification.py`

- [ ] **Step 1: Delete the old email module and its dedicated test file**

```bash
git rm src/icloudpd/email_notifications.py tests/test_email_notifications.py
```

- [ ] **Step 2: Write the migrated integration test**

```python
# tests/test_session_expired_notification.py
import inspect
import json
import os
from unittest import TestCase
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from tests.helpers import path_from_project_root, recreate_path, run_cassette


class SessionExpiredNotificationTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self) -> None:
        self.root_path = path_from_project_root(__file__)
        self.fixtures_path = os.path.join(self.root_path, "fixtures")
        self.vcr_path = os.path.join(self.root_path, "vcr_cassettes")

    @freeze_time("2018-01-01")
    def test_2sa_required_notification_script_receives_json_event(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])
        cookie_dir = os.path.join(base_dir, "cookie")
        data_dir = os.path.join(base_dir, "data")

        for dir in [base_dir, cookie_dir, data_dir]:
            recreate_path(dir)

        with patch("icloudpd.notifications.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            run_mock.return_value.stderr = ""
            result = run_cassette(
                os.path.join(self.vcr_path, "auth_requires_2fa.yml"),
                [
                    "--username",
                    "jdoe@gmail.com",
                    "--password",
                    "password1",
                    "--notification-script",
                    "./test_script.sh",
                    "-d",
                    data_dir,
                    "--cookie-directory",
                    cookie_dir,
                ],
            )
            self.assertEqual(result.exit_code, 1, "exit code")

            run_mock.assert_called_once()
            args, kwargs = run_mock.call_args
            self.assertEqual(args[0], ["test_script.sh"])
            payload = json.loads(kwargs["input"])
            self.assertEqual(payload["event_type"], "session_expired")
            self.assertEqual(payload["username"], "jdoe@gmail.com")
            self.assertIn("two-step authentication has expired", payload["message"])
```

- [ ] **Step 3: Run test to verify it passes**

Run: `python3 -m pytest tests/test_session_expired_notification.py -v`
Expected: PASS

If it fails because `test_script.sh` (referenced by `--notification-script ./test_script.sh`) doesn't exist as a real file and something upstream of `notify()` validates the path: check `run_cassette`/argparse — `--notification-script` uses `type=pathlib.Path`, which does not check existence, so this should pass without the file existing on disk (the mock intercepts `subprocess.run` before any real execution). If it does fail on a `FileNotFoundError` from argparse path validation, this indicates a `type=` conversion issue — re-check that `pathlib.Path` conversion (not a custom validator) is what's registered on the flag; no other explanation should apply, since no other test in this repo instantiates the referenced script file either.

- [ ] **Step 4: Commit**

```bash
git add tests/test_session_expired_notification.py
git commit -m "test: migrate 2FA-expiry test to assert structured JSON event delivery"
```

---

## Task 6: Clean up remaining references in test fixtures

**Files:**
- Modify: `tests/test_cli.py` (3 occurrences, lines ~221-227, ~261-267, ~337-343)
- Modify: `tests/helpers/__init__.py:170`

- [ ] **Step 1: Remove the removed fields from `test_cli.py`'s `UserConfig` fixtures**

In `tests/test_cli.py`, this exact 7-line block appears three times (once per `UserConfig(...)` test fixture):

```python
                            smtp_username=None,
                            smtp_password=None,
                            smtp_host="smtp.gmail.com",
                            smtp_port=587,
                            smtp_no_tls=False,
                            notification_email=None,
                            notification_email_from=None,
```

Delete all three occurrences (use a find-and-replace-all across the file — the text is byte-identical at each of the three sites, so a single `replace_all` edit handles all of them). Leave the following line (`notification_script=None,`) untouched at each site.

- [ ] **Step 2: Remove `--smtp-no-tls` from the legacy boolean-flag cleanup list**

In `tests/helpers/__init__.py`, in `clean_boolean_args`, remove this line from the `boolean_flags` set:

```python
        "--smtp-no-tls",
```

- [ ] **Step 3: Run the full test suite**

Run: `python3 -m pytest tests/test_cli.py tests/test_notifications.py tests/test_session_expired_notification.py -v`
Expected: PASS (all tests green)

- [ ] **Step 4: Commit**

```bash
git add tests/test_cli.py tests/helpers/__init__.py
git commit -m "test: remove references to deleted SMTP/email config fields"
```

---

## Task 7: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `./scripts/test`
Expected: all tests pass, no failures

- [ ] **Step 2: Run mypy --strict**

Run: `./scripts/type_check`
Expected: no errors (in particular: no dangling references to `email_notifications`, `smtp_username`, etc. anywhere in `src/` or `tests/`)

- [ ] **Step 3: Run ruff**

Run: `./scripts/lint`
Expected: no lint errors (in particular: no unused imports left behind in `base.py` from the removed `subprocess`/`send_2sa_notification` imports)

- [ ] **Step 4: Grep for any remaining dead references**

Run: `grep -rn "smtp_\|smtp-\|notification_email\|notification-email\|email_notifications" src tests`
Expected: no output. If anything shows up, it's a missed reference from an earlier task — fix it and re-run Steps 1-3.

- [ ] **Step 5: Final commit (only if Steps 1-4 required fixes)**

```bash
git add -A
git commit -m "fix: address verification findings"
```

If Steps 1-4 all passed clean with no fixes needed, skip this step — there's nothing to commit.
