from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests


class StaleBatchError(Exception):
    """The held batch changed since the user saw it (HTTP 409)."""

    def __init__(self, batch_token: str, keep_token: str = "") -> None:
        super().__init__(f"stale batch, current token {batch_token}")
        self.batch_token = batch_token
        self.keep_token = keep_token


class SyncingError(Exception):
    """icloudpd is mid-sync and cannot take the write right now (HTTP 503 syncing)."""


class ControlClient:
    """Client for icloudpd's authenticated control channel (/v1/...)."""

    def __init__(self, base_url: str, token: str, timeout: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._timeout = timeout

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        response = requests.request(
            method,
            f"{self._base_url}{path}",
            headers=self._headers,
            timeout=self._timeout,
            **kwargs,
        )
        if response.status_code == 409:
            body = response.json()
            raise StaleBatchError(
                str(body.get("batch_token", "")), str(body.get("keep_token", ""))
            )
        if response.status_code == 503 and _reason(response) == "syncing":
            raise SyncingError()
        return response

    def entries(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/v1/entries")
        response.raise_for_status()
        return list(response.json()["entries"])

    def page(self, key: str, page: int) -> dict[str, Any]:
        response = self._request("GET", f"/v1/entries/{quote(key, safe='')}/held?page={page}")
        response.raise_for_status()
        return dict(response.json())

    def thumbnail(self, key: str, record_name: str) -> bytes | None:
        response = self._request(
            "GET",
            f"/v1/entries/{quote(key, safe='')}/held/{quote(record_name, safe='')}/thumbnail",
        )
        if response.status_code in (404, 503):
            return None
        response.raise_for_status()
        return response.content

    def set_keep(self, key: str, record_name: str, keep: bool, token: str) -> dict[str, Any]:
        response = self._request(
            "POST",
            f"/v1/entries/{quote(key, safe='')}/held/{quote(record_name, safe='')}/keep",
            json={"keep": keep, "batch_token": token},
        )
        response.raise_for_status()
        return dict(response.json())

    def resolve(
        self, key: str, action: str, token: str, keep_token: str | None = None
    ) -> dict[str, Any]:
        """`keep_token` (the keep marks the user saw) is required for action "apply"."""
        payload: dict[str, Any] = {"action": action, "batch_token": token}
        if keep_token is not None:
            payload["keep_token"] = keep_token
        response = self._request(
            "POST", f"/v1/entries/{quote(key, safe='')}/resolve", json=payload
        )
        response.raise_for_status()
        return dict(response.json())


def _reason(response: requests.Response) -> str | None:
    try:
        return response.json().get("reason")
    except ValueError:
        return None
