from __future__ import annotations

import asyncio
from typing import Any

from aiogram import Bot, Dispatcher
from aiohttp import web

from bot.config import BotConfig
from bot.handlers import build_router
from bot.icloudpd_client import IcloudpdClient
from bot.messages import (
    force_reauth_keyboard,
    library_mount_missing_text,
    library_mount_restored_text,
    manual_password_entry_text,
    retry_mount_keyboard,
    session_expired_text,
    session_expiring_soon_text,
    start_2fa_keyboard,
    webui_link_keyboard,
)
from bot.mfa_waiter import MfaResultWaiter
from bot.notify_listener import build_notify_app
from bot.review import ReviewService
from bot.state import ChatState


def build_application(
    bot: Bot,
    config: BotConfig,
    client: IcloudpdClient,
    state: ChatState,
    waiter: MfaResultWaiter,
    review: ReviewService | None = None,
) -> tuple[Dispatcher, web.Application]:
    dispatcher = Dispatcher()
    dispatcher.include_router(
        build_router(client, state, waiter, config.allowed_chat_ids, review)
    )

    async def on_session_expired(event: dict[str, Any]) -> None:
        text = session_expired_text(
            event.get("username", "unknown account"), event.get("message", "")
        )
        for chat_id in config.allowed_chat_ids:
            await bot.send_message(chat_id, text, reply_markup=start_2fa_keyboard())

    async def on_session_expiring_soon(event: dict[str, Any]) -> None:
        username = event.get("username", "unknown account")
        message = event.get("message", "")
        if await asyncio.to_thread(client.password_requires_manual_entry):
            text = manual_password_entry_text(username, message)
            keyboard = (
                webui_link_keyboard(config.webui_external_url)
                if config.webui_external_url
                else None
            )
            for chat_id in config.allowed_chat_ids:
                await bot.send_message(chat_id, text, reply_markup=keyboard)
        else:
            text = session_expiring_soon_text(username, message)
            for chat_id in config.allowed_chat_ids:
                await bot.send_message(
                    chat_id, text, reply_markup=force_reauth_keyboard(username)
                )

    async def on_mfa_accepted(event: dict[str, Any]) -> None:
        waiter.resolve(success=True, error=None, username=event.get("username"))

    async def on_mfa_rejected(event: dict[str, Any]) -> None:
        data = event.get("data", {})
        waiter.resolve(success=False, error=data.get("error"), username=event.get("username"))

    async def on_library_mount_missing(event: dict[str, Any]) -> None:
        text = library_mount_missing_text(
            event.get("username", "unknown account"), event.get("message", "")
        )
        for chat_id in config.allowed_chat_ids:
            await bot.send_message(chat_id, text, reply_markup=retry_mount_keyboard())

    async def on_library_mount_restored(event: dict[str, Any]) -> None:
        text = library_mount_restored_text(
            event.get("username", "unknown account"), event.get("message", "")
        )
        for chat_id in config.allowed_chat_ids:
            await bot.send_message(chat_id, text)

    async def on_threshold_tripped(event: dict[str, Any]) -> None:
        if review is not None:
            await review.on_tripped(event)

    notify_app = build_notify_app(
        on_session_expired,
        on_session_expiring_soon,
        on_mfa_accepted,
        on_mfa_rejected,
        on_library_mount_missing,
        on_library_mount_restored,
        on_threshold_tripped,
    )
    return dispatcher, notify_app
