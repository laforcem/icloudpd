from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiohttp import web

logger = logging.getLogger(__name__)

NotifyHandler = Callable[[dict[str, Any]], Awaitable[None]]


def build_notify_app(
    on_session_expired: NotifyHandler,
    on_session_expiring_soon: NotifyHandler,
) -> web.Application:
    app = web.Application()

    async def handle_notify(request: web.Request) -> web.Response:
        event = await request.json()
        event_type = event.get("event_type")
        if event_type == "session_expired":
            await on_session_expired(event)
        elif event_type == "session_expiring_soon":
            await on_session_expiring_soon(event)
        else:
            logger.debug("Ignoring unhandled event_type=%s", event_type)
        return web.Response(status=204)

    app.router.add_post("/notify", handle_notify)
    return app
