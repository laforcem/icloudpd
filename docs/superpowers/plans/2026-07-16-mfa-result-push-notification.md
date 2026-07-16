# MFA Result Push Notification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix issue #15 (Telegram bot's 2FA-code wait times out even when icloudpd's own auth succeeds) by having icloudpd push the MFA success/failure result to the bot instead of the bot polling for it.

**Architecture:** icloudpd emits a new `mfa_result` event through its existing `--notification-script` mechanism (the same channel already used for `session_expired`/`session_expiring_soon`) at the exact two points where the outcome is known: right after `status_exchange` flips to `IDLE` (success) and right after it flips back to `AWAITING_MFA_TRIGGER` with an error (failure). The bot's `/notify` endpoint routes this event to a single shared `asyncio.Future` that `handle_message` awaits, replacing the polling loop in `wait_for_mfa_result` entirely. This closes the race identified during investigation: in `--auth-only` mode, the process exits within ~200ms of the status flipping to `IDLE`, and the bot's poll can land after the port is already closed — no amount of extra timeout budget fixes that, since a push doesn't depend on the port staying open for a subsequent poll.

While making this change, two incidental `get_status()` round-trips in the bot (`handlers.py:48`, `handlers.py:128`) are also folded away: `/trigger-push`'s response now includes `current_user` directly, and the `mfa_result` event includes `username`, so neither follow-up call is needed.

**Tech Stack:** Python 3.10+, Flask (icloudpd's status server), aiohttp + aiogram (bot), pytest / pytest-asyncio, mypy --strict, ruff.

---

## Context for the engineer

- `src/icloudpd/authentication.py` — `request_2fa_web()` is icloudpd's in-process loop that waits for the bot to trigger a push and submit a code, then calls `icloud.validate_2fa_code(code)`. On success it flips `status_exchange` to `IDLE`; on failure it flips back to `AWAITING_MFA_TRIGGER` with an error and loops.
- `src/icloudpd/base.py` — `core_single_run()` builds a `notificator` callable (a `functools.partial` closing over `logger`, `username`, `notification_script`) and passes it into `authenticator()`, which only uses it to announce "2FA is required." We're adding a second, similarly-built callable for the *result*.
- `src/icloudpd/notifications.py` — `notify(logger, script_path, event)` is the generic, already-existing delivery mechanism (runs `notification_script` as a subprocess with the event JSON on stdin). No changes needed here; `event_type` is just a string.
- `integrations/telegram-bot/notification_script.py` — forwards whatever JSON it receives on stdin, unmodified, to the bot's `/notify` endpoint. No changes needed here either.
- `integrations/telegram-bot/bot/notify_listener.py` — `build_notify_app()` wires event types to async handler callbacks; needs a new `mfa_result` route.
- `integrations/telegram-bot/bot/mfa_result.py` — the current polling implementation (`wait_for_mfa_result`). This file and its test (`tests/test_mfa_result.py`) are deleted; replaced by `bot/mfa_waiter.py`.
- `integrations/telegram-bot/bot/handlers.py` — `handle_message()` currently calls `wait_for_mfa_result` in a loop; `handle_start_or_retry()` currently calls `get_status()` after `trigger_push()` just to fetch a username for display.
- `integrations/telegram-bot/bot/icloudpd_client.py` — thin `requests`-based client; `trigger_push()` currently returns `bool`.
- `integrations/telegram-bot/bot/main.py` — wires everything together on a single `asyncio` event loop (`asyncio.run(run())`), so the aiohttp notify server and the aiogram dispatcher share one loop — an `asyncio.Future` created in one can safely be resolved from the other with no thread-safety concerns.

Run icloudpd's own tests with `.venv/bin/python -m pytest <path> -v` from `/home/malc/repos/icloudpd`. Run the bot's tests with `.venv/bin/pytest` (or the bot's own venv if it has one — check `integrations/telegram-bot/.venv`) from `/home/malc/repos/icloudpd/integrations/telegram-bot`. Full local repo checks: `scripts/lint`, `scripts/type_check` (mypy `--strict`), `scripts/test`.

---

### Task 1: icloudpd emits `mfa_result` on success

**Files:**
- Modify: `src/icloudpd/authentication.py`
- Modify: `src/icloudpd/base.py`
- Modify: `tests/test_authentication_webui.py`
- Modify: `tests/test_authentication.py`

- [ ] **Step 1: Write the failing test for the success path**

Add to `tests/test_authentication_webui.py`:

```python
def test_successful_code_notifies_mfa_result_success() -> None:
    status_exchange = StatusExchange()
    icloud = make_icloud([True])
    logger = setup_logger()
    notified: List[tuple] = []

    def notify_mfa_result(success: bool, error: str | None) -> None:
        notified.append((success, error))

    thread = threading.Thread(
        target=request_2fa_web,
        args=(icloud, logger, status_exchange, notify_mfa_result),
        daemon=True,
    )
    thread.start()

    wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)
    status_exchange.trigger_mfa()
    wait_for_status(status_exchange, Status.AWAITING_MFA_CODE)
    status_exchange.set_payload("123456")
    thread.join(timeout=2.0)

    assert status_exchange.get_status() == Status.IDLE
    assert notified == [(True, None)]
```

Also update the three existing tests in this file that call `request_2fa_web` positionally with 3 args, since the signature is gaining a required 4th parameter. Change:

```python
    thread = threading.Thread(
        target=request_2fa_web, args=(icloud, logger, status_exchange), daemon=True
    )
```

to (in all three occurrences: `test_does_not_trigger_push_until_asked`, `test_successful_code_after_explicit_trigger`, `test_failed_code_drops_back_to_awaiting_trigger`):

```python
    thread = threading.Thread(
        target=request_2fa_web,
        args=(icloud, logger, status_exchange, lambda success, error: None),
        daemon=True,
    )
```

Also update `tests/test_authentication.py`'s two direct `authenticator()` calls (`test_failed_auth` and `test_non_2fa`) since `authenticator()` is gaining a required parameter right after `notificator`. Change:

```python
                authenticator(
                    setup_logger(),
                    "com",
                    {"test": (constant("dummy"), dummy_password_writter)},
                    MFAProvider.CONSOLE,
                    StatusExchange(),
                    "bad_username",
                    lambda: None,
                    None,
                    cookie_dir,
                    "EC5646DE-9423-11E8-BF21-14109FE0B321",
                )
```

to:

```python
                authenticator(
                    setup_logger(),
                    "com",
                    {"test": (constant("dummy"), dummy_password_writter)},
                    MFAProvider.CONSOLE,
                    StatusExchange(),
                    "bad_username",
                    lambda: None,
                    lambda success, error: None,
                    None,
                    cookie_dir,
                    "EC5646DE-9423-11E8-BF21-14109FE0B321",
                )
```

(same insertion — `lambda success, error: None` right after `lambda: None` — for the `test_non_2fa` call, which has `"jdoe@gmail.com"` instead of `"bad_username"`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/malc/repos/icloudpd && .venv/bin/python -m pytest tests/test_authentication_webui.py tests/test_authentication.py -v`
Expected: FAIL — `request_2fa_web() takes 3 positional arguments but 4 were given` / `authenticator() takes ... positional arguments but 5 were given` (TypeError), since the production signatures don't accept the new argument yet.

- [ ] **Step 3: Add the `notify_mfa_result` parameter and success-path call**

In `src/icloudpd/authentication.py`, change the `request_2fa_web` signature:

```python
def request_2fa_web(
    icloud: PyiCloudService,
    logger: logging.Logger,
    status_exchange: StatusExchange,
    notify_mfa_result: Callable[[bool, str | None], None],
) -> None:
```

And add the success-path call right after the status flips to `IDLE`:

```python
        status_exchange.replace_status(Status.VALIDATING_MFA_CODE, Status.IDLE)  # done
        notify_mfa_result(True, None)
        logger.info(
```

Change the `authenticator()` signature to accept and forward it:

```python
def authenticator(
    logger: logging.Logger,
    domain: str,
    password_providers: Dict[str, Tuple[Callable[[str], str | None], Callable[[str, str], None]]],
    mfa_provider: MFAProvider,
    status_exchange: StatusExchange,
    username: str,
    notificator: Callable[[], None],
    notify_mfa_result: Callable[[bool, str | None], None],
    response_observer: Callable[[Mapping[str, Any]], None] | None = None,
    cookie_directory: str | None = None,
    client_id: str | None = None,
) -> PyiCloudService:
```

and change the call site inside it:

```python
        if mfa_provider == MFAProvider.WEBUI:
            request_2fa_web(icloud, logger, status_exchange, notify_mfa_result)
```

- [ ] **Step 4: Wire a real `notify_mfa_result` in `src/icloudpd/base.py`**

Add a new builder function near `notificator_builder` (around line 454):

```python
def mfa_result_notificator_builder(
    logger: logging.Logger,
    username: str,
    notification_script: str | None,
    success: bool,
    error: str | None,
) -> None:
    message = (
        f"{username}'s two-factor authentication code was accepted."
        if success
        else f"{username}'s two-factor authentication code was rejected: {error}"
    )
    event = notifications.build_event(
        event_type="mfa_result",
        username=username,
        message=message,
        data={"success": success, "error": error},
    )
    notifications.notify(logger, notification_script, event)
```

Where the existing `notificator` partial is built (around line 420), add the new partial right after it:

```python
            notificator = partial(
                notificator_builder,
                logger,
                user_config.username,
                str(user_config.notification_script) if user_config.notification_script else None,
            )

            notify_mfa_result = partial(
                mfa_result_notificator_builder,
                logger,
                user_config.username,
                str(user_config.notification_script) if user_config.notification_script else None,
            )
```

Thread it through `core_single_run`'s signature (around line 865-879), adding the parameter right after `notificator`:

```python
def core_single_run(
    logger: logging.Logger,
    status_exchange: StatusExchange,
    global_config: GlobalConfig,
    user_config: UserConfig,
    password_providers_dict: Dict[
        PasswordProvider, Tuple[Callable[[str], str | None], Callable[[str, str], None]]
    ],
    passer: Callable[[PhotoAsset], bool],
    downloader: Callable[
        [manifest.ManifestHandle | None, PyiCloudService, Counter, PhotoAsset], bool
    ],
    notificator: Callable[[], None],
    notify_mfa_result: Callable[[bool, str | None], None],
    lp_filename_generator: Callable[[str], str],
) -> int:
```

And update its call site (around line 429) to pass the new partial:

```python
            result = core_single_run(
                logger,
                status_exchange,
                global_config,
                user_config,
                password_providers_dict,
                passer,
                downloader,
                notificator,
                notify_mfa_result,
                lp_filename_generator,
            )
```

Finally, update the `authenticator(...)` call inside `core_single_run` (around line 894-908) to pass it through:

```python
            icloud = authenticator(
                logger,
                global_config.domain,
                {
                    provider.value: functions
                    for provider, functions in password_providers_dict.items()
                },
                global_config.mfa_provider,
                status_exchange,
                user_config.username,
                notificator,
                notify_mfa_result,
                partial(append_response, captured_responses),
                user_config.cookie_directory,
                os.environ.get("CLIENT_ID"),
            )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /home/malc/repos/icloudpd && .venv/bin/python -m pytest tests/test_authentication_webui.py tests/test_authentication.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 6: Commit**

```bash
cd /home/malc/repos/icloudpd
git add src/icloudpd/authentication.py src/icloudpd/base.py tests/test_authentication_webui.py tests/test_authentication.py
git commit -m "feat: emit mfa_result notification on successful 2FA validation"
```

---

### Task 2: icloudpd emits `mfa_result` on failure

**Files:**
- Modify: `src/icloudpd/authentication.py`
- Modify: `tests/test_authentication_webui.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_authentication_webui.py`:

```python
def test_failed_code_notifies_mfa_result_failure() -> None:
    status_exchange = StatusExchange()
    icloud = make_icloud([False, True])
    logger = setup_logger()
    notified: List[tuple] = []

    def notify_mfa_result(success: bool, error: str | None) -> None:
        notified.append((success, error))

    thread = threading.Thread(
        target=request_2fa_web,
        args=(icloud, logger, status_exchange, notify_mfa_result),
        daemon=True,
    )
    thread.start()

    wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)
    status_exchange.trigger_mfa()
    wait_for_status(status_exchange, Status.AWAITING_MFA_CODE)
    status_exchange.set_payload("000000")
    wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)

    assert notified == [(False, "Failed to verify two-factor authentication code")]

    status_exchange.trigger_mfa()
    wait_for_status(status_exchange, Status.AWAITING_MFA_CODE)
    status_exchange.set_payload("123456")
    thread.join(timeout=2.0)
    assert notified == [
        (False, "Failed to verify two-factor authentication code"),
        (True, None),
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/malc/repos/icloudpd && .venv/bin/python -m pytest tests/test_authentication_webui.py::test_failed_code_notifies_mfa_result_failure -v`
Expected: FAIL — `notified == []` (the failure path doesn't call `notify_mfa_result` yet)

- [ ] **Step 3: Add the failure-path call**

In `src/icloudpd/authentication.py`, inside `request_2fa_web`, change:

```python
        if not icloud.validate_2fa_code(code):
            if not status_exchange.set_error("Failed to verify two-factor authentication code"):
                raise PyiCloudFailedMFAException("Failed to change status of invalid code")
            # dropped back to AWAITING_MFA_TRIGGER; loop and wait for another explicit trigger
            continue
```

to:

```python
        if not icloud.validate_2fa_code(code):
            error = "Failed to verify two-factor authentication code"
            if not status_exchange.set_error(error):
                raise PyiCloudFailedMFAException("Failed to change status of invalid code")
            notify_mfa_result(False, error)
            # dropped back to AWAITING_MFA_TRIGGER; loop and wait for another explicit trigger
            continue
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /home/malc/repos/icloudpd && .venv/bin/python -m pytest tests/test_authentication_webui.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
cd /home/malc/repos/icloudpd
git add src/icloudpd/authentication.py tests/test_authentication_webui.py
git commit -m "feat: emit mfa_result notification on failed 2FA validation"
```

---

### Task 3: `/trigger-push` returns the username directly

**Files:**
- Modify: `src/icloudpd/server/__init__.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_server.py`, change `test_trigger_push_moves_awaiting_trigger_to_awaiting_code`:

```python
def test_trigger_push_moves_awaiting_trigger_to_awaiting_code() -> None:
    status_exchange = StatusExchange()
    status_exchange.replace_status(Status.IDLE, Status.AWAITING_MFA_TRIGGER)
    status_exchange.set_current_user("jdoe@icloud.com")
    client = make_client(status_exchange)

    response = client.post("/trigger-push")

    assert response.status_code == 200
    assert response.json == {"current_user": "jdoe@icloud.com"}
    assert status_exchange.get_status() == Status.AWAITING_MFA_CODE
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/malc/repos/icloudpd && .venv/bin/python -m pytest tests/test_server.py::test_trigger_push_moves_awaiting_trigger_to_awaiting_code -v`
Expected: FAIL — `assert 204 == 200`

- [ ] **Step 3: Update the route**

In `src/icloudpd/server/__init__.py`, change:

```python
    @app.route("/trigger-push", methods=["POST"])
    def trigger_push() -> Response:
        if _status_exchange.trigger_mfa():
            return make_response("", 204)
        return make_response("Not awaiting an MFA trigger", 409)
```

to:

```python
    @app.route("/trigger-push", methods=["POST"])
    def trigger_push() -> Response:
        if _status_exchange.trigger_mfa():
            return jsonify({"current_user": _status_exchange.get_current_user()})
        return make_response("Not awaiting an MFA trigger", 409)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /home/malc/repos/icloudpd && .venv/bin/python -m pytest tests/test_server.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
cd /home/malc/repos/icloudpd
git add src/icloudpd/server/__init__.py tests/test_server.py
git commit -m "feat: return current_user from POST /trigger-push"
```

---

### Task 4: Bot's `MfaResultWaiter`

**Files:**
- Create: `integrations/telegram-bot/bot/mfa_waiter.py`
- Create: `integrations/telegram-bot/tests/test_mfa_waiter.py`

- [ ] **Step 1: Write the failing test**

Create `integrations/telegram-bot/tests/test_mfa_waiter.py`:

```python
import asyncio

import pytest

from bot.mfa_waiter import MfaResultWaiter


async def test_resolve_delivers_result_to_waiting_future() -> None:
    waiter = MfaResultWaiter()
    future = waiter.start()

    waiter.resolve(success=True, error=None, username="jdoe@icloud.com")

    result = await asyncio.wait_for(future, timeout=1.0)
    assert result == (True, None, "jdoe@icloud.com")


async def test_resolve_with_failure_delivers_error() -> None:
    waiter = MfaResultWaiter()
    future = waiter.start()

    waiter.resolve(success=False, error="bad code", username="jdoe@icloud.com")

    result = await asyncio.wait_for(future, timeout=1.0)
    assert result == (False, "bad code", "jdoe@icloud.com")


async def test_resolve_without_a_pending_waiter_is_a_no_op() -> None:
    waiter = MfaResultWaiter()

    waiter.resolve(success=True, error=None, username="jdoe@icloud.com")  # must not raise


async def test_second_start_replaces_the_pending_future() -> None:
    waiter = MfaResultWaiter()
    first_future = waiter.start()
    second_future = waiter.start()

    waiter.resolve(success=True, error=None, username="jdoe@icloud.com")

    assert not first_future.done()
    result = await asyncio.wait_for(second_future, timeout=1.0)
    assert result == (True, None, "jdoe@icloud.com")


async def test_resolve_after_future_already_done_does_not_raise() -> None:
    waiter = MfaResultWaiter()
    future = waiter.start()
    waiter.resolve(success=True, error=None, username="jdoe@icloud.com")
    await asyncio.wait_for(future, timeout=1.0)

    waiter.resolve(success=False, error="late", username="jdoe@icloud.com")  # must not raise
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/malc/repos/icloudpd/integrations/telegram-bot && .venv/bin/pytest tests/test_mfa_waiter.py -v` (or `pytest tests/test_mfa_waiter.py -v` if using the bot's own environment — check for `integrations/telegram-bot/.venv` first)
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.mfa_waiter'`

- [ ] **Step 3: Implement `MfaResultWaiter`**

Create `integrations/telegram-bot/bot/mfa_waiter.py`:

```python
from __future__ import annotations

import asyncio


class MfaResultWaiter:
    """Bridges the server-pushed 'mfa_result' notify event to whichever
    handle_message call is currently waiting on it.

    icloudpd runs one account's MFA flow at a time (a single global
    StatusExchange), so a single pending slot is enough - there's no
    concurrent-flow case to disambiguate with correlation IDs.
    """

    def __init__(self) -> None:
        self._pending: asyncio.Future[tuple[bool, str | None, str | None]] | None = None

    def start(self) -> asyncio.Future[tuple[bool, str | None, str | None]]:
        future: asyncio.Future[tuple[bool, str | None, str | None]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending = future
        return future

    def resolve(self, success: bool, error: str | None, username: str | None) -> None:
        pending = self._pending
        if pending is not None and not pending.done():
            pending.set_result((success, error, username))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /home/malc/repos/icloudpd/integrations/telegram-bot && .venv/bin/pytest tests/test_mfa_waiter.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
cd /home/malc/repos/icloudpd
git add integrations/telegram-bot/bot/mfa_waiter.py integrations/telegram-bot/tests/test_mfa_waiter.py
git commit -m "feat: add MfaResultWaiter to bridge pushed MFA results to waiting handlers"
```

---

### Task 5: Route `mfa_result` events in `notify_listener.py`

**Files:**
- Modify: `integrations/telegram-bot/bot/notify_listener.py`
- Modify: `integrations/telegram-bot/tests/test_notify_listener.py`

- [ ] **Step 1: Write the failing test**

Add to `integrations/telegram-bot/tests/test_notify_listener.py`:

```python
@pytest.mark.asyncio
async def test_mfa_result_event_invokes_its_own_handler() -> None:
    received: list[dict[str, Any]] = []

    async def on_mfa_result(event: dict[str, Any]) -> None:
        received.append(event)

    app = build_notify_app(_noop, _noop, on_mfa_result)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/notify",
            json={
                "event_type": "mfa_result",
                "timestamp": "2026-07-16T00:00:00+00:00",
                "username": "jdoe@icloud.com",
                "message": "jdoe@icloud.com's two-factor authentication code was accepted.",
                "data": {"success": True, "error": None},
            },
        )

        assert response.status == 204
    assert len(received) == 1
    assert received[0]["event_type"] == "mfa_result"
    assert received[0]["data"] == {"success": True, "error": None}
```

Also update the three other `build_notify_app(...)` calls in this file (`test_session_expiring_soon_event_invokes_its_own_handler`, `test_session_expired_event_invokes_handler`, `test_unhandled_event_type_does_not_invoke_handler`) to pass a third argument, since the signature is gaining a required parameter. Each currently reads either `build_notify_app(on_session_expired, on_session_expiring_soon)` or `build_notify_app(on_session_expired, _noop)` — change both call shapes to append `, _noop` (or the relevant handler) as a third positional argument, e.g. `build_notify_app(on_session_expired, on_session_expiring_soon, _noop)` and `build_notify_app(on_session_expired, _noop, _noop)`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/malc/repos/icloudpd/integrations/telegram-bot && .venv/bin/pytest tests/test_notify_listener.py -v`
Expected: FAIL — `TypeError: build_notify_app() missing 1 required positional argument: 'on_mfa_result'` (for the existing calls before they're updated) and `TypeError: build_notify_app() takes 2 positional arguments but 3 were given` (for the new test, before the implementation is added) — apply Step 1's test-file changes together, then this step should show only the second kind of failure for the new test, and the others should already be fixed by the signature update in Step 1. Run the full file and confirm the only failure is the new test.

- [ ] **Step 3: Add the `mfa_result` route**

In `integrations/telegram-bot/bot/notify_listener.py`, change:

```python
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

to:

```python
def build_notify_app(
    on_session_expired: NotifyHandler,
    on_session_expiring_soon: NotifyHandler,
    on_mfa_result: NotifyHandler,
) -> web.Application:
    app = web.Application()

    async def handle_notify(request: web.Request) -> web.Response:
        event = await request.json()
        event_type = event.get("event_type")
        if event_type == "session_expired":
            await on_session_expired(event)
        elif event_type == "session_expiring_soon":
            await on_session_expiring_soon(event)
        elif event_type == "mfa_result":
            await on_mfa_result(event)
        else:
            logger.debug("Ignoring unhandled event_type=%s", event_type)
        return web.Response(status=204)

    app.router.add_post("/notify", handle_notify)
    return app
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/malc/repos/icloudpd/integrations/telegram-bot && .venv/bin/pytest tests/test_notify_listener.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
cd /home/malc/repos/icloudpd
git add integrations/telegram-bot/bot/notify_listener.py integrations/telegram-bot/tests/test_notify_listener.py
git commit -m "feat: route mfa_result notify events to a dedicated handler"
```

---

### Task 6: `IcloudpdClient.trigger_push()` returns the username

**Files:**
- Modify: `integrations/telegram-bot/bot/icloudpd_client.py`
- Modify: `integrations/telegram-bot/tests/test_icloudpd_client.py`

- [ ] **Step 1: Write the failing test**

In `integrations/telegram-bot/tests/test_icloudpd_client.py`, change:

```python
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
```

to:

```python
@responses.activate
def test_trigger_push_success() -> None:
    responses.add(
        responses.POST,
        "http://icloudpd:8080/trigger-push",
        json={"current_user": "jdoe@icloud.com"},
        status=200,
    )
    client = IcloudpdClient("http://icloudpd:8080")

    assert client.trigger_push() == "jdoe@icloud.com"


@responses.activate
def test_trigger_push_conflict() -> None:
    responses.add(responses.POST, "http://icloudpd:8080/trigger-push", status=409)
    client = IcloudpdClient("http://icloudpd:8080")

    assert client.trigger_push() is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/malc/repos/icloudpd/integrations/telegram-bot && .venv/bin/pytest tests/test_icloudpd_client.py -v`
Expected: FAIL — assertion on the return value (currently `bool`, test now expects `str | None`)

- [ ] **Step 3: Update the client**

In `integrations/telegram-bot/bot/icloudpd_client.py`, change:

```python
    def trigger_push(self) -> bool:
        response = requests.post(f"{self._base_url}/trigger-push", timeout=self._timeout)
        return response.status_code == 204
```

to:

```python
    def trigger_push(self) -> str | None:
        response = requests.post(f"{self._base_url}/trigger-push", timeout=self._timeout)
        if response.status_code != 200:
            return None
        body: dict[str, Any] = response.json()
        return body.get("current_user")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/malc/repos/icloudpd/integrations/telegram-bot && .venv/bin/pytest tests/test_icloudpd_client.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
cd /home/malc/repos/icloudpd
git add integrations/telegram-bot/bot/icloudpd_client.py integrations/telegram-bot/tests/test_icloudpd_client.py
git commit -m "feat: trigger_push() returns the username from the server's response"
```

---

### Task 7: `handle_start_or_retry` uses the username from `trigger_push()`

**Files:**
- Modify: `integrations/telegram-bot/bot/handlers.py`
- Modify: `integrations/telegram-bot/tests/test_handlers.py`

- [ ] **Step 1: Update the fakes and write the failing test**

In `integrations/telegram-bot/tests/test_handlers.py`, change `FakeClient` so `trigger_push` returns a username string (or `None`) instead of a bool, and remove the now-unneeded `GetStatusRaisesAfterTriggerClient` class along with `test_start_still_prompts_for_code_when_status_lookup_fails_after_trigger` (there's no longer a follow-up `get_status()` call after `trigger_push()` for `handle_start_or_retry` to fail on):

```python
class FakeClient:
    def __init__(
        self,
        trigger_push_result: str | None = "jdoe@icloud.com",
        submit_code_result: bool = True,
    ) -> None:
        self.trigger_push_result = trigger_push_result
        self.submit_code_result = submit_code_result

    def trigger_push(self) -> str | None:
        return self.trigger_push_result

    def submit_code(self, code: str) -> bool:
        return self.submit_code_result
```

(Note: `get_status` and `status_sequence` are removed from `FakeClient` entirely in this task — `handle_start_or_retry` no longer calls `get_status()`. `handle_message`'s tests, updated in Task 8, no longer need `get_status` either since success/failure now comes from the waiter, not a status lookup. Update `TriggerPushRaisesClient` to still subclass `FakeClient` correctly given the new constructor.)

Update `test_start_triggers_push_and_awaits_code` and `test_start_alerts_when_nothing_pending` for the new return type:

```python
async def test_start_triggers_push_and_awaits_code() -> None:
    client = FakeClient(trigger_push_result="jdoe@icloud.com")
    state = ChatState()
    callback = make_callback(chat_id=1, data="start_2fa")

    await handle_start_or_retry(callback, client, state, allowed_chat_ids=frozenset({1}))

    assert state.is_awaiting_code(1) is True
    callback.message.answer.assert_awaited_once()
    assert "jdoe@icloud.com" in callback.message.answer.await_args.args[0]


async def test_start_alerts_when_nothing_pending() -> None:
    client = FakeClient(trigger_push_result=None)
    state = ChatState()
    callback = make_callback(chat_id=1, data="start_2fa")

    await handle_start_or_retry(callback, client, state, allowed_chat_ids=frozenset({1}))

    callback.answer.assert_awaited_once()
    assert state.is_awaiting_code(1) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/malc/repos/icloudpd/integrations/telegram-bot && .venv/bin/pytest tests/test_handlers.py -v`
Expected: FAIL on the tests touched in Step 1 (return-type mismatch / missing username in message)

- [ ] **Step 3: Update `handle_start_or_retry`**

In `integrations/telegram-bot/bot/handlers.py`, change:

```python
    try:
        triggered = await asyncio.to_thread(client.trigger_push)
    except requests.exceptions.RequestException:
        await callback.answer(connection_lost_text(), show_alert=True)
        return

    if not triggered:
        await callback.answer(push_not_pending_text(), show_alert=True)
        return

    state.start_awaiting_code(chat_id)
    try:
        status = await asyncio.to_thread(client.get_status)
        username = status.current_user or ""
    except requests.exceptions.RequestException:
        # trigger_push() already succeeded - the real push is in flight - so
        # the user must still be told to expect a code even without a
        # personalized username.
        username = ""
    await callback.answer()
    await callback.message.answer(code_requested_text(username))
```

to:

```python
    try:
        username = await asyncio.to_thread(client.trigger_push)
    except requests.exceptions.RequestException:
        await callback.answer(connection_lost_text(), show_alert=True)
        return

    if username is None:
        await callback.answer(push_not_pending_text(), show_alert=True)
        return

    state.start_awaiting_code(chat_id)
    await callback.answer()
    await callback.message.answer(code_requested_text(username))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/malc/repos/icloudpd/integrations/telegram-bot && .venv/bin/pytest tests/test_handlers.py -v`
Expected: The tests touched in this task pass; tests for `handle_message` will still fail until Task 8 (expected - don't fix those here).

- [ ] **Step 5: Commit**

```bash
cd /home/malc/repos/icloudpd
git add integrations/telegram-bot/bot/handlers.py integrations/telegram-bot/tests/test_handlers.py
git commit -m "feat: use trigger_push's returned username instead of a follow-up get_status()"
```

---

### Task 8: `handle_message` awaits the pushed result instead of polling

**Files:**
- Modify: `integrations/telegram-bot/bot/handlers.py`
- Modify: `integrations/telegram-bot/tests/test_handlers.py`

- [ ] **Step 1: Update the fakes and write the failing tests**

In `integrations/telegram-bot/tests/test_handlers.py`, remove `ConnectionDropsAfterSuccessClient` and `test_message_still_reports_success_if_username_lookup_fails` (there's no longer a follow-up `get_status()` call in `handle_message` to lose the connection on). Update the remaining `handle_message` tests to drive the new waiter-based flow instead of `status_sequence`:

```python
async def test_message_reports_success() -> None:
    client = FakeClient(submit_code_result=True)
    state = ChatState()
    state.start_awaiting_code(1)
    waiter = MfaResultWaiter()
    message = make_message(chat_id=1, text="123456")

    async def submit_and_resolve() -> None:
        await asyncio.sleep(0)  # let handle_message call waiter.start() first
        waiter.resolve(success=True, error=None, username="jdoe@icloud.com")

    await asyncio.gather(
        handle_message(message, client, state, waiter, allowed_chat_ids=frozenset({1})),
        submit_and_resolve(),
    )

    message.answer.assert_awaited_once()
    assert "jdoe@icloud.com" in message.answer.await_args.args[0]
    assert state.is_awaiting_code(1) is False


async def test_message_reports_failure_with_retry_buttons() -> None:
    client = FakeClient(submit_code_result=True)
    state = ChatState()
    state.start_awaiting_code(1)
    waiter = MfaResultWaiter()
    message = make_message(chat_id=1, text="000000")

    async def submit_and_resolve() -> None:
        await asyncio.sleep(0)
        waiter.resolve(
            success=False,
            error="Failed to verify two-factor authentication code",
            username="jdoe@icloud.com",
        )

    await asyncio.gather(
        handle_message(message, client, state, waiter, allowed_chat_ids=frozenset({1})),
        submit_and_resolve(),
    )

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.await_args
    assert "Failed to verify" in args[0]
    assert "reply_markup" in kwargs
    assert state.is_awaiting_code(1) is False


async def test_message_reports_connection_lost_when_submit_raises() -> None:
    client = SubmitCodeRaisesClient()
    state = ChatState()
    state.start_awaiting_code(1)
    waiter = MfaResultWaiter()
    message = make_message(chat_id=1, text="123456")

    await handle_message(message, client, state, waiter, allowed_chat_ids=frozenset({1}))

    message.answer.assert_awaited_once()
    assert "connection" in message.answer.await_args.args[0].lower()
    assert state.is_awaiting_code(1) is False


async def test_message_times_out_when_no_result_is_pushed() -> None:
    client = FakeClient(submit_code_result=True)
    state = ChatState()
    state.start_awaiting_code(1)
    waiter = MfaResultWaiter()
    message = make_message(chat_id=1, text="123456")

    await handle_message(
        message, client, state, waiter, allowed_chat_ids=frozenset({1}), result_timeout=0.05
    )

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.await_args
    assert "Timed out" in args[0]
    assert "reply_markup" in kwargs
    assert state.is_awaiting_code(1) is False
```

Also update `test_message_ignored_when_not_awaiting_code` to construct and pass a `waiter` (it won't be used since the function returns early, but the signature requires it):

```python
async def test_message_ignored_when_not_awaiting_code() -> None:
    client = FakeClient()
    state = ChatState()
    waiter = MfaResultWaiter()
    message = make_message(chat_id=1, text="123456")

    await handle_message(message, client, state, waiter, allowed_chat_ids=frozenset({1}))

    message.answer.assert_not_called()
```

Add the imports at the top of the test file (`integrations/telegram-bot/tests/test_handlers.py` doesn't currently import `asyncio` - it's needed now for `asyncio.sleep`/`asyncio.gather` in the new tests):

```python
import asyncio

from bot.mfa_waiter import MfaResultWaiter
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/malc/repos/icloudpd/integrations/telegram-bot && .venv/bin/pytest tests/test_handlers.py -v`
Expected: FAIL — `handle_message() missing 1 required positional argument: 'waiter'` (and related) since the production signature doesn't accept `waiter`/`result_timeout` yet.

- [ ] **Step 3: Update `handle_message`**

In `integrations/telegram-bot/bot/handlers.py`, remove the `wait_for_mfa_result` import:

```python
from bot.mfa_result import wait_for_mfa_result
```

replace with:

```python
from bot.mfa_waiter import MfaResultWaiter
```

Change `handle_message`'s signature and body from:

```python
async def handle_message(
    message: Message,
    client: IcloudpdClient,
    state: ChatState,
    allowed_chat_ids: frozenset[int],
) -> None:
    chat_id = message.chat.id
    # Not atomic with the submit_code below: two messages in quick succession
    # from the same chat can both pass this check before either clears
    # awaiting-code state. Harmless in practice (single human, occasional
    # double-tap) but not a correctness guarantee against concurrent messages.
    if chat_id not in allowed_chat_ids or not state.is_awaiting_code(chat_id):
        return

    code = (message.text or "").strip()
    try:
        submitted = await asyncio.to_thread(client.submit_code, code)
    except requests.exceptions.RequestException:
        state.stop_awaiting_code(chat_id)
        await message.answer(connection_lost_text())
        return

    if not submitted:
        state.stop_awaiting_code(chat_id)
        await message.answer(push_not_pending_text())
        return

    success, error = await asyncio.to_thread(wait_for_mfa_result, client)
    state.stop_awaiting_code(chat_id)
    if success:
        try:
            status = await asyncio.to_thread(client.get_status)
            username = status.current_user or ""
        except requests.exceptions.RequestException:
            # We already know the code was accepted (wait_for_mfa_result
            # returned success); losing the connection just for this
            # username lookup shouldn't turn a success into an error.
            username = ""
        await message.answer(code_accepted_success_text(username))
    else:
        await message.answer(
            code_failed_text(error or "Verification failed"),
            reply_markup=code_failed_keyboard(),
        )
```

to:

```python
async def handle_message(
    message: Message,
    client: IcloudpdClient,
    state: ChatState,
    waiter: MfaResultWaiter,
    allowed_chat_ids: frozenset[int],
    result_timeout: float = 120.0,
) -> None:
    chat_id = message.chat.id
    # Not atomic with the submit_code below: two messages in quick succession
    # from the same chat can both pass this check before either clears
    # awaiting-code state. Harmless in practice (single human, occasional
    # double-tap) but not a correctness guarantee against concurrent messages.
    if chat_id not in allowed_chat_ids or not state.is_awaiting_code(chat_id):
        return

    code = (message.text or "").strip()

    # Start waiting before submitting the code: icloudpd's mfa_result push can
    # arrive within milliseconds of the code landing, so the waiter must exist
    # before submit_code() goes out, not after.
    future = waiter.start()

    try:
        submitted = await asyncio.to_thread(client.submit_code, code)
    except requests.exceptions.RequestException:
        state.stop_awaiting_code(chat_id)
        await message.answer(connection_lost_text())
        return

    if not submitted:
        state.stop_awaiting_code(chat_id)
        await message.answer(push_not_pending_text())
        return

    try:
        success, error, username = await asyncio.wait_for(future, timeout=result_timeout)
    except asyncio.TimeoutError:
        state.stop_awaiting_code(chat_id)
        await message.answer(
            code_failed_text("Timed out waiting for verification result"),
            reply_markup=code_failed_keyboard(),
        )
        return

    state.stop_awaiting_code(chat_id)
    if success:
        await message.answer(code_accepted_success_text(username or ""))
    else:
        await message.answer(
            code_failed_text(error or "Verification failed"),
            reply_markup=code_failed_keyboard(),
        )
```

Update the router wiring in the same file:

```python
def build_router(
    client: IcloudpdClient, state: ChatState, allowed_chat_ids: frozenset[int]
) -> Router:
    router = Router()
    ...
    @router.message()
    async def _message(message: Message) -> None:
        await handle_message(message, client, state, allowed_chat_ids)

    return router
```

to:

```python
def build_router(
    client: IcloudpdClient,
    state: ChatState,
    waiter: MfaResultWaiter,
    allowed_chat_ids: frozenset[int],
) -> Router:
    router = Router()
    ...
    @router.message()
    async def _message(message: Message) -> None:
        await handle_message(message, client, state, waiter, allowed_chat_ids)

    return router
```

(Keep the other handlers registered in `build_router` — `_start_or_retry`, `_exit`, `_force_reauth` — unchanged; only the `waiter` parameter and the `_message` closure's call are new.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/malc/repos/icloudpd/integrations/telegram-bot && .venv/bin/pytest tests/test_handlers.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
cd /home/malc/repos/icloudpd
git add integrations/telegram-bot/bot/handlers.py integrations/telegram-bot/tests/test_handlers.py
git commit -m "feat: handle_message awaits the pushed MFA result instead of polling"
```

---

### Task 9: Wire it all up in `main.py`, delete the old polling module

**Files:**
- Modify: `integrations/telegram-bot/bot/main.py`
- Delete: `integrations/telegram-bot/bot/mfa_result.py`
- Delete: `integrations/telegram-bot/tests/test_mfa_result.py`

- [ ] **Step 1: Update `main.py`**

In `integrations/telegram-bot/bot/main.py`, add the import:

```python
from bot.mfa_waiter import MfaResultWaiter
```

Change:

```python
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
```

to:

```python
    bot = Bot(token=config.bot_token)
    dispatcher = Dispatcher()
    client = IcloudpdClient(config.icloudpd_base_url)
    state = ChatState()
    waiter = MfaResultWaiter()
    dispatcher.include_router(build_router(client, state, waiter, config.allowed_chat_ids))

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

    async def on_mfa_result(event: dict[str, Any]) -> None:
        data = event.get("data", {})
        waiter.resolve(
            success=bool(data.get("success")),
            error=data.get("error"),
            username=event.get("username"),
        )

    notify_app = build_notify_app(on_session_expired, on_session_expiring_soon, on_mfa_result)
```

- [ ] **Step 2: Delete the obsolete polling module and its test**

```bash
cd /home/malc/repos/icloudpd
git rm integrations/telegram-bot/bot/mfa_result.py integrations/telegram-bot/tests/test_mfa_result.py
```

- [ ] **Step 3: Run the full bot test suite**

Run: `cd /home/malc/repos/icloudpd/integrations/telegram-bot && .venv/bin/pytest -v`
Expected: PASS (every test in the `integrations/telegram-bot` suite; there should be no remaining references to `mfa_result.py` or `wait_for_mfa_result` anywhere)

Run: `cd /home/malc/repos/icloudpd/integrations/telegram-bot && grep -rn "wait_for_mfa_result\|bot.mfa_result" bot tests` to confirm zero remaining references (the earlier `bot/mfa_result.py` module, not `bot/mfa_waiter.py`).
Expected: no output

- [ ] **Step 4: Commit**

```bash
cd /home/malc/repos/icloudpd
git add integrations/telegram-bot/bot/main.py
git commit -m "feat: wire MfaResultWaiter into main.py and remove the polling-based mfa_result module"
```

---

### Task 10: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run icloudpd's full test suite**

Run: `cd /home/malc/repos/icloudpd && .venv/bin/python -m pytest tests/ -x -q`
Expected: PASS

- [ ] **Step 2: Run icloudpd's lint and type checks**

Run: `cd /home/malc/repos/icloudpd && scripts/lint && scripts/type_check`
Expected: both PASS with no errors (mypy runs in `--strict` mode; every new function above has full type annotations, but double check `src/icloudpd/base.py` and `src/icloudpd/authentication.py`'s new/changed signatures against this)

- [ ] **Step 3: Run the bot's full test suite**

Run: `cd /home/malc/repos/icloudpd/integrations/telegram-bot && .venv/bin/pytest -v`
Expected: PASS

- [ ] **Step 4: Manually re-run the E2E reproduction from the original investigation**

This is the scenario that originally reproduced issue #15. Confirm it's fixed:

1. Ensure the bot container is up: `cd /home/malc/repos/icloudpd/integrations/telegram-bot/e2e-local && docker compose up --build -d`
2. Clear the session file to force a real 2FA challenge: `rm -f config-fresh/malcstarcliffnet.session`
3. Run: `cd /home/malc/repos/icloudpd && TELEGRAM_BOT_NOTIFY_URL=http://localhost:8090/notify .venv/bin/icloudpd --auth-only --mfa-provider webui --notification-script integrations/telegram-bot/notification_script.py --cookie-directory integrations/telegram-bot/e2e-local/config-fresh --username malc@starcliff.net --log-level debug`
4. Tap **Start 2FA** in Telegram, submit the real code.
5. Confirm the bot reports success promptly (not a timeout), even though icloudpd's `--auth-only` process exits immediately after.
6. Tear down: `cd /home/malc/repos/icloudpd/integrations/telegram-bot/e2e-local && docker compose down`

- [ ] **Step 5: Update the E2E checklist doc**

Add a step to `integrations/telegram-bot/E2E_CHECKLIST.md` (after the existing steps 4-9) noting that the bot must report success/failure promptly and specifically that this must be re-verified against `--auth-only` (not just a full download run), since that's the case that originally exposed the race in issue #15.
