"""True end-to-end coverage of the proactive session-expiry paths
(E2E_CHECKLIST.md steps 10-14, issue #9): icloudpd's session_expired and
session_expiring_soon pushes must reach every allowed chat with the right
button, and tapping "Refresh session now" must actually trigger a
force-reauth and fall through cleanly for an unrecognized username. Drives
the real Dispatcher, the real handlers, and the real notify_listener HTTP
app together against a fake Telegram Bot API (MockedBot) - no bot token, no
chat, no real icloudpd required.
"""

from __future__ import annotations

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

CHAT_ID_A = 111
CHAT_ID_B = 222
USERNAME = "jdoe@icloud.com"


class FakeClient:
    def __init__(
        self, force_reauth_result: bool = True, manual_entry_required: bool = False
    ) -> None:
        self.force_reauth_result = force_reauth_result
        self.force_reauth_calls: list[str] = []
        self.manual_entry_required = manual_entry_required

    def trigger_push(self) -> str | None:
        return USERNAME

    def submit_code(self, code: str) -> bool:
        return True

    def force_reauth(self, username: str) -> bool:
        self.force_reauth_calls.append(username)
        return self.force_reauth_result

    def password_requires_manual_entry(self) -> bool:
        return self.manual_entry_required


def make_chat(chat_id: int) -> Chat:
    return Chat(id=chat_id, type="private")


def make_user(chat_id: int) -> User:
    return User(id=chat_id, is_bot=False, first_name="Test")


def make_reply_message() -> Message:
    return Message(
        message_id=42, date=datetime.datetime.now(), chat=make_chat(CHAT_ID_A), text="reply"
    )


def force_reauth_update(update_id: int, chat_id: int, username: str) -> Update:
    callback_message = Message(message_id=1, date=datetime.datetime.now(), chat=make_chat(chat_id))
    callback = CallbackQuery(
        id="cb1",
        from_user=make_user(chat_id),
        chat_instance="x",
        data=f"force_reauth:{username}",
        message=callback_message,
    )
    return Update(update_id=update_id, callback_query=callback)


def build_test_app(
    bot: MockedBot,
    client: FakeClient,
    allowed_chat_ids: frozenset[int],
    webui_external_url: str | None = None,
) -> tuple:
    config = BotConfig(
        bot_token="42:TEST",
        allowed_chat_ids=allowed_chat_ids,
        icloudpd_base_url="http://icloudpd:2011",
        webui_external_url=webui_external_url,
    )
    state = ChatState()
    waiter = MfaResultWaiter()
    return build_application(bot, config, client, state, waiter)


@pytest.mark.asyncio
async def test_session_expired_push_dms_every_allowed_chat_with_start_2fa_button() -> None:
    bot = MockedBot()
    client = FakeClient()
    dispatcher, notify_app = build_test_app(bot, client, frozenset({CHAT_ID_A, CHAT_ID_B}))

    async with TestClient(TestServer(notify_app)) as notify_client:
        queue_ok(bot, SendMessage, result=make_reply_message())
        queue_ok(bot, SendMessage, result=make_reply_message())
        response = await notify_client.post(
            "/notify",
            json={
                "event_type": "session_expired",
                "timestamp": "2026-07-16T00:00:00+00:00",
                "username": USERNAME,
                "message": f"{USERNAME}'s icloudpd session needs two-step authentication. "
                "Tap Start 2FA below to continue.",
                "data": {},
            },
        )
        assert response.status == 204

    sent = [req for req in bot.session.requests if isinstance(req, SendMessage)]
    assert {msg.chat_id for msg in sent} == {CHAT_ID_A, CHAT_ID_B}
    for msg in sent:
        assert msg.text == (
            f"\U0001f510 {USERNAME}: {USERNAME}'s icloudpd session needs two-step "
            "authentication. Tap Start 2FA below to continue."
        )
        assert msg.reply_markup is not None
        assert msg.reply_markup.inline_keyboard[0][0].text == "Start 2FA"
        assert msg.reply_markup.inline_keyboard[0][0].callback_data == "start_2fa"


@pytest.mark.asyncio
async def test_session_expiring_soon_push_then_refresh_tap_triggers_force_reauth() -> None:
    bot = MockedBot()
    client = FakeClient(force_reauth_result=True)
    dispatcher, notify_app = build_test_app(bot, client, frozenset({CHAT_ID_A}))

    async with TestClient(TestServer(notify_app)) as notify_client:
        queue_ok(bot, SendMessage, result=make_reply_message())
        response = await notify_client.post(
            "/notify",
            json={
                "event_type": "session_expiring_soon",
                "timestamp": "2026-07-16T00:00:00+00:00",
                "username": USERNAME,
                "message": "session expires in 3.0 day(s)",
                "data": {"days_remaining": 3.0},
            },
        )
        assert response.status == 204

    warning = next(req for req in bot.session.requests if isinstance(req, SendMessage))
    assert warning.text == (
        f"⏳ {USERNAME}: session expires in 3.0 day(s) "
        "Re-authenticate before it lapses to avoid a stalled run."
    )
    assert warning.reply_markup.inline_keyboard[0][0].text == "Refresh session now"
    assert warning.reply_markup.inline_keyboard[0][0].callback_data == f"force_reauth:{USERNAME}"

    # Tap "Refresh session now" on that warning.
    queue_ok(bot, AnswerCallbackQuery, result=True)
    queue_ok(bot, SendMessage, result=make_reply_message())
    await dispatcher.feed_update(bot, force_reauth_update(2, CHAT_ID_A, USERNAME))

    assert client.force_reauth_calls == [USERNAME]
    confirmation = [req for req in bot.session.requests if isinstance(req, SendMessage)][-1]
    assert confirmation.text == f"Refreshing session for {USERNAME}. This may take a few seconds."


@pytest.mark.asyncio
async def test_session_expiring_soon_with_webui_only_password_sends_text_and_link() -> None:
    bot = MockedBot()
    client = FakeClient(manual_entry_required=True)
    dispatcher, notify_app = build_test_app(
        bot, client, frozenset({CHAT_ID_A}), webui_external_url="http://vm101.lan:2011"
    )

    async with TestClient(TestServer(notify_app)) as notify_client:
        queue_ok(bot, SendMessage, result=make_reply_message())
        response = await notify_client.post(
            "/notify",
            json={
                "event_type": "session_expiring_soon",
                "timestamp": "2026-07-16T00:00:00+00:00",
                "username": USERNAME,
                "message": "session expires in 3.0 day(s)",
                "data": {"days_remaining": 3.0},
            },
        )
        assert response.status == 204

    warning = next(req for req in bot.session.requests if isinstance(req, SendMessage))
    assert warning.text == (
        f"⏳ {USERNAME}: session expires in 3.0 day(s) "
        "Re-enter your password in the web app to avoid a stalled run."
    )
    assert warning.reply_markup.inline_keyboard[0][0].text == "Open WebUI"
    assert warning.reply_markup.inline_keyboard[0][0].url == "http://vm101.lan:2011"


@pytest.mark.asyncio
async def test_session_expiring_soon_with_webui_only_password_and_no_external_url() -> None:
    bot = MockedBot()
    client = FakeClient(manual_entry_required=True)
    dispatcher, notify_app = build_test_app(bot, client, frozenset({CHAT_ID_A}))

    async with TestClient(TestServer(notify_app)) as notify_client:
        queue_ok(bot, SendMessage, result=make_reply_message())
        response = await notify_client.post(
            "/notify",
            json={
                "event_type": "session_expiring_soon",
                "timestamp": "2026-07-16T00:00:00+00:00",
                "username": USERNAME,
                "message": "session expires in 3.0 day(s)",
                "data": {"days_remaining": 3.0},
            },
        )
        assert response.status == 204

    warning = next(req for req in bot.session.requests if isinstance(req, SendMessage))
    assert warning.text == (
        f"⏳ {USERNAME}: session expires in 3.0 day(s) "
        "Re-enter your password in the web app to avoid a stalled run."
    )
    assert warning.reply_markup is None


@pytest.mark.asyncio
async def test_refresh_tap_for_unconfigured_username_alerts_without_crashing() -> None:
    bot = MockedBot()
    client = FakeClient(force_reauth_result=False)
    dispatcher, notify_app = build_test_app(bot, client, frozenset({CHAT_ID_A}))

    queue_ok(bot, AnswerCallbackQuery, result=True)
    await dispatcher.feed_update(bot, force_reauth_update(1, CHAT_ID_A, "unconfigured@icloud.com"))

    assert client.force_reauth_calls == ["unconfigured@icloud.com"]
    answer = next(req for req in bot.session.requests if isinstance(req, AnswerCallbackQuery))
    assert answer.text == "That account isn't configured on this icloudpd instance."
    assert answer.show_alert is True
