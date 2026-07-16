from __future__ import annotations

import asyncio

import requests
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.icloudpd_client import IcloudpdClient
from bot.mfa_result import wait_for_mfa_result
from bot.messages import (
    code_accepted_success_text,
    code_failed_keyboard,
    code_failed_text,
    code_requested_text,
    connection_lost_text,
    exited_text,
    push_not_pending_text,
)
from bot.state import ChatState


async def handle_start_or_retry(
    callback: CallbackQuery,
    client: IcloudpdClient,
    state: ChatState,
    allowed_chat_ids: frozenset[int],
) -> None:
    chat_id = callback.message.chat.id
    if chat_id not in allowed_chat_ids:
        await callback.answer()
        return

    try:
        triggered = await asyncio.to_thread(client.trigger_push)
    except requests.exceptions.RequestException:
        await callback.answer(connection_lost_text(), show_alert=True)
        return

    if not triggered:
        await callback.answer(push_not_pending_text(), show_alert=True)
        return

    state.start_awaiting_code(chat_id)
    try:
        status = await asyncio.to_thread(client.get_status)
        username = status.current_user or ""
    except requests.exceptions.RequestException:
        # trigger_push() already succeeded - the real push is in flight - so
        # the user must still be told to expect a code even without a
        # personalized username.
        username = ""
    await callback.answer()
    await callback.message.answer(code_requested_text(username))


async def handle_exit(
    callback: CallbackQuery, state: ChatState, allowed_chat_ids: frozenset[int]
) -> None:
    chat_id = callback.message.chat.id
    if chat_id not in allowed_chat_ids:
        await callback.answer()
        return

    state.stop_awaiting_code(chat_id)
    await callback.answer()
    await callback.message.answer(exited_text())


async def handle_message(
    message: Message,
    client: IcloudpdClient,
    state: ChatState,
    allowed_chat_ids: frozenset[int],
) -> None:
    chat_id = message.chat.id
    # Not atomic with the submit_code below: two messages in quick succession
    # from the same chat can both pass this check before either clears
    # awaiting-code state. Harmless in practice (single human, occasional
    # double-tap) but not a correctness guarantee against concurrent messages.
    if chat_id not in allowed_chat_ids or not state.is_awaiting_code(chat_id):
        return

    code = (message.text or "").strip()
    try:
        submitted = await asyncio.to_thread(client.submit_code, code)
    except requests.exceptions.RequestException:
        state.stop_awaiting_code(chat_id)
        await message.answer(connection_lost_text())
        return

    if not submitted:
        state.stop_awaiting_code(chat_id)
        await message.answer(push_not_pending_text())
        return

    success, error = await asyncio.to_thread(wait_for_mfa_result, client)
    state.stop_awaiting_code(chat_id)
    if success:
        try:
            status = await asyncio.to_thread(client.get_status)
            username = status.current_user or ""
        except requests.exceptions.RequestException:
            # We already know the code was accepted (wait_for_mfa_result
            # returned success); losing the connection just for this
            # username lookup shouldn't turn a success into an error.
            username = ""
        await message.answer(code_accepted_success_text(username))
    else:
        await message.answer(
            code_failed_text(error or "Verification failed"),
            reply_markup=code_failed_keyboard(),
        )


def build_router(
    client: IcloudpdClient, state: ChatState, allowed_chat_ids: frozenset[int]
) -> Router:
    router = Router()

    @router.callback_query(F.data.in_({"start_2fa", "retry_2fa"}))
    async def _start_or_retry(callback: CallbackQuery) -> None:
        await handle_start_or_retry(callback, client, state, allowed_chat_ids)

    @router.callback_query(F.data == "exit_2fa")
    async def _exit(callback: CallbackQuery) -> None:
        await handle_exit(callback, state, allowed_chat_ids)

    @router.message()
    async def _message(message: Message) -> None:
        await handle_message(message, client, state, allowed_chat_ids)

    return router
