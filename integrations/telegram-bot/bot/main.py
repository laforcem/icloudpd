from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, Dispatcher
from aiohttp import web

from bot.config import load_config
from bot.handlers import build_router
from bot.icloudpd_client import IcloudpdClient
from bot.messages import (
    force_reauth_keyboard,
    session_expired_text,
    session_expiring_soon_text,
    start_2fa_keyboard,
)
from bot.notify_listener import build_notify_app
from bot.state import ChatState

logger = logging.getLogger(__name__)


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()

    bot = Bot(token=config.bot_token)
    dispatcher = Dispatcher()
    client = IcloudpdClient(config.icloudpd_base_url)
    state = ChatState()
    dispatcher.include_router(build_router(client, state, config.allowed_chat_ids))

    async def on_session_expired(event: dict[str, Any]) -> None:
        text = session_expired_text(
            event.get("username", "unknown account"), event.get("message", "")
        )
        for chat_id in config.allowed_chat_ids:
            await bot.send_message(chat_id, text, reply_markup=start_2fa_keyboard())

    async def on_session_expiring_soon(event: dict[str, Any]) -> None:
        username = event.get("username", "unknown account")
        text = session_expiring_soon_text(username, event.get("message", ""))
        for chat_id in config.allowed_chat_ids:
            await bot.send_message(chat_id, text, reply_markup=force_reauth_keyboard(username))

    notify_app = build_notify_app(on_session_expired, on_session_expiring_soon)
    runner = web.AppRunner(notify_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.notify_listener_port)
    await site.start()
    logger.info(
        "Notify listener on :%d, starting Telegram polling", config.notify_listener_port
    )

    try:
        await dispatcher.start_polling(bot)
    finally:
        await runner.cleanup()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
