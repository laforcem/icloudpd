import threading
import time
from typing import List, Tuple
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
        args=(icloud, logger, status_exchange, lambda success, error: None),
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
        args=(icloud, logger, status_exchange, lambda success, error: None),
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
        args=(icloud, logger, status_exchange, lambda success, error: None),
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


def test_successful_code_notifies_mfa_result_success() -> None:
    status_exchange = StatusExchange()
    icloud = make_icloud([True])
    logger = setup_logger()
    notified: List[Tuple[bool, str | None]] = []

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


def test_failed_code_notifies_mfa_result_failure() -> None:
    status_exchange = StatusExchange()
    icloud = make_icloud([False, True])
    logger = setup_logger()
    notified: List[Tuple[bool, str | None]] = []

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


def test_failed_code_notifies_before_flipping_status_back() -> None:
    # notify_mfa_result() can be slow in production (a blocking subprocess +
    # network call, up to ~10s). If the status flip to AWAITING_MFA_TRIGGER
    # happened first, a fast retry could start before that stale failure
    # notification is delivered, and a single-slot waiter (see the bot's
    # MfaResultWaiter) would misattribute it to the new attempt. Pin the
    # ordering: notify_mfa_result() must be called while still
    # VALIDATING_MFA_CODE, before the status has flipped back.
    status_exchange = StatusExchange()
    icloud = make_icloud([False, True])
    logger = setup_logger()
    status_at_notify_time: List[Status] = []

    def notify_mfa_result(success: bool, error: str | None) -> None:
        status_at_notify_time.append(status_exchange.get_status())

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

    assert status_at_notify_time == [Status.VALIDATING_MFA_CODE]

    status_exchange.trigger_mfa()
    wait_for_status(status_exchange, Status.AWAITING_MFA_CODE)
    status_exchange.set_payload("123456")
    thread.join(timeout=2.0)
