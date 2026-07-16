from __future__ import annotations

import time
from typing import Callable, Protocol

import requests

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
        try:
            status = client.get_status()
        except requests.exceptions.RequestException:
            # Transient - e.g. a brief network blip, or icloudpd's webserver
            # not yet back up after a restart. Keep polling until the timeout.
            sleep(poll_interval)
            continue
        if status.status == "IDLE":
            return True, None
        if status.status == "AWAITING_MFA_TRIGGER" and status.error:
            return False, status.error
        sleep(poll_interval)
    return False, "Timed out waiting for verification result"
