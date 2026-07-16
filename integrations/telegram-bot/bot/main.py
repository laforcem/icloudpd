from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiohttp import web

from bot.app import build_application
from bot.config import load_config
from bot.icloudpd_client import IcloudpdClient
from bot.mfa_waiter import MfaResultWaiter
from bot.state import ChatState

logger = logging.getLogger(__name__)


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()

    bot = Bot(token=config.bot_token)
    client = IcloudpdClient(config.icloudpd_base_url)
    state = ChatState()
    waiter = MfaResultWaiter()
    dispatcher, notify_app = build_application(bot, config, client, state, waiter)

    runner = web.AppRunner(notify_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.notify_listener_port)
    await site.start()
    logger.info("Notify listener on :%d, starting Telegram polling", config.notify_listener_port)

    try:
        await dispatcher.start_polling(bot)
    finally:
        await runner.cleanup()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
