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

    def force_reauth(self, username: str) -> bool:
        response = requests.post(
            f"{self._base_url}/force-reauth", data={"username": username}, timeout=self._timeout
        )
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
