"""True end-to-end coverage of the --auth-only push scenario from
E2E_CHECKLIST.md step 9a: icloudpd's mfa_accepted/mfa_rejected push must
reach a chat awaiting a code even when it lands within milliseconds of the
code being submitted (the race that motivated pushing instead of polling,
issue #15). Drives the real Dispatcher, the real handlers, and the real
notify_listener HTTP app together against a fake Telegram Bot API
(MockedBot) - no bot token, no chat, no real icloudpd required.
"""

from __future__ import annotations

import asyncio
import datetime

import pytest
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from aiohttp.test_utils import TestClient, TestServer
from bot.app import build_application
from bot.config import BotConfig
from bot.mfa_waiter import MfaResultWaiter
from bot.state import ChatState

from tests.support.mocked_bot import MockedBot, queue_ok

CHAT_ID = 12345
USERNAME = "jdoe@icloud.com"


class FakeClient:
    def __init__(self) -> None:
        self.submit_code_calls: list[str] = []

    def trigger_push(self) -> str | None:
        return USERNAME

    def submit_code(self, code: str) -> bool:
        self.submit_code_calls.append(code)
        return True


def make_chat() -> Chat:
    return Chat(id=CHAT_ID, type="private")


def make_user() -> User:
    return User(id=CHAT_ID, is_bot=False, first_name="Test")


def make_reply_message() -> Message:
    return Message(message_id=42, date=datetime.datetime.now(), chat=make_chat(), text="reply")


def start_2fa_update(update_id: int) -> Update:
    callback_message = Message(message_id=1, date=datetime.datetime.now(), chat=make_chat())
    callback = CallbackQuery(
        id="cb1",
        from_user=make_user(),
        chat_instance="x",
        data="start_2fa",
        message=callback_message,
    )
    return Update(update_id=update_id, callback_query=callback)


def code_message_update(update_id: int, code: str) -> Update:
    message = Message(
        message_id=2,
        date=datetime.datetime.now(),
        chat=make_chat(),
        text=code,
        from_user=make_user(),
    )
    return Update(update_id=update_id, message=message)


async def build_test_app(bot: MockedBot) -> tuple:
    config = BotConfig(
        bot_token="42:TEST",
        allowed_chat_ids=frozenset({CHAT_ID}),
        icloudpd_base_url="http://icloudpd:2011",
    )
    client = FakeClient()
    state = ChatState()
    waiter = MfaResultWaiter()
    dispatcher, notify_app = build_application(bot, config, client, state, waiter)
    return dispatcher, notify_app


@pytest.mark.asyncio
async def test_auth_only_push_lands_while_code_is_being_awaited_accepted() -> None:
    bot = MockedBot()
    dispatcher, notify_app = await build_test_app(bot)

    # Tap "Start 2FA": bot acks the callback, then asks for a code.
    queue_ok(bot, AnswerCallbackQuery, result=True)
    queue_ok(bot, SendMessage, result=make_reply_message())
    await dispatcher.feed_update(bot, start_2fa_update(1))

    async with TestClient(TestServer(notify_app)) as notify_client:
        # Submit the code, then simulate icloudpd's push landing while
        # handle_message is still awaiting the result - the exact race from
        # issue #15 (a fast --auth-only run can push the result within
        # milliseconds of the code being accepted).
        queue_ok(bot, SendMessage, result=make_reply_message())
        message_task = asyncio.create_task(
            dispatcher.feed_update(bot, code_message_update(2, "123456"))
        )
        await asyncio.sleep(0.05)  # let handle_message register the waiter first

        response = await notify_client.post(
            "/notify",
            json={
                "event_type": "mfa_accepted",
                "timestamp": "2026-07-16T00:00:00+00:00",
                "username": USERNAME,
                "message": f"{USERNAME}'s two-factor authentication code was accepted.",
                "data": {},
            },
        )
        assert response.status == 204

        await asyncio.wait_for(message_task, timeout=2.0)

    sent_texts = [req.text for req in bot.session.requests if isinstance(req, SendMessage)]
    assert sent_texts == [
        f"Code requested for {USERNAME}. Paste the 6-digit code you received.",
        f"✅ Authenticated for {USERNAME}.",
    ]


@pytest.mark.asyncio
async def test_auth_only_push_lands_while_code_is_being_awaited_rejected() -> None:
    bot = MockedBot()
    dispatcher, notify_app = await build_test_app(bot)

    queue_ok(bot, AnswerCallbackQuery, result=True)
    queue_ok(bot, SendMessage, result=make_reply_message())
    await dispatcher.feed_update(bot, start_2fa_update(1))

    async with TestClient(TestServer(notify_app)) as notify_client:
        queue_ok(bot, SendMessage, result=make_reply_message())
        message_task = asyncio.create_task(
            dispatcher.feed_update(bot, code_message_update(2, "000000"))
        )
        await asyncio.sleep(0.05)

        response = await notify_client.post(
            "/notify",
            json={
                "event_type": "mfa_rejected",
                "timestamp": "2026-07-16T00:00:00+00:00",
                "username": USERNAME,
                "message": f"{USERNAME}'s two-factor authentication code was rejected: bad code",
                "data": {"error": "bad code"},
            },
        )
        assert response.status == 204

        await asyncio.wait_for(message_task, timeout=2.0)

    sent_texts = [req.text for req in bot.session.requests if isinstance(req, SendMessage)]
    assert sent_texts == [
        f"Code requested for {USERNAME}. Paste the 6-digit code you received.",
        "❌ bad code",
    ]
