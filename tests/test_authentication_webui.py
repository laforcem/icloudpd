import threading
import time
from typing import List
from unittest import mock

from icloudpd.authentication import request_2fa_web
from icloudpd.logger import setup_logger
from icloudpd.status import Status, StatusExchange
from tests.helpers import wait_for_status


def make_icloud(validate_results: List[bool]) -> mock.Mock:
    icloud = mock.Mock()
    icloud.trigger_push_notification.return_value = True
    icloud.validate_2fa_code.side_effect = validate_results
    return icloud


def test_does_not_trigger_push_until_asked() -> None:
    status_exchange = StatusExchange()
    icloud = make_icloud([True])
    logger = setup_logger()

    thread = threading.Thread(
        target=request_2fa_web,
        args=(icloud, logger, status_exchange, lambda: None, lambda error: None),
        daemon=True,
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
        target=request_2fa_web,
        args=(icloud, logger, status_exchange, lambda: None, lambda error: None),
        daemon=True,
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
        target=request_2fa_web,
        args=(icloud, logger, status_exchange, lambda: None, lambda error: None),
        daemon=True,
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


def test_successful_code_notifies_mfa_accepted() -> None:
    status_exchange = StatusExchange()
    icloud = make_icloud([True])
    logger = setup_logger()
    accepted: List[None] = []
    rejected: List[str] = []

    def notify_mfa_accepted() -> None:
        accepted.append(None)

    def notify_mfa_rejected(error: str) -> None:
        rejected.append(error)

    thread = threading.Thread(
        target=request_2fa_web,
        args=(icloud, logger, status_exchange, notify_mfa_accepted, notify_mfa_rejected),
        daemon=True,
    )
    thread.start()

    wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)
    status_exchange.trigger_mfa()
    wait_for_status(status_exchange, Status.AWAITING_MFA_CODE)
    status_exchange.set_payload("123456")
    thread.join(timeout=2.0)

    assert status_exchange.get_status() == Status.IDLE
    assert accepted == [None]
    assert rejected == []


def test_failed_code_notifies_mfa_rejected() -> None:
    status_exchange = StatusExchange()
    icloud = make_icloud([False, True])
    logger = setup_logger()
    accepted: List[None] = []
    rejected: List[str] = []

    def notify_mfa_accepted() -> None:
        accepted.append(None)

    def notify_mfa_rejected(error: str) -> None:
        rejected.append(error)

    thread = threading.Thread(
        target=request_2fa_web,
        args=(icloud, logger, status_exchange, notify_mfa_accepted, notify_mfa_rejected),
        daemon=True,
    )
    thread.start()

    wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)
    status_exchange.trigger_mfa()
    wait_for_status(status_exchange, Status.AWAITING_MFA_CODE)
    status_exchange.set_payload("000000")
    wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)

    assert rejected == ["Failed to verify two-factor authentication code"]
    assert accepted == []

    status_exchange.trigger_mfa()
    wait_for_status(status_exchange, Status.AWAITING_MFA_CODE)
    status_exchange.set_payload("123456")
    thread.join(timeout=2.0)
    assert rejected == ["Failed to verify two-factor authentication code"]
    assert accepted == [None]


def test_failed_code_notifies_before_flipping_status_back() -> None:
    # notify_mfa_rejected() can be slow in production (a blocking subprocess +
    # network call, up to ~10s). If the status flip to AWAITING_MFA_TRIGGER
    # happened first, a fast retry could start before that stale failure
    # notification is delivered, and a single-slot waiter (see the bot's
    # MfaResultWaiter) would misattribute it to the new attempt. Pin the
    # ordering: notify_mfa_rejected() must be called while still
    # VALIDATING_MFA_CODE, before the status has flipped back.
    status_exchange = StatusExchange()
    icloud = make_icloud([False, True])
    logger = setup_logger()
    status_at_notify_time: List[Status] = []

    def notify_mfa_accepted() -> None:
        pass

    def notify_mfa_rejected(error: str) -> None:
        status_at_notify_time.append(status_exchange.get_status())

    thread = threading.Thread(
        target=request_2fa_web,
        args=(icloud, logger, status_exchange, notify_mfa_accepted, notify_mfa_rejected),
        daemon=True,
    )
    thread.start()

    wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)
    status_exchange.trigger_mfa()
    wait_for_status(status_exchange, Status.AWAITING_MFA_CODE)
    status_exchange.set_payload("000000")
    wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)

    assert status_at_notify_time == [Status.VALIDATING_MFA_CODE]

    status_exchange.trigger_mfa()
    wait_for_status(status_exchange, Status.AWAITING_MFA_CODE)
    status_exchange.set_payload("123456")
    thread.join(timeout=2.0)


def _run_thread(icloud: mock.Mock, status_exchange: StatusExchange, **kwargs: object) -> threading.Thread:
    errors: List[str] = []

    def target() -> None:
        try:
            request_2fa_web(
                icloud,
                setup_logger(),
                status_exchange,
                lambda: None,
                errors.append,
                **kwargs,  # type: ignore[arg-type]
            )
        except Exception as ex:
            errors.append(f"EXC:{type(ex).__name__}")

    thread = threading.Thread(target=target, daemon=True)
    thread.errors = errors  # type: ignore[attr-defined]
    thread.start()
    return thread


def test_failed_push_relogs_in_and_retries_once() -> None:
    status_exchange = StatusExchange()
    icloud = make_icloud([True])
    icloud.trigger_push_notification.side_effect = [False, True]
    relogin = mock.Mock()

    thread = _run_thread(icloud, status_exchange, relogin=relogin)
    wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)
    status_exchange.trigger_mfa()
    wait_for_status(status_exchange, Status.AWAITING_MFA_CODE)
    time.sleep(0.05)

    relogin.assert_called_once()
    assert icloud.trigger_push_notification.call_count == 2
    assert status_exchange.get_status() == Status.AWAITING_MFA_CODE  # still waiting for a code

    status_exchange.set_payload("123456")
    thread.join(timeout=2.0)
    assert not thread.is_alive()


def test_push_failure_after_relogin_reports_and_returns_to_trigger() -> None:
    status_exchange = StatusExchange()
    icloud = make_icloud([True])
    icloud.trigger_push_notification.return_value = False

    # short timeout so the loop thread ends (and stops polling) before the test returns
    thread = _run_thread(icloud, status_exchange, relogin=mock.Mock(), timeout_seconds=1.0)
    wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)
    status_exchange.trigger_mfa()
    deadline = time.monotonic() + 2
    while not thread.errors and time.monotonic() < deadline:  # type: ignore[attr-defined]
        time.sleep(0.01)

    assert len(thread.errors) == 1  # type: ignore[attr-defined]
    assert "Start 2FA" in thread.errors[0]  # type: ignore[attr-defined]
    wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)
    assert status_exchange.get_error() is not None

    # a fresh trigger is accepted and the loop is not dead
    assert status_exchange.trigger_mfa() is True
    thread.join(timeout=3.0)
    assert not thread.is_alive()


def test_times_out_waiting_for_trigger_and_resets_status() -> None:
    status_exchange = StatusExchange()
    icloud = make_icloud([True])

    thread = _run_thread(icloud, status_exchange, timeout_seconds=0.2)
    thread.join(timeout=2.0)

    assert thread.errors == ["EXC:PyiCloudMFATimeoutException"]  # type: ignore[attr-defined]
    assert status_exchange.get_status() == Status.IDLE


def test_times_out_waiting_for_code_and_resets_status() -> None:
    status_exchange = StatusExchange()
    icloud = make_icloud([True])

    thread = _run_thread(icloud, status_exchange, timeout_seconds=0.3)
    wait_for_status(status_exchange, Status.AWAITING_MFA_TRIGGER)
    status_exchange.trigger_mfa()
    thread.join(timeout=2.0)

    assert thread.errors == ["EXC:PyiCloudMFATimeoutException"]  # type: ignore[attr-defined]
    assert status_exchange.get_status() == Status.IDLE
