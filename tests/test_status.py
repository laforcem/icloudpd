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
