from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.notify_listener import build_notify_app


async def _noop(event: dict[str, Any]) -> None:
    pass


@pytest.mark.asyncio
async def test_session_expiring_soon_event_invokes_its_own_handler() -> None:
    expired: list[dict[str, Any]] = []
    expiring: list[dict[str, Any]] = []

    async def on_session_expired(event: dict[str, Any]) -> None:
        expired.append(event)

    async def on_session_expiring_soon(event: dict[str, Any]) -> None:
        expiring.append(event)

    app = build_notify_app(on_session_expired, on_session_expiring_soon)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/notify",
            json={
                "event_type": "session_expiring_soon",
                "timestamp": "2026-07-15T00:00:00+00:00",
                "username": "jdoe@icloud.com",
                "message": "session expires in 3.0 day(s)",
                "data": {"days_remaining": 3.0},
            },
        )

        assert response.status == 204
    assert expired == []
    assert len(expiring) == 1
    assert expiring[0]["event_type"] == "session_expiring_soon"


@pytest.mark.asyncio
async def test_session_expired_event_invokes_handler() -> None:
    received: list[dict[str, Any]] = []

    async def on_session_expired(event: dict[str, Any]) -> None:
        received.append(event)

    app = build_notify_app(on_session_expired, _noop)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/notify",
            json={
                "event_type": "session_expired",
                "timestamp": "2026-07-15T00:00:00+00:00",
                "username": "jdoe@icloud.com",
                "message": "2FA expired",
                "data": {},
            },
        )

        assert response.status == 204
    assert received == [
        {
            "event_type": "session_expired",
            "timestamp": "2026-07-15T00:00:00+00:00",
            "username": "jdoe@icloud.com",
            "message": "2FA expired",
            "data": {},
        }
    ]


@pytest.mark.asyncio
async def test_unhandled_event_type_does_not_invoke_handler() -> None:
    received: list[dict[str, Any]] = []

    async def on_session_expired(event: dict[str, Any]) -> None:
        received.append(event)

    app = build_notify_app(on_session_expired, _noop)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/notify",
            json={
                "event_type": "deletion_sync_summary",
                "timestamp": "x",
                "username": "u",
                "message": "m",
                "data": {},
            },
        )

        assert response.status == 204
    assert received == []
