# Telegram 2FA Sidecar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Defer icloudpd's automatic 2FA push notification until explicitly requested, and build an optional, unsupported Telegram sidecar that requests it and supplies the code via real buttons and plain-text replies.

**Architecture:** Core icloudpd gets a new `Status.AWAITING_MFA_TRIGGER` state (no push sent yet) that sits before the renamed `AWAITING_MFA_CODE` state (push sent, waiting for code), plus a `POST /trigger-push` endpoint and a JSON `GET /status.json` endpoint so a non-browser client can drive and observe the flow. A brand-new `integrations/telegram-bot/` package — excluded from core CI/tests — runs as a sidecar container: it receives `session_expired` events forwarded by a small script configured as icloudpd's `notification_script`, DMs a "Start 2FA" button to allowlisted Telegram chats, and on tap calls `/trigger-push` before accepting a plain-text code reply and submitting it to `/code`.

**Tech Stack:** Python 3.10+, Flask (existing), aiogram 3.x (new, sidecar-only), aiohttp (new, sidecar-only, also an aiogram dependency), requests (existing, reused for the sidecar's HTTP calls and the notify-forwarding script), pytest / pytest-asyncio / pytest-aiohttp / responses (test-only, sidecar).

**Reference:** `docs/superpowers/specs/2026-07-15-telegram-2fa-sidecar-design.md` — read this first for the full rationale (why the push is deferred, why states are split this way, why multi-account needs no new logic, why the sidecar can't touch core Telegram-specific code, network/auth model).

---

## Ground rules for whoever executes this plan

- Work happens on the `feature/telegram-2fa-sidecar` branch (already created, spec commit already on it). Do not touch `master`.
- Run root tests with `python3 -m pytest tests/test_status.py tests/test_authentication_webui.py tests/test_server.py -v` per-task, and the full suite (`scripts/test`) before the final commit of Tasks 1-4.
- Sidecar tests run from inside `integrations/telegram-bot/` with its own `pytest` invocation — they are never picked up by the root `scripts/test` (root `pyproject.toml` restricts `testpaths` to `tests` and `src`, confirmed during planning).
- Every commit message in this plan is a suggestion; keep the spirit (small, single-purpose commits) even if you reword.

---

## Task 1: Rename and extend the `Status` state machine

**Files:**
- Modify: `src/icloudpd/status.py`
- Test: `tests/test_status.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_status.py`:

```python
from icloudpd.status import Status, StatusExchange


def test_starts_idle() -> None:
    status_exchange = StatusExchange()
    assert status_exchange.get_status() == Status.IDLE


def test_replace_status_only_when_expected() -> None:
    status_exchange = StatusExchange()
    assert status_exchange.replace_status(Status.AWAITING_PASSWORD, Status.IDLE) is False
    assert status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER) is True
    assert status_exchange.get_status() == Status.AWAITING_MFA_TRIGGER


def test_trigger_mfa_only_from_awaiting_trigger() -> None:
    status_exchange = StatusExchange()
    assert status_exchange.trigger_mfa() is False  # still IDLE

    status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER)
    assert status_exchange.trigger_mfa() is True
    assert status_exchange.get_status() == Status.AWAITING_MFA_CODE
    assert status_exchange.trigger_mfa() is False  # already past AWAITING_MFA_TRIGGER


def test_set_payload_transitions_mfa_code_to_submitted() -> None:
    status_exchange = StatusExchange()
    status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER)
    status_exchange.trigger_mfa()

    assert status_exchange.set_payload("123456") is True
    assert status_exchange.get_status() == Status.SUBMITTED_MFA_CODE
    assert status_exchange.get_payload() == "123456"


def test_set_payload_rejected_outside_awaiting_states() -> None:
    status_exchange = StatusExchange()
    assert status_exchange.set_payload("123456") is False


def test_failed_mfa_validation_drops_back_to_awaiting_trigger() -> None:
    status_exchange = StatusExchange()
    status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER)
    status_exchange.trigger_mfa()
    status_exchange.set_payload("000000")
    status_exchange.replace_status(Status.SUBMITTED_MFA_CODE, Status.VALIDATING_MFA_CODE)

    assert status_exchange.set_error("bad code") is True
    assert status_exchange.get_status() == Status.AWAITING_MFA_TRIGGER
    assert status_exchange.get_error() == "bad code"


def test_failed_password_validation_drops_back_to_idle() -> None:
    status_exchange = StatusExchange()
    status_exchange.replace_status(Status.IDLE, Status.AWAITING_PASSWORD)
    status_exchange.set_payload("hunter2")
    status_exchange.replace_status(Status.SUBMITTED_PASSWORD, Status.VALIDATING_PASSWORD)

    assert status_exchange.set_error("bad password") is True
    assert status_exchange.get_status() == Status.IDLE
    assert status_exchange.get_error() == "bad password"


def test_get_payload_hidden_outside_submitted_or_validating() -> None:
    status_exchange = StatusExchange()
    assert status_exchange.get_payload() is None


def test_get_error_hidden_while_validating() -> None:
    status_exchange = StatusExchange()
    status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER)
    status_exchange.trigger_mfa()
    status_exchange.set_payload("123456")
    status_exchange.replace_status(Status.SUBMITTED_MFA_CODE, Status.VALIDATING_MFA_CODE)

    assert status_exchange.get_error() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_status.py -v`
Expected: FAIL — `AttributeError: IDLE` (or similar) since `Status.IDLE` / `trigger_mfa` don't exist yet.

- [ ] **Step 3: Rewrite `src/icloudpd/status.py`**

Replace the entire file:

```python
from enum import Enum
from threading import Lock
from typing import Sequence

from icloudpd.config import GlobalConfig, UserConfig
from icloudpd.progress import Progress


class Status(Enum):
    IDLE = "idle"
    AWAITING_MFA_TRIGGER = "awaiting_mfa_trigger"
    AWAITING_MFA_CODE = "awaiting_mfa_code"
    SUBMITTED_MFA_CODE = "submitted_mfa_code"
    VALIDATING_MFA_CODE = "validating_mfa_code"
    AWAITING_PASSWORD = "awaiting_password"
    SUBMITTED_PASSWORD = "submitted_password"
    VALIDATING_PASSWORD = "validating_password"

    def __str__(self) -> str:
        return self.name


class StatusExchange:
    def __init__(self) -> None:
        self.lock = Lock()
        self._status = Status.IDLE
        self._payload: str | None = None
        self._error: str | None = None
        self._global_config: GlobalConfig | None = None
        self._user_configs: Sequence[UserConfig] = []
        self._current_user: str | None = None
        self._progress = Progress()

    def get_status(self) -> Status:
        with self.lock:
            return self._status

    def replace_status(self, expected_status: Status, new_status: Status) -> bool:
        with self.lock:
            if self._status == expected_status:
                self._status = new_status
                return True
            else:
                return False

    def trigger_mfa(self) -> bool:
        with self.lock:
            if self._status != Status.AWAITING_MFA_TRIGGER:
                return False
            self._status = Status.AWAITING_MFA_CODE
            return True

    def set_payload(self, payload: str) -> bool:
        with self.lock:
            if self._status != Status.AWAITING_MFA_CODE and self._status != Status.AWAITING_PASSWORD:
                return False

            self._payload = payload
            self._status = (
                Status.SUBMITTED_MFA_CODE
                if self._status == Status.AWAITING_MFA_CODE
                else Status.SUBMITTED_PASSWORD
            )
            self._error = None
            return True

    def get_payload(self) -> str | None:
        with self.lock:
            if self._status not in [
                Status.SUBMITTED_MFA_CODE,
                Status.VALIDATING_MFA_CODE,
                Status.SUBMITTED_PASSWORD,
                Status.VALIDATING_PASSWORD,
            ]:
                return None

            return self._payload

    def set_error(self, error: str) -> bool:
        with self.lock:
            if self._status != Status.VALIDATING_MFA_CODE and self._status != Status.VALIDATING_PASSWORD:
                return False

            self._error = error
            self._status = (
                Status.IDLE
                if self._status == Status.VALIDATING_PASSWORD
                else Status.AWAITING_MFA_TRIGGER
            )
            return True

    def get_error(self) -> str | None:
        with self.lock:
            if self._status not in [
                Status.IDLE,
                Status.AWAITING_PASSWORD,
                Status.AWAITING_MFA_TRIGGER,
            ]:
                return None

            return self._error

    def get_progress(self) -> Progress:
        with self.lock:
            return self._progress

    def set_global_config(self, global_config: GlobalConfig) -> None:
        with self.lock:
            self._global_config = global_config

    def get_global_config(self) -> GlobalConfig | None:
        with self.lock:
            return self._global_config

    def set_user_configs(self, user_configs: Sequence[UserConfig]) -> None:
        with self.lock:
            self._user_configs = user_configs

    def get_user_configs(self) -> Sequence[UserConfig]:
        with self.lock:
            return self._user_configs

    def set_current_user(self, username: str) -> None:
        with self.lock:
            self._current_user = username

    def get_current_user(self) -> str | None:
        with self.lock:
            return self._current_user

    def clear_current_user(self) -> None:
        with self.lock:
            self._current_user = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_status.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd/status.py tests/test_status.py
git commit -m "feat: split MFA-required into awaiting-trigger and awaiting-code states"
```

---

## Task 2: Rename remaining `Status` call sites in `base.py` (password flow, mechanical)

`status.py`'s rename breaks `base.py`'s password-webui functions, which reference the old names directly. This is a pure rename — no behavior change to the password flow.

**Files:**
- Modify: `src/icloudpd/base.py:129-158`

- [ ] **Step 1: Confirm the break**

Run: `python3 -m mypy src/icloudpd/base.py`
Expected: errors like `Module has no attribute "NO_INPUT_NEEDED"` for `Status.NO_INPUT_NEEDED`, `Status.NEED_PASSWORD`, `Status.SUPPLIED_PASSWORD`, `Status.CHECKING_PASSWORD` (lines 133, 140, 144, 148-149, 158).

- [ ] **Step 2: Apply the rename**

In `src/icloudpd/base.py`, replace the block from `def get_password_from_webui` through `def update_password_status_in_webui` (lines 129-158) with:

```python
def get_password_from_webui(
    logger: Logger, status_exchange: StatusExchange, _user: str
) -> str | None:
    """Request two-factor authentication through Webui."""
    if not status_exchange.replace_status(Status.IDLE, Status.AWAITING_PASSWORD):
        logger.error("Expected IDLE, but got something else")
        return None

    # wait for input
    while True:
        status = status_exchange.get_status()
        if status == Status.AWAITING_PASSWORD:
            time.sleep(1)
        else:
            break
    if status_exchange.replace_status(Status.SUBMITTED_PASSWORD, Status.VALIDATING_PASSWORD):
        password = status_exchange.get_payload()
        if not password:
            logger.error("Internal error: did not get password for SUBMITTED_PASSWORD status")
            status_exchange.replace_status(
                Status.VALIDATING_PASSWORD, Status.IDLE
            )  # TODO Error
            return None
        return password

    return None  # TODO


def update_password_status_in_webui(status_exchange: StatusExchange, _u: str, _p: str) -> None:
    status_exchange.replace_status(Status.VALIDATING_PASSWORD, Status.IDLE)
```

(`update_auth_error_in_webui`, immediately below, is untouched — it only calls `set_error`, which doesn't reference a specific enum member by name.)

- [ ] **Step 3: Verify the rename is complete**

Run: `python3 -m mypy src/icloudpd/base.py src/icloudpd/authentication.py`
Expected: `authentication.py` still shows errors (Task 3 fixes those) — `base.py` should show none related to `Status`.

- [ ] **Step 4: Commit**

```bash
git add src/icloudpd/base.py
git commit -m "refactor: rename Status references in webui password flow"
```

---

## Task 3: Defer the 2FA push until explicitly triggered

**Files:**
- Modify: `src/icloudpd/authentication.py:250-303` (`request_2fa_web`)
- Test: `tests/test_authentication_webui.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_authentication_webui.py`:

```python
import threading
import time
from typing import List
from unittest import mock

from icloudpd.authentication import request_2fa_web
from icloudpd.logger import setup_logger
from icloudpd.status import Status, StatusExchange


def make_icloud(validate_results: List[bool]) -> mock.Mock:
    icloud = mock.Mock()
    icloud.trigger_push_notification.return_value = True
    icloud.validate_2fa_code.side_effect = validate_results
    return icloud


def wait_for_status(status_exchange: StatusExchange, expected: Status, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if status_exchange.get_status() == expected:
            return
        time.sleep(0.01)
    raise AssertionError(f"Timed out waiting for status {expected}, got {status_exchange.get_status()}")


def test_does_not_trigger_push_until_asked() -> None:
    status_exchange = StatusExchange()
    icloud = make_icloud([True])
    logger = setup_logger()

    thread = threading.Thread(
        target=request_2fa_web, args=(icloud, logger, status_exchange), daemon=True
    )
    thread.start()
    try:
        wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)
        icloud.trigger_push_notification.assert_not_called()
    finally:
        status_exchange.trigger_mfa()
        status_exchange.set_payload("123456")
        thread.join(timeout=2.0)


def test_successful_code_after_explicit_trigger() -> None:
    status_exchange = StatusExchange()
    icloud = make_icloud([True])
    logger = setup_logger()

    thread = threading.Thread(
        target=request_2fa_web, args=(icloud, logger, status_exchange), daemon=True
    )
    thread.start()

    wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)
    assert status_exchange.trigger_mfa() is True
    icloud.trigger_push_notification.assert_not_called()  # auth thread hasn't noticed yet

    wait_for_status(status_exchange, Status.AWAITING_MFA_CODE)
    time.sleep(0.05)  # let the auth thread's push call land
    assert thread.is_alive()
    icloud.trigger_push_notification.assert_called_once()

    assert status_exchange.set_payload("123456") is True
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert status_exchange.get_status() == Status.IDLE
    icloud.validate_2fa_code.assert_called_once_with("123456")


def test_failed_code_drops_back_to_awaiting_trigger() -> None:
    status_exchange = StatusExchange()
    icloud = make_icloud([False, True])
    logger = setup_logger()

    thread = threading.Thread(
        target=request_2fa_web, args=(icloud, logger, status_exchange), daemon=True
    )
    thread.start()

    wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)
    status_exchange.trigger_mfa()
    wait_for_status(status_exchange, Status.AWAITING_MFA_CODE)
    status_exchange.set_payload("000000")

    wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)
    assert status_exchange.get_error() == "Failed to verify two-factor authentication code"
    assert thread.is_alive()

    # "Try again": explicit re-trigger, then a correct code
    status_exchange.trigger_mfa()
    wait_for_status(status_exchange, Status.AWAITING_MFA_CODE)
    status_exchange.set_payload("123456")
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert status_exchange.get_status() == Status.IDLE
    assert icloud.trigger_push_notification.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_authentication_webui.py -v`
Expected: FAIL — `request_2fa_web` still triggers the push immediately, so `test_does_not_trigger_push_until_asked` fails on `assert_not_called()`.

- [ ] **Step 3: Rewrite `request_2fa_web`**

In `src/icloudpd/authentication.py`, replace the entire `request_2fa_web` function (lines 250-303) with:

```python
def request_2fa_web(
    icloud: PyiCloudService, logger: logging.Logger, status_exchange: StatusExchange
) -> None:
    """Request two-factor authentication through Webui."""
    if not status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER):
        raise PyiCloudFailedMFAException(
            f"Expected IDLE, but got {status_exchange.get_status()}"
        )

    while True:
        # wait for something (the WebUI, a bot, etc.) to ask for the push
        while status_exchange.get_status() == Status.AWAITING_MFA_TRIGGER:
            time.sleep(1)

        if status_exchange.get_status() != Status.AWAITING_MFA_CODE:
            raise PyiCloudFailedMFAException(
                f"Unexpected status while awaiting MFA trigger: {status_exchange.get_status()}"
            )

        # Trigger push notification to trusted devices now that it's been asked for.
        # Apple's auth flow (2026+) requires a PUT to /verify/trusteddevice/securitycode
        # to initiate code delivery. Failure is non-fatal — the user can still enter
        # a code if it arrives via another path.
        if not icloud.trigger_push_notification():
            logger.debug("Failed to trigger 2FA push notification, continuing anyway")
        else:
            logger.debug("2FA push notification triggered")

        # wait for a code to be submitted
        while status_exchange.get_status() == Status.AWAITING_MFA_CODE:
            time.sleep(1)

        if not status_exchange.replace_status(Status.SUBMITTED_MFA_CODE, Status.VALIDATING_MFA_CODE):
            raise PyiCloudFailedMFAException("Failed to change status")

        code = status_exchange.get_payload()
        if not code:
            raise PyiCloudFailedMFAException(
                "Internal error: did not get code for SUBMITTED_MFA_CODE status"
            )

        if not icloud.validate_2fa_code(code):
            if not status_exchange.set_error("Failed to verify two-factor authentication code"):
                raise PyiCloudFailedMFAException("Failed to change status of invalid code")
            # dropped back to AWAITING_MFA_TRIGGER; loop and wait for another explicit trigger
            continue

        status_exchange.replace_status(Status.VALIDATING_MFA_CODE, Status.IDLE)  # done
        logger.info(
            "Great, you're all set up. The script can now be run without "
            "user interaction until 2FA expires.\n"
            "You can set up a notification script for when "
            "the two-factor authentication expires.\n"
            "(Use --notification-script to configure this.)"
        )
        return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_authentication_webui.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the existing authentication test suite to confirm no regression**

Run: `python3 -m pytest tests/test_authentication.py -v`
Expected: PASS — `test_password_prompt_2fa` and friends exercise the *console* path (`request_2fa`), which this task didn't touch.

- [ ] **Step 6: Commit**

```bash
git add src/icloudpd/authentication.py tests/test_authentication_webui.py
git commit -m "feat: defer 2FA push notification until explicitly triggered"
```

---

## Task 4: `/trigger-push` + JSON status endpoint + WebUI template for the new state

The existing `serve_app` builds a Flask app and immediately calls `waitress.serve()` on it in one function — there's no way to get the `Flask` object out for testing. Split app-building from serving as part of this change (this file has zero tests today; this is what makes testing it possible at all).

**Files:**
- Modify: `src/icloudpd/server/__init__.py`
- Create: `src/icloudpd/server/templates/mfa_trigger.html`
- Test: `tests/test_server.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server.py`:

```python
from flask.testing import FlaskClient

from icloudpd.logger import setup_logger
from icloudpd.server import build_app
from icloudpd.status import Status, StatusExchange


def make_client(status_exchange: StatusExchange) -> FlaskClient:
    app = build_app(setup_logger(), status_exchange)
    return app.test_client()


def test_status_idle_renders_no_input() -> None:
    status_exchange = StatusExchange()
    client = make_client(status_exchange)

    response = client.get("/status")

    assert response.status_code == 200
    assert b"No input is needed" in response.data


def test_status_awaiting_mfa_trigger_renders_trigger_prompt() -> None:
    status_exchange = StatusExchange()
    status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER)
    client = make_client(status_exchange)

    response = client.get("/status")

    assert response.status_code == 200
    assert b"Two-factor authentication is required" in response.data
    assert b"/trigger-push" in response.data


def test_status_awaiting_mfa_code_renders_code_form() -> None:
    status_exchange = StatusExchange()
    status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER)
    status_exchange.trigger_mfa()
    client = make_client(status_exchange)

    response = client.get("/status")

    assert response.status_code == 200
    assert b"Two-Factor code" in response.data


def test_status_json_reports_current_state() -> None:
    status_exchange = StatusExchange()
    status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER)
    status_exchange.set_current_user("jdoe@icloud.com")
    client = make_client(status_exchange)

    response = client.get("/status.json")

    assert response.status_code == 200
    assert response.json == {
        "status": "AWAITING_MFA_TRIGGER",
        "error": None,
        "current_user": "jdoe@icloud.com",
    }


def test_trigger_push_moves_awaiting_trigger_to_awaiting_code() -> None:
    status_exchange = StatusExchange()
    status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER)
    client = make_client(status_exchange)

    response = client.post("/trigger-push")

    assert response.status_code == 204
    assert status_exchange.get_status() == Status.AWAITING_MFA_CODE


def test_trigger_push_rejects_when_nothing_pending() -> None:
    status_exchange = StatusExchange()
    client = make_client(status_exchange)

    response = client.post("/trigger-push")

    assert response.status_code == 409
    assert status_exchange.get_status() == Status.IDLE


def test_code_endpoint_accepts_code_when_awaiting() -> None:
    status_exchange = StatusExchange()
    status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER)
    status_exchange.trigger_mfa()
    client = make_client(status_exchange)

    response = client.post("/code", data={"code": "123456"})

    assert response.status_code == 200
    assert status_exchange.get_status() == Status.SUBMITTED_MFA_CODE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_server.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_app' from 'icloudpd.server'`.

- [ ] **Step 3: Create the new template**

Create `src/icloudpd/server/templates/mfa_trigger.html`:

```html
<div hx-get="/status" hx-trigger="every 5s" hx-swap="outerHTML">
    <fieldset>
        <legend>Authentication{% if current_user %} - {{ current_user }}{% endif %}</legend>
        {% if error %}
        <ul class="list-group list-group-flush">
            <li class="list-group-item d-flex justify-content-between align-items-center">
                <div class="fw-bold">{{ error }}</div>
            </li>
        </ul>
        {% endif %}
        <div class="col-12 mb-3">
            <label class="form-label">Two-factor authentication is required for {{ current_user if current_user else 'iCloud account' }}</label>
        </div>
        <div class="col-12">
            <button hx-post="/trigger-push" hx-swap="none" class="btn btn-primary">Send code</button>
        </div>
    </fieldset>
</div>
```

- [ ] **Step 4: Rewrite `src/icloudpd/server/__init__.py`**

Replace the entire file:

```python
import os
import sys
from logging import Logger

import waitress
from flask import Flask, Response, jsonify, make_response, render_template, request

from icloudpd.status import Status, StatusExchange


def build_app(logger: Logger, _status_exchange: StatusExchange) -> Flask:
    app = Flask(__name__)
    app.logger = logger
    # for running in pyinstaller
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir is not None:
        app.template_folder = os.path.join(bundle_dir, "templates")
        app.static_folder = os.path.join(bundle_dir, "static")

    @app.route("/")
    def index() -> Response | str:
        return render_template("index.html")

    @app.route("/status", methods=["GET"])
    def get_status() -> Response | str:
        _status = _status_exchange.get_status()
        _global_config = _status_exchange.get_global_config()
        _user_configs = _status_exchange.get_user_configs()
        _current_user = _status_exchange.get_current_user()
        _progress = _status_exchange.get_progress()
        _error = _status_exchange.get_error()

        if _status == Status.IDLE:
            return render_template(
                "no_input.html",
                status=_status,
                error=_error,
                progress=_progress,
                global_config=vars(_global_config) if _global_config else None,
                user_configs=[vars(uc) for uc in _user_configs] if _user_configs else [],
                current_user=_current_user,
            )
        if _status == Status.AWAITING_MFA_TRIGGER:
            return render_template("mfa_trigger.html", error=_error, current_user=_current_user)
        if _status == Status.AWAITING_MFA_CODE:
            return render_template("code.html", error=_error, current_user=_current_user)
        if _status == Status.AWAITING_PASSWORD:
            return render_template("password.html", error=_error, current_user=_current_user)
        return render_template("status.html", status=_status)

    @app.route("/status.json", methods=["GET"])
    def get_status_json() -> Response:
        return jsonify(
            {
                "status": str(_status_exchange.get_status()),
                "error": _status_exchange.get_error(),
                "current_user": _status_exchange.get_current_user(),
            }
        )

    @app.route("/code", methods=["POST"])
    def set_code() -> Response | str:
        _current_user = _status_exchange.get_current_user()
        code = request.form.get("code")
        if code is not None:
            if _status_exchange.set_payload(code):
                return render_template("code_submitted.html", current_user=_current_user)
        else:
            logger.error(f"cannot find code in request {request.form}")
        return make_response(
            render_template(
                "auth_error.html",
                type="Two-Factor Code",
                current_user=_current_user,
            ),
            400,
        )  # incorrect code

    @app.route("/password", methods=["POST"])
    def set_password() -> Response | str:
        _current_user = _status_exchange.get_current_user()
        password = request.form.get("password")
        if password is not None:
            if _status_exchange.set_payload(password):
                return render_template("password_submitted.html", current_user=_current_user)
        else:
            logger.error(f"cannot find password in request {request.form}")
        return make_response(
            render_template("auth_error.html", type="password", current_user=_current_user),
            400,
        )  # incorrect code

    @app.route("/trigger-push", methods=["POST"])
    def trigger_push() -> Response:
        if _status_exchange.trigger_mfa():
            return make_response("", 204)
        return make_response("Not awaiting an MFA trigger", 409)

    @app.route("/resume", methods=["POST"])
    def resume() -> Response | str:
        _status_exchange.get_progress().resume = True
        return make_response("Ok", 200)

    @app.route("/cancel", methods=["POST"])
    def cancel() -> Response | str:
        _status_exchange.get_progress().cancel = True
        return make_response("Ok", 200)

    return app


def serve_app(logger: Logger, _status_exchange: StatusExchange) -> None:
    logger.debug("Starting web server...")
    return waitress.serve(build_app(logger, _status_exchange))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_server.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Run the full root suite**

Run: `scripts/test`
Expected: PASS, no regressions in `tests/test_authentication.py`, `tests/test_notifications.py`, `tests/test_session_expired_notification.py`, or elsewhere.

- [ ] **Step 7: Commit**

```bash
git add src/icloudpd/server/__init__.py src/icloudpd/server/templates/mfa_trigger.html tests/test_server.py
git commit -m "feat: add /trigger-push and /status.json, split build_app from serve_app"
```

---

## Task 5: Scaffold the `integrations/telegram-bot/` package

Everything from here on lives outside `src/icloudpd/` and is never imported by it or referenced by the root `pyproject.toml`/`scripts/test` — this is the "optional, unsupported, no maintenance commitment" boundary from the design doc.

**Files:**
- Create: `integrations/telegram-bot/pyproject.toml`
- Create: `integrations/telegram-bot/bot/__init__.py`
- Modify: `.gitignore`

- [ ] **Step 1: Create the package layout**

Create `integrations/telegram-bot/bot/__init__.py` (empty file).

Create `integrations/telegram-bot/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "telegram-bot"
version = "0.1.0"
description = "Optional, unsupported Telegram sidecar for icloudpd notifications (2FA and beyond). No maintenance commitment."
requires-python = ">=3.10"
dependencies = [
    "aiogram==3.15.0",
    "aiohttp==3.11.11",
    "requests==2.32.3",
]

[project.optional-dependencies]
test = [
    "pytest==8.4.0",
    "pytest-asyncio==0.25.0",
    "pytest-aiohttp==1.1.0",
    "responses==0.25.3",
]

[tool.setuptools.packages.find]
include = ["bot*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Add `.env` to `.gitignore`**

In `.gitignore`, add a new line after the `.claude/` / `.superpowers/` / `uv.lock` block:

```
.env
```

- [ ] **Step 3: Confirm the root suite still ignores this directory**

Run: `python3 -m pytest --collect-only 2>&1 | grep -i telegram`
Expected: no output — root `pytest` (governed by root `pyproject.toml`'s `testpaths = ["tests", "src"]`) does not discover anything under `integrations/`.

- [ ] **Step 4: Commit**

```bash
git add integrations/telegram-bot/pyproject.toml integrations/telegram-bot/bot/__init__.py .gitignore
git commit -m "chore: scaffold integrations/telegram-bot package"
```

---

## Task 6: `bot/config.py` — environment-driven configuration

**Files:**
- Create: `integrations/telegram-bot/bot/config.py`
- Test: `integrations/telegram-bot/tests/test_config.py`

- [ ] **Step 1: Create the sidecar's test package**

Create `integrations/telegram-bot/tests/__init__.py` (empty file).

- [ ] **Step 2: Write the failing tests**

Create `integrations/telegram-bot/tests/test_config.py`:

```python
import pytest

from bot.config import load_config


def test_load_config_parses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "488165044, 999")
    monkeypatch.setenv("ICLOUDPD_BASE_URL", "http://icloudpd:8080")

    config = load_config()

    assert config.bot_token == "123:abc"
    assert config.allowed_chat_ids == frozenset({488165044, 999})
    assert config.icloudpd_base_url == "http://icloudpd:8080"
    assert config.notify_listener_port == 8090


def test_load_config_defaults_base_url_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "488165044")
    monkeypatch.delenv("ICLOUDPD_BASE_URL", raising=False)
    monkeypatch.delenv("NOTIFY_LISTENER_PORT", raising=False)

    config = load_config()

    assert config.icloudpd_base_url == "http://icloudpd:8080"
    assert config.notify_listener_port == 8090


def test_load_config_requires_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "488165044")

    with pytest.raises(KeyError):
        load_config()
```

- [ ] **Step 3: Run tests to verify they fail**

Run (from `integrations/telegram-bot/`): `pip install -e '.[test]' && pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.config'`.

- [ ] **Step 4: Write the implementation**

Create `integrations/telegram-bot/bot/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BotConfig:
    bot_token: str
    allowed_chat_ids: frozenset[int]
    icloudpd_base_url: str
    notify_listener_port: int = 8090


def load_config() -> BotConfig:
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    raw_chat_ids = os.environ["TELEGRAM_ALLOWED_CHAT_IDS"]
    allowed_chat_ids = frozenset(
        int(chat_id.strip()) for chat_id in raw_chat_ids.split(",") if chat_id.strip()
    )
    icloudpd_base_url = os.environ.get("ICLOUDPD_BASE_URL", "http://icloudpd:8080")
    notify_listener_port = int(os.environ.get("NOTIFY_LISTENER_PORT", "8090"))
    return BotConfig(
        bot_token=bot_token,
        allowed_chat_ids=allowed_chat_ids,
        icloudpd_base_url=icloudpd_base_url,
        notify_listener_port=notify_listener_port,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add integrations/telegram-bot/bot/config.py integrations/telegram-bot/tests/__init__.py integrations/telegram-bot/tests/test_config.py
git commit -m "feat(telegram-bot): add environment-driven config loader"
```

---

## Task 7: `bot/icloudpd_client.py` — HTTP client for icloudpd's endpoints

**Files:**
- Create: `integrations/telegram-bot/bot/icloudpd_client.py`
- Test: `integrations/telegram-bot/tests/test_icloudpd_client.py`

- [ ] **Step 1: Write the failing tests**

Create `integrations/telegram-bot/tests/test_icloudpd_client.py`:

```python
import responses

from bot.icloudpd_client import IcloudpdClient


@responses.activate
def test_trigger_push_success() -> None:
    responses.add(responses.POST, "http://icloudpd:8080/trigger-push", status=204)
    client = IcloudpdClient("http://icloudpd:8080")

    assert client.trigger_push() is True


@responses.activate
def test_trigger_push_conflict() -> None:
    responses.add(responses.POST, "http://icloudpd:8080/trigger-push", status=409)
    client = IcloudpdClient("http://icloudpd:8080")

    assert client.trigger_push() is False


@responses.activate
def test_submit_code_success() -> None:
    responses.add(responses.POST, "http://icloudpd:8080/code", status=200)
    client = IcloudpdClient("http://icloudpd:8080")

    assert client.submit_code("123456") is True


@responses.activate
def test_submit_code_rejected() -> None:
    responses.add(responses.POST, "http://icloudpd:8080/code", status=400)
    client = IcloudpdClient("http://icloudpd:8080")

    assert client.submit_code("000000") is False


@responses.activate
def test_get_status_parses_json() -> None:
    responses.add(
        responses.GET,
        "http://icloudpd:8080/status.json",
        json={"status": "AWAITING_MFA_TRIGGER", "error": None, "current_user": "jdoe@icloud.com"},
        status=200,
    )
    client = IcloudpdClient("http://icloudpd:8080")

    status = client.get_status()

    assert status.status == "AWAITING_MFA_TRIGGER"
    assert status.error is None
    assert status.current_user == "jdoe@icloud.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_icloudpd_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.icloudpd_client'`.

- [ ] **Step 3: Write the implementation**

Create `integrations/telegram-bot/bot/icloudpd_client.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class MfaStatus:
    status: str
    error: str | None
    current_user: str | None


class IcloudpdClient:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def trigger_push(self) -> bool:
        response = requests.post(f"{self._base_url}/trigger-push", timeout=self._timeout)
        return response.status_code == 204

    def submit_code(self, code: str) -> bool:
        response = requests.post(
            f"{self._base_url}/code", data={"code": code}, timeout=self._timeout
        )
        return response.status_code == 200

    def get_status(self) -> MfaStatus:
        response = requests.get(f"{self._base_url}/status.json", timeout=self._timeout)
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return MfaStatus(
            status=body["status"],
            error=body.get("error"),
            current_user=body.get("current_user"),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_icloudpd_client.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add integrations/telegram-bot/bot/icloudpd_client.py integrations/telegram-bot/tests/test_icloudpd_client.py
git commit -m "feat(telegram-bot): add icloudpd HTTP client"
```

---

## Task 8: `bot/mfa_result.py` — poll icloudpd until a submitted code resolves

**Files:**
- Create: `integrations/telegram-bot/bot/mfa_result.py`
- Test: `integrations/telegram-bot/tests/test_mfa_result.py`

- [ ] **Step 1: Write the failing tests**

Create `integrations/telegram-bot/tests/test_mfa_result.py`:

```python
from bot.icloudpd_client import MfaStatus
from bot.mfa_result import wait_for_mfa_result


class FakeClient:
    def __init__(self, statuses: list[MfaStatus]) -> None:
        self._statuses = statuses

    def get_status(self) -> MfaStatus:
        if len(self._statuses) > 1:
            return self._statuses.pop(0)
        return self._statuses[0]


def test_success_when_status_becomes_idle() -> None:
    client = FakeClient(
        [
            MfaStatus("VALIDATING_MFA_CODE", None, "jdoe@icloud.com"),
            MfaStatus("IDLE", None, "jdoe@icloud.com"),
        ]
    )

    success, error = wait_for_mfa_result(client, poll_interval=0, sleep=lambda _s: None)

    assert success is True
    assert error is None


def test_failure_when_status_drops_to_awaiting_trigger_with_error() -> None:
    client = FakeClient(
        [
            MfaStatus(
                "AWAITING_MFA_TRIGGER",
                "Failed to verify two-factor authentication code",
                "jdoe@icloud.com",
            )
        ]
    )

    success, error = wait_for_mfa_result(client, poll_interval=0, sleep=lambda _s: None)

    assert success is False
    assert error == "Failed to verify two-factor authentication code"


def test_times_out_if_status_never_resolves() -> None:
    client = FakeClient([MfaStatus("VALIDATING_MFA_CODE", None, "jdoe@icloud.com")] * 3)

    success, error = wait_for_mfa_result(client, poll_interval=0, timeout=0, sleep=lambda _s: None)

    assert success is False
    assert error == "Timed out waiting for verification result"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mfa_result.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.mfa_result'`.

- [ ] **Step 3: Write the implementation**

Create `integrations/telegram-bot/bot/mfa_result.py`:

```python
from __future__ import annotations

import time
from typing import Callable, Protocol

from bot.icloudpd_client import MfaStatus


class StatusSource(Protocol):
    def get_status(self) -> MfaStatus: ...


def wait_for_mfa_result(
    client: StatusSource,
    poll_interval: float = 1.0,
    timeout: float = 15.0,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, str | None]:
    """Poll icloudpd until a submitted code resolves. Returns (success, error_message)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get_status()
        if status.status == "IDLE":
            return True, None
        if status.status == "AWAITING_MFA_TRIGGER" and status.error:
            return False, status.error
        sleep(poll_interval)
    return False, "Timed out waiting for verification result"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mfa_result.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add integrations/telegram-bot/bot/mfa_result.py integrations/telegram-bot/tests/test_mfa_result.py
git commit -m "feat(telegram-bot): add polling helper for code verification result"
```

---

## Task 9: `bot/state.py` — per-chat "awaiting code" tracking

**Files:**
- Create: `integrations/telegram-bot/bot/state.py`
- Test: `integrations/telegram-bot/tests/test_state.py`

- [ ] **Step 1: Write the failing tests**

Create `integrations/telegram-bot/tests/test_state.py`:

```python
from bot.state import ChatState


def test_not_awaiting_by_default() -> None:
    state = ChatState()
    assert state.is_awaiting_code(1) is False


def test_start_and_stop_awaiting() -> None:
    state = ChatState()
    state.start_awaiting_code(1)
    assert state.is_awaiting_code(1) is True

    state.stop_awaiting_code(1)
    assert state.is_awaiting_code(1) is False


def test_tracks_chats_independently() -> None:
    state = ChatState()
    state.start_awaiting_code(1)
    assert state.is_awaiting_code(2) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.state'`.

- [ ] **Step 3: Write the implementation**

Create `integrations/telegram-bot/bot/state.py`:

```python
from __future__ import annotations

from threading import Lock


class ChatState:
    """Tracks which chats are currently expected to send a 2FA code next."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._awaiting_code: set[int] = set()

    def start_awaiting_code(self, chat_id: int) -> None:
        with self._lock:
            self._awaiting_code.add(chat_id)

    def stop_awaiting_code(self, chat_id: int) -> None:
        with self._lock:
            self._awaiting_code.discard(chat_id)

    def is_awaiting_code(self, chat_id: int) -> bool:
        with self._lock:
            return chat_id in self._awaiting_code
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_state.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add integrations/telegram-bot/bot/state.py integrations/telegram-bot/tests/test_state.py
git commit -m "feat(telegram-bot): add per-chat awaiting-code state tracking"
```

---

## Task 10: `bot/messages.py` — pure text and keyboard builders

**Files:**
- Create: `integrations/telegram-bot/bot/messages.py`
- Test: `integrations/telegram-bot/tests/test_messages.py`

- [ ] **Step 1: Write the failing tests**

Create `integrations/telegram-bot/tests/test_messages.py`:

```python
from bot.messages import (
    code_accepted_success_text,
    code_failed_keyboard,
    code_failed_text,
    code_requested_text,
    session_expired_text,
    start_2fa_keyboard,
)


def test_session_expired_text_includes_username_and_message() -> None:
    text = session_expired_text("jdoe@icloud.com", "2FA has expired")

    assert "jdoe@icloud.com" in text
    assert "2FA has expired" in text


def test_start_2fa_keyboard_has_one_button() -> None:
    keyboard = start_2fa_keyboard()

    assert keyboard.inline_keyboard[0][0].callback_data == "start_2fa"


def test_code_requested_text_includes_username() -> None:
    assert "jdoe@icloud.com" in code_requested_text("jdoe@icloud.com")


def test_code_accepted_success_text_includes_username() -> None:
    assert "jdoe@icloud.com" in code_accepted_success_text("jdoe@icloud.com")


def test_code_failed_text_includes_error() -> None:
    assert "bad code" in code_failed_text("bad code")


def test_code_failed_keyboard_has_retry_and_exit() -> None:
    keyboard = code_failed_keyboard()
    callback_datas = {button.callback_data for row in keyboard.inline_keyboard for button in row}

    assert callback_datas == {"retry_2fa", "exit_2fa"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_messages.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.messages'`.

- [ ] **Step 3: Write the implementation**

Create `integrations/telegram-bot/bot/messages.py`:

```python
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def session_expired_text(username: str, message: str) -> str:
    return f"\U0001F510 {username}: {message}"


def start_2fa_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Start 2FA", callback_data="start_2fa")]]
    )


def code_requested_text(username: str) -> str:
    return f"Code requested for {username}. Paste the 6-digit code you received."


def push_not_pending_text() -> str:
    return "Nothing is waiting on a 2FA code right now."


def code_accepted_success_text(username: str) -> str:
    return f"✅ Authenticated for {username}."


def code_failed_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Try again", callback_data="retry_2fa"),
                InlineKeyboardButton(text="Exit", callback_data="exit_2fa"),
            ]
        ]
    )


def code_failed_text(error: str) -> str:
    return f"❌ {error}"


def exited_text() -> str:
    return "Okay. Tap Start 2FA again whenever you're ready."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_messages.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add integrations/telegram-bot/bot/messages.py integrations/telegram-bot/tests/test_messages.py
git commit -m "feat(telegram-bot): add message and keyboard builders"
```

---

## Task 11: `bot/handlers.py` — the Telegram interaction flow

**Files:**
- Create: `integrations/telegram-bot/bot/handlers.py`
- Test: `integrations/telegram-bot/tests/test_handlers.py`

- [ ] **Step 1: Write the failing tests**

Create `integrations/telegram-bot/tests/test_handlers.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import handle_exit, handle_message, handle_start_or_retry
from bot.icloudpd_client import MfaStatus
from bot.state import ChatState


class FakeClient:
    def __init__(
        self,
        trigger_push_result: bool = True,
        submit_code_result: bool = True,
        status_sequence: list[MfaStatus] | None = None,
    ) -> None:
        self.trigger_push_result = trigger_push_result
        self.submit_code_result = submit_code_result
        self._status_sequence = status_sequence or [MfaStatus("IDLE", None, "jdoe@icloud.com")]

    def trigger_push(self) -> bool:
        return self.trigger_push_result

    def submit_code(self, code: str) -> bool:
        return self.submit_code_result

    def get_status(self) -> MfaStatus:
        if len(self._status_sequence) > 1:
            return self._status_sequence.pop(0)
        return self._status_sequence[0]


def make_callback(chat_id: int, data: str) -> SimpleNamespace:
    return SimpleNamespace(
        data=data,
        message=SimpleNamespace(chat=SimpleNamespace(id=chat_id), answer=AsyncMock()),
        answer=AsyncMock(),
    )


def make_message(chat_id: int, text: str) -> SimpleNamespace:
    return SimpleNamespace(chat=SimpleNamespace(id=chat_id), text=text, answer=AsyncMock())


@pytest.mark.asyncio
async def test_start_ignores_disallowed_chat() -> None:
    client = FakeClient()
    state = ChatState()
    callback = make_callback(chat_id=1, data="start_2fa")

    await handle_start_or_retry(callback, client, state, allowed_chat_ids=frozenset({2}))

    callback.answer.assert_awaited_once_with()
    callback.message.answer.assert_not_called()
    assert state.is_awaiting_code(1) is False


@pytest.mark.asyncio
async def test_start_triggers_push_and_awaits_code() -> None:
    client = FakeClient(trigger_push_result=True)
    state = ChatState()
    callback = make_callback(chat_id=1, data="start_2fa")

    await handle_start_or_retry(callback, client, state, allowed_chat_ids=frozenset({1}))

    assert state.is_awaiting_code(1) is True
    callback.message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_alerts_when_nothing_pending() -> None:
    client = FakeClient(trigger_push_result=False)
    state = ChatState()
    callback = make_callback(chat_id=1, data="start_2fa")

    await handle_start_or_retry(callback, client, state, allowed_chat_ids=frozenset({1}))

    callback.answer.assert_awaited_once()
    assert state.is_awaiting_code(1) is False


@pytest.mark.asyncio
async def test_exit_stops_awaiting_code() -> None:
    client = FakeClient()
    state = ChatState()
    state.start_awaiting_code(1)
    callback = make_callback(chat_id=1, data="exit_2fa")

    await handle_exit(callback, state, allowed_chat_ids=frozenset({1}))

    assert state.is_awaiting_code(1) is False
    callback.message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_message_ignored_when_not_awaiting_code() -> None:
    client = FakeClient()
    state = ChatState()
    message = make_message(chat_id=1, text="123456")

    await handle_message(message, client, state, allowed_chat_ids=frozenset({1}))

    message.answer.assert_not_called()


@pytest.mark.asyncio
async def test_message_reports_success() -> None:
    client = FakeClient(
        submit_code_result=True,
        status_sequence=[MfaStatus("IDLE", None, "jdoe@icloud.com")],
    )
    state = ChatState()
    state.start_awaiting_code(1)
    message = make_message(chat_id=1, text="123456")

    await handle_message(message, client, state, allowed_chat_ids=frozenset({1}))

    message.answer.assert_awaited_once()
    assert "jdoe@icloud.com" in message.answer.await_args.args[0]
    assert state.is_awaiting_code(1) is False


@pytest.mark.asyncio
async def test_message_reports_failure_with_retry_buttons() -> None:
    client = FakeClient(
        submit_code_result=True,
        status_sequence=[
            MfaStatus(
                "AWAITING_MFA_TRIGGER",
                "Failed to verify two-factor authentication code",
                "jdoe@icloud.com",
            )
        ],
    )
    state = ChatState()
    state.start_awaiting_code(1)
    message = make_message(chat_id=1, text="000000")

    await handle_message(message, client, state, allowed_chat_ids=frozenset({1}))

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.await_args
    assert "Failed to verify" in args[0]
    assert "reply_markup" in kwargs
    assert state.is_awaiting_code(1) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_handlers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.handlers'`.

- [ ] **Step 3: Write the implementation**

Create `integrations/telegram-bot/bot/handlers.py`:

```python
from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.icloudpd_client import IcloudpdClient
from bot.mfa_result import wait_for_mfa_result
from bot.messages import (
    code_accepted_success_text,
    code_failed_keyboard,
    code_failed_text,
    code_requested_text,
    exited_text,
    push_not_pending_text,
)
from bot.state import ChatState


async def handle_start_or_retry(
    callback: CallbackQuery,
    client: IcloudpdClient,
    state: ChatState,
    allowed_chat_ids: frozenset[int],
) -> None:
    chat_id = callback.message.chat.id
    if chat_id not in allowed_chat_ids:
        await callback.answer()
        return

    triggered = await asyncio.to_thread(client.trigger_push)
    if not triggered:
        await callback.answer(push_not_pending_text(), show_alert=True)
        return

    state.start_awaiting_code(chat_id)
    status = await asyncio.to_thread(client.get_status)
    await callback.answer()
    await callback.message.answer(code_requested_text(status.current_user or ""))


async def handle_exit(
    callback: CallbackQuery, state: ChatState, allowed_chat_ids: frozenset[int]
) -> None:
    chat_id = callback.message.chat.id
    if chat_id not in allowed_chat_ids:
        await callback.answer()
        return

    state.stop_awaiting_code(chat_id)
    await callback.answer()
    await callback.message.answer(exited_text())


async def handle_message(
    message: Message,
    client: IcloudpdClient,
    state: ChatState,
    allowed_chat_ids: frozenset[int],
) -> None:
    chat_id = message.chat.id
    if chat_id not in allowed_chat_ids or not state.is_awaiting_code(chat_id):
        return

    code = (message.text or "").strip()
    submitted = await asyncio.to_thread(client.submit_code, code)
    if not submitted:
        state.stop_awaiting_code(chat_id)
        await message.answer(push_not_pending_text())
        return

    success, error = await asyncio.to_thread(wait_for_mfa_result, client)
    state.stop_awaiting_code(chat_id)
    if success:
        status = await asyncio.to_thread(client.get_status)
        await message.answer(code_accepted_success_text(status.current_user or ""))
    else:
        await message.answer(
            code_failed_text(error or "Verification failed"),
            reply_markup=code_failed_keyboard(),
        )


def build_router(
    client: IcloudpdClient, state: ChatState, allowed_chat_ids: frozenset[int]
) -> Router:
    router = Router()

    @router.callback_query(F.data.in_({"start_2fa", "retry_2fa"}))
    async def _start_or_retry(callback: CallbackQuery) -> None:
        await handle_start_or_retry(callback, client, state, allowed_chat_ids)

    @router.callback_query(F.data == "exit_2fa")
    async def _exit(callback: CallbackQuery) -> None:
        await handle_exit(callback, state, allowed_chat_ids)

    @router.message()
    async def _message(message: Message) -> None:
        await handle_message(message, client, state, allowed_chat_ids)

    return router
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_handlers.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add integrations/telegram-bot/bot/handlers.py integrations/telegram-bot/tests/test_handlers.py
git commit -m "feat(telegram-bot): add Telegram callback and message handlers"
```

---

## Task 12: `bot/notify_listener.py` — receive forwarded `session_expired` events

**Files:**
- Create: `integrations/telegram-bot/bot/notify_listener.py`
- Test: `integrations/telegram-bot/tests/test_notify_listener.py`

- [ ] **Step 1: Write the failing tests**

Create `integrations/telegram-bot/tests/test_notify_listener.py`:

```python
from typing import Any

import pytest

from bot.notify_listener import build_notify_app

pytest_plugins = "aiohttp.pytest_plugin"


@pytest.mark.asyncio
async def test_session_expired_event_invokes_handler(aiohttp_client: Any) -> None:
    received: list[dict[str, Any]] = []

    async def on_session_expired(event: dict[str, Any]) -> None:
        received.append(event)

    app = build_notify_app(on_session_expired)
    client = await aiohttp_client(app)

    response = await client.post(
        "/notify",
        json={
            "event_type": "session_expired",
            "timestamp": "2026-07-15T00:00:00+00:00",
            "username": "jdoe@icloud.com",
            "message": "2FA expired",
            "data": {},
        },
    )

    assert response.status == 204
    assert received == [
        {
            "event_type": "session_expired",
            "timestamp": "2026-07-15T00:00:00+00:00",
            "username": "jdoe@icloud.com",
            "message": "2FA expired",
            "data": {},
        }
    ]


@pytest.mark.asyncio
async def test_unhandled_event_type_does_not_invoke_handler(aiohttp_client: Any) -> None:
    received: list[dict[str, Any]] = []

    async def on_session_expired(event: dict[str, Any]) -> None:
        received.append(event)

    app = build_notify_app(on_session_expired)
    client = await aiohttp_client(app)

    response = await client.post(
        "/notify",
        json={
            "event_type": "deletion_sync_summary",
            "timestamp": "x",
            "username": "u",
            "message": "m",
            "data": {},
        },
    )

    assert response.status == 204
    assert received == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_notify_listener.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.notify_listener'`.

- [ ] **Step 3: Write the implementation**

Create `integrations/telegram-bot/bot/notify_listener.py`:

```python
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiohttp import web

logger = logging.getLogger(__name__)

NotifyHandler = Callable[[dict[str, Any]], Awaitable[None]]


def build_notify_app(on_session_expired: NotifyHandler) -> web.Application:
    app = web.Application()

    async def handle_notify(request: web.Request) -> web.Response:
        event = await request.json()
        if event.get("event_type") == "session_expired":
            await on_session_expired(event)
        else:
            logger.debug("Ignoring unhandled event_type=%s", event.get("event_type"))
        return web.Response(status=204)

    app.router.add_post("/notify", handle_notify)
    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_notify_listener.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full sidecar suite**

Run: `pytest -v`
Expected: PASS, all tests from Tasks 6-12 (26 tests total).

- [ ] **Step 6: Commit**

```bash
git add integrations/telegram-bot/bot/notify_listener.py integrations/telegram-bot/tests/test_notify_listener.py
git commit -m "feat(telegram-bot): add notify-forwarding HTTP listener"
```

---

## Task 13: Wire it together — `bot/main.py`, the notification script, Docker, docs

This task has no new automated tests: `main.py` is thin process wiring (loads config, starts the aiogram poller and the aiohttp listener together), consistent with how the rest of this codebase treats top-level orchestration (e.g. `base.py`'s `run_with_configs` isn't unit-tested either — it's exercised through the CLI/VCR integration tests instead). This wiring is exercised by the manual E2E checklist (Task 14), not CI, matching the "unsupported integration" scope from the design doc.

**Files:**
- Create: `integrations/telegram-bot/bot/main.py`
- Create: `integrations/telegram-bot/notification_script.py`
- Create: `integrations/telegram-bot/Dockerfile`
- Create: `integrations/telegram-bot/docker-compose.example.yml`
- Create: `integrations/telegram-bot/.env.example`
- Create: `integrations/telegram-bot/README.md`

- [ ] **Step 1: Write `bot/main.py`**

Create `integrations/telegram-bot/bot/main.py`:

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
from bot.messages import session_expired_text, start_2fa_keyboard
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

    notify_app = build_notify_app(on_session_expired)
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

- [ ] **Step 2: Write the notification-forwarding script**

Create `integrations/telegram-bot/notification_script.py`. This is what gets configured as icloudpd's `--notification-script` — it runs *inside the icloudpd container*, which already has `requests` installed (a core icloudpd dependency), so no image changes are needed there. It must stay fast: `notify()` in `src/icloudpd/notifications.py` enforces a ~10s subprocess timeout.

```python
#!/usr/bin/env python3
"""Forwards a notify() JSON event on stdin to the Telegram bot's /notify endpoint.

Best-effort: any failure here is swallowed so it never affects icloudpd's own
best-effort notify() semantics (see src/icloudpd/notifications.py). Must return
quickly - notify() enforces a ~10s subprocess timeout.
"""

import os
import sys

import requests

NOTIFY_URL = os.environ.get("TELEGRAM_BOT_NOTIFY_URL", "http://telegram-bot:8090/notify")


def main() -> int:
    payload = sys.stdin.read()
    try:
        requests.post(
            NOTIFY_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
    except requests.RequestException:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Make it executable**

Run: `chmod +x integrations/telegram-bot/notification_script.py`

- [ ] **Step 4: Write the Dockerfile**

Create `integrations/telegram-bot/Dockerfile`:

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml ./
COPY bot ./bot
RUN pip install --no-cache-dir --disable-pip-version-check .
EXPOSE 8090
ENTRYPOINT ["python", "-m", "bot.main"]
```

- [ ] **Step 5: Write the example compose file**

Create `integrations/telegram-bot/docker-compose.example.yml`:

```yaml
services:
  icloudpd:
    image: icloudpd/icloudpd:latest
    command:
      - "--mfa-provider"
      - "webui"
      - "--watch-with-interval"
      - "3600"
      - "--username"
      - "jdoe@icloud.com"
      - "--directory"
      - "/data"
      - "--notification-script"
      - "/usr/local/bin/notification_script.py"
    volumes:
      - ./data:/data
      - ./config:/home/icloudpd/.pyicloud
      - ./notification_script.py:/usr/local/bin/notification_script.py:ro
    environment:
      TELEGRAM_BOT_NOTIFY_URL: "http://telegram-bot:8090/notify"
    networks:
      - icloudpd-net

  telegram-bot:
    build: .
    environment:
      TELEGRAM_BOT_TOKEN: "${TELEGRAM_BOT_TOKEN}"
      TELEGRAM_ALLOWED_CHAT_IDS: "${TELEGRAM_ALLOWED_CHAT_IDS}"
      ICLOUDPD_BASE_URL: "http://icloudpd:8080"
    networks:
      - icloudpd-net

networks:
  icloudpd-net:
    driver: bridge
```

- [ ] **Step 6: Write the env template**

Create `integrations/telegram-bot/.env.example`:

```
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_CHAT_IDS=
```

- [ ] **Step 7: Write the README**

Create `integrations/telegram-bot/README.md`:

```markdown
# Telegram bot (unsupported)

Optional sidecar that gives icloudpd remote, button-driven interaction over
Telegram — starting with 2FA, expandable to other notification events later.

**No maintenance commitment.** This ships because it's useful to the
maintainer personally. If Telegram's API changes and breaks it, that's a
"fix it if there's time" problem, not a tracked bug. It is intentionally
excluded from the core test/release/CI surface — this directory has its own
`pyproject.toml` and is not referenced by the root project's `pyproject.toml`
or `scripts/test`.

## What it does

1. icloudpd fires a `session_expired` event through its normal
   `notification_script` hook (see `../../src/icloudpd/notifications.py`).
2. `notification_script.py` forwards that event, unmodified, to this bot's
   `/notify` endpoint and exits immediately.
3. The bot DMs every chat ID in `TELEGRAM_ALLOWED_CHAT_IDS` with a
   "Start 2FA" button. No push is sent to your phone yet.
4. Tapping the button calls icloudpd's `POST /trigger-push`, which is what
   actually triggers Apple's push to your trusted device, and puts that chat
   into code-expecting mode.
5. Paste the 6-digit code as a plain message (no `/` prefix). The bot submits
   it to icloudpd's `POST /code` and reports success or failure.
6. On failure you get "Try again" / "Exit" buttons — "Try again" re-triggers
   the push, "Exit" just stops the bot from treating your next message as a
   code (icloudpd itself keeps waiting either way, same as it always has with
   nobody watching the WebUI).

Requires icloudpd running with `--mfa-provider webui`. See
`docs/superpowers/specs/2026-07-15-telegram-2fa-sidecar-design.md` in the
repo root for the full design rationale.

## Running it

```bash
cp .env.example .env  # fill in TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_CHAT_IDS
docker compose -f docker-compose.example.yml up --build
```

## Testing

```bash
pip install -e '.[test]'
pytest
```

Unit tests run without any real Telegram or icloudpd connection — everything
network-facing is faked. For a real end-to-end pass against the live
Telegram API, see `E2E_CHECKLIST.md`.
```

- [ ] **Step 8: Commit**

```bash
git add integrations/telegram-bot/bot/main.py integrations/telegram-bot/notification_script.py integrations/telegram-bot/Dockerfile integrations/telegram-bot/docker-compose.example.yml integrations/telegram-bot/.env.example integrations/telegram-bot/README.md
git commit -m "feat(telegram-bot): wire up process entrypoint, notify script, Docker, docs"
```

---

## Task 14: Manual E2E pass against a real Telegram bot

Not automated, not CI. This is the "actually works" verification the whole project exists to satisfy before a release gets cut with this included. Run this on the workstation, using the spare bot token retrieved from vm101 (`~/homelab/icloudpd/.env`, `TELEGRAM_BOT_TOKEN`) and chat ID `488165044`.

**Files:**
- Create: `integrations/telegram-bot/E2E_CHECKLIST.md`
- Create (local only, gitignored, not committed): `integrations/telegram-bot/.env`

- [ ] **Step 1: Write the checklist**

Create `integrations/telegram-bot/E2E_CHECKLIST.md`:

```markdown
# Manual E2E checklist (run before cutting a release that includes this)

Not part of CI. Requires a real, otherwise-unused Telegram bot token and your
own Telegram chat ID.

1. `cp .env.example .env` and fill in `TELEGRAM_BOT_TOKEN` and
   `TELEGRAM_ALLOWED_CHAT_IDS` (your chat ID).
2. Run icloudpd against a fixture/account that will hit `requires_2fa`,
   with `--mfa-provider webui` and `--notification-script` pointed at
   `notification_script.py`. `tests/fixtures/test_2sa_required_notification_script`
   (root repo) shows the recorded-cassette shape used elsewhere in this repo
   if you want to avoid a real Apple account for this pass; a real, disposable
   test Apple ID also works if you'd rather exercise the real Apple API too.
3. `docker compose -f docker-compose.example.yml up --build`
4. Confirm the bot DMs you an informative message ("`<username>` needs 2FA")
   with a **Start 2FA** button, and that no push notification has arrived on
   your phone yet.
5. Tap **Start 2FA**. Confirm a push notification now arrives on your trusted
   device, and the bot replies asking for the code.
6. Type an incorrect 6-digit code as a plain message (no `/` prefix). Confirm
   the bot reports failure with **Try again** / **Exit** buttons, and that no
   second push fired automatically.
7. Tap **Try again**. Confirm a fresh push arrives, type the correct code as
   a plain message, and confirm the bot reports success.
8. Confirm icloudpd's own logs show authentication completed and the run
   proceeded.
9. Repeat steps 4-7 once using **Exit** instead of **Try again** after a
   failure, confirming the bot goes quiet and a later "Start 2FA" tap on the
   original message still works.

Record the outcome (pass/fail per step) in the PR description before merging.
```

- [ ] **Step 2: Set up local secrets (not committed)**

```bash
cp integrations/telegram-bot/.env.example integrations/telegram-bot/.env
```

Fill in `TELEGRAM_BOT_TOKEN` (from `ssh vm101 "grep TELEGRAM_BOT_TOKEN ~/homelab/icloudpd/.env"`) and `TELEGRAM_ALLOWED_CHAT_IDS=488165044`. Confirm `.env` is ignored:

Run: `git status --porcelain integrations/telegram-bot/.env`
Expected: no output (untracked and ignored, not "??").

- [ ] **Step 3: Run the checklist**

Follow `E2E_CHECKLIST.md` steps 1-9 by hand. Do not proceed to Task 15 until every step passes.

- [ ] **Step 4: Commit the checklist (not the `.env`)**

```bash
git add integrations/telegram-bot/E2E_CHECKLIST.md
git commit -m "docs(telegram-bot): add manual E2E checklist"
```

---

## Task 15: Final verification and cleanup

**Files:** none (verification only)

- [ ] **Step 1: Full root suite**

Run: `scripts/test`
Expected: PASS, including the new `tests/test_status.py`, `tests/test_authentication_webui.py`, `tests/test_server.py`.

- [ ] **Step 2: Root lint and type check**

Run: `python3 -m ruff check src tests && python3 -m mypy src`
Expected: PASS, no errors introduced by the `Status` rename or the new endpoints.

- [ ] **Step 3: Full sidecar suite**

Run (from `integrations/telegram-bot/`): `pytest -v`
Expected: PASS, all tests from Tasks 6-12.

- [ ] **Step 4: Confirm the console 2FA path is untouched**

Run: `python3 -m pytest tests/test_authentication.py -k test_password_prompt_2fa -v`
Expected: PASS — the default `--mfa-provider console` path (not exercised by anything in this plan) still works exactly as before.

- [ ] **Step 5: Review the diff against the design doc**

Read `docs/superpowers/specs/2026-07-15-telegram-2fa-sidecar-design.md` once more against `git diff master...feature/telegram-2fa-sidecar` and confirm every section (state machine, push deferral, bot flow, multi-account, network model, repo layout, testing) has a corresponding change. No open items are expected.

- [ ] **Step 6: Push the branch (only if instructed — do not push without asking)**

At this point the branch is ready for PR. Do not open a PR or push without explicit confirmation from the user.
