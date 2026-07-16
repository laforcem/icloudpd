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

    app = build_notify_app(on_session_expired, on_session_expiring_soon, _noop, _noop)
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

    app = build_notify_app(on_session_expired, _noop, _noop, _noop)
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

    app = build_notify_app(on_session_expired, _noop, _noop, _noop)
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


@pytest.mark.asyncio
async def test_mfa_accepted_event_invokes_its_own_handler() -> None:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    async def on_mfa_accepted(event: dict[str, Any]) -> None:
        accepted.append(event)

    async def on_mfa_rejected(event: dict[str, Any]) -> None:
        rejected.append(event)

    app = build_notify_app(_noop, _noop, on_mfa_accepted, on_mfa_rejected)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/notify",
            json={
                "event_type": "mfa_accepted",
                "timestamp": "2026-07-16T00:00:00+00:00",
                "username": "jdoe@icloud.com",
                "message": "jdoe@icloud.com's two-factor authentication code was accepted.",
                "data": {},
            },
        )

        assert response.status == 204
    assert rejected == []
    assert len(accepted) == 1
    assert accepted[0]["event_type"] == "mfa_accepted"


@pytest.mark.asyncio
async def test_mfa_rejected_event_invokes_its_own_handler() -> None:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    async def on_mfa_accepted(event: dict[str, Any]) -> None:
        accepted.append(event)

    async def on_mfa_rejected(event: dict[str, Any]) -> None:
        rejected.append(event)

    app = build_notify_app(_noop, _noop, on_mfa_accepted, on_mfa_rejected)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/notify",
            json={
                "event_type": "mfa_rejected",
                "timestamp": "2026-07-16T00:00:00+00:00",
                "username": "jdoe@icloud.com",
                "message": "jdoe@icloud.com's two-factor authentication code was rejected: bad code",
                "data": {"error": "bad code"},
            },
        )

        assert response.status == 204
    assert accepted == []
    assert len(rejected) == 1
    assert rejected[0]["event_type"] == "mfa_rejected"
    assert rejected[0]["data"] == {"error": "bad code"}
