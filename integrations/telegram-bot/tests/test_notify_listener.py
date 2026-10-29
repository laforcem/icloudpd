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

    app = build_notify_app(
        on_session_expired, on_session_expiring_soon, _noop, _noop, _noop, _noop, _noop
    )
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

    app = build_notify_app(on_session_expired, _noop, _noop, _noop, _noop, _noop, _noop)
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

    app = build_notify_app(on_session_expired, _noop, _noop, _noop, _noop, _noop, _noop)
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

    app = build_notify_app(_noop, _noop, on_mfa_accepted, on_mfa_rejected, _noop, _noop, _noop)
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

    app = build_notify_app(_noop, _noop, on_mfa_accepted, on_mfa_rejected, _noop, _noop, _noop)
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


async def _post_event(app: Any, event_type: str) -> int:
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/notify",
            json={
                "event_type": event_type,
                "timestamp": "2026-07-15T00:00:00+00:00",
                "username": "jdoe@icloud.com",
                "message": "library not mounted",
                "data": {"directory": "/data/jdoe"},
            },
        )
        return response.status


@pytest.mark.asyncio
async def test_library_mount_missing_event_invokes_its_own_handler() -> None:
    missing: list[dict[str, Any]] = []
    restored: list[dict[str, Any]] = []

    async def on_missing(event: dict[str, Any]) -> None:
        missing.append(event)

    async def on_restored(event: dict[str, Any]) -> None:
        restored.append(event)

    app = build_notify_app(_noop, _noop, _noop, _noop, on_missing, on_restored, _noop)

    assert await _post_event(app, "library_mount_missing") == 204
    assert [e["event_type"] for e in missing] == ["library_mount_missing"]
    assert restored == []


@pytest.mark.asyncio
async def test_library_mount_restored_event_invokes_its_own_handler() -> None:
    missing: list[dict[str, Any]] = []
    restored: list[dict[str, Any]] = []

    async def on_missing(event: dict[str, Any]) -> None:
        missing.append(event)

    async def on_restored(event: dict[str, Any]) -> None:
        restored.append(event)

    app = build_notify_app(_noop, _noop, _noop, _noop, on_missing, on_restored, _noop)

    assert await _post_event(app, "library_mount_restored") == 204
    assert [e["event_type"] for e in restored] == ["library_mount_restored"]
    assert missing == []


@pytest.mark.asyncio
async def test_threshold_tripped_event_invokes_its_own_handler() -> None:
    tripped: list[dict[str, Any]] = []

    async def on_tripped(event: dict[str, Any]) -> None:
        tripped.append(event)

    app = build_notify_app(_noop, _noop, _noop, _noop, _noop, _noop, on_tripped)

    assert await _post_event(app, "deletion_sync_threshold_tripped") == 204
    assert [e["event_type"] for e in tripped] == ["deletion_sync_threshold_tripped"]
    assert await _post_event(app, "deletion_sync_summary") == 204
    assert len(tripped) == 1


@pytest.mark.asyncio
async def test_threshold_tripped_returns_before_the_review_is_sent() -> None:
    import asyncio

    release = asyncio.Event()
    done: list[str] = []

    async def slow(event: dict[str, Any]) -> None:
        await release.wait()
        done.append(event["event_type"])

    app = build_notify_app(_noop, _noop, _noop, _noop, _noop, _noop, slow)

    # The 204 must not wait for the review message: icloudpd's forwarder gives up after 5 s.
    assert await asyncio.wait_for(_post_event(app, "deletion_sync_threshold_tripped"), 1) == 204
    assert done == []
    release.set()
    for _ in range(20):
        await asyncio.sleep(0)
    assert done == ["deletion_sync_threshold_tripped"]
