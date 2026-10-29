from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiohttp import web

logger = logging.getLogger(__name__)

NotifyHandler = Callable[[dict[str, Any]], Awaitable[None]]


def build_notify_app(
    on_session_expired: NotifyHandler,
    on_session_expiring_soon: NotifyHandler,
    on_mfa_accepted: NotifyHandler,
    on_mfa_rejected: NotifyHandler,
    on_library_mount_missing: NotifyHandler,
    on_library_mount_restored: NotifyHandler,
    on_threshold_tripped: NotifyHandler,
) -> web.Application:
    app = web.Application()
    # Strong references: the event loop keeps only weak ones to running tasks.
    background: set[asyncio.Task[None]] = set()

    async def run_tripped(event: dict[str, Any]) -> None:
        try:
            await on_threshold_tripped(event)
        except Exception:
            logger.exception("Sending the deletion review failed")

    async def handle_notify(request: web.Request) -> web.Response:
        event = await request.json()
        event_type = event.get("event_type")
        if event_type == "session_expired":
            await on_session_expired(event)
        elif event_type == "session_expiring_soon":
            await on_session_expiring_soon(event)
        elif event_type == "mfa_accepted":
            await on_mfa_accepted(event)
        elif event_type == "mfa_rejected":
            await on_mfa_rejected(event)
        elif event_type == "library_mount_missing":
            await on_library_mount_missing(event)
        elif event_type == "library_mount_restored":
            await on_library_mount_restored(event)
        elif event_type == "deletion_sync_threshold_tripped":
            # Building the review fetches thumbnails and can take longer than the
            # forwarder's 5 s timeout, so answer first and send in the background.
            task = asyncio.create_task(run_tripped(event))
            background.add(task)
            task.add_done_callback(background.discard)
        else:
            logger.debug("Ignoring unhandled event_type=%s", event_type)
        return web.Response(status=204)

    app.router.add_post("/notify", handle_notify)
    return app
