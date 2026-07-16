from __future__ import annotations

from typing import Any

import requests


class IcloudpdClient:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def trigger_push(self) -> str | None:
        response = requests.post(f"{self._base_url}/trigger-push", timeout=self._timeout)
        if response.status_code != 200:
            return None
        body: dict[str, Any] = response.json()
        return body.get("current_user")

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
