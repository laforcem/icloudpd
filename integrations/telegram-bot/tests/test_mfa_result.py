import requests

from bot.icloudpd_client import MfaStatus
from bot.mfa_result import wait_for_mfa_result


class FakeClient:
    def __init__(self, statuses: list[MfaStatus]) -> None:
        self._statuses = statuses

    def get_status(self) -> MfaStatus:
        if len(self._statuses) > 1:
            return self._statuses.pop(0)
        return self._statuses[0]


class FlakyThenSuccessClient:
    """Raises a connection error a fixed number of times, then returns statuses normally."""

    def __init__(self, failures_before_success: int, statuses: list[MfaStatus]) -> None:
        self._failures_remaining = failures_before_success
        self._statuses = statuses

    def get_status(self) -> MfaStatus:
        if self._failures_remaining > 0:
            self._failures_remaining -= 1
            raise requests.exceptions.ConnectionError("Remote end closed connection")
        if len(self._statuses) > 1:
            return self._statuses.pop(0)
        return self._statuses[0]


class AlwaysFailsClient:
    def get_status(self) -> MfaStatus:
        raise requests.exceptions.ConnectionError("Remote end closed connection")


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


def test_survives_transient_connection_error_then_succeeds() -> None:
    # e.g. icloudpd's process exits right after auth completes (--auth-only),
    # or a brief network blip, between the code being validated and the bot's
    # next poll landing.
    client = FlakyThenSuccessClient(
        failures_before_success=2,
        statuses=[MfaStatus("IDLE", None, "jdoe@icloud.com")],
    )

    success, error = wait_for_mfa_result(client, poll_interval=0, sleep=lambda _s: None)

    assert success is True
    assert error is None


def test_times_out_if_connection_errors_never_resolve() -> None:
    client = AlwaysFailsClient()

    success, error = wait_for_mfa_result(client, poll_interval=0, timeout=0, sleep=lambda _s: None)

    assert success is False
    assert error == "Timed out waiting for verification result"
