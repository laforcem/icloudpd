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
