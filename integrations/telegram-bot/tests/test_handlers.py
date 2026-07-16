import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import requests

from bot.handlers import handle_exit, handle_force_reauth, handle_message, handle_start_or_retry
from bot.mfa_waiter import MfaResultWaiter
from bot.state import ChatState


class FakeClient:
    def __init__(
        self,
        trigger_push_result: str | None = "jdoe@icloud.com",
        submit_code_result: bool = True,
    ) -> None:
        self.trigger_push_result = trigger_push_result
        self.submit_code_result = submit_code_result

    def trigger_push(self) -> str | None:
        return self.trigger_push_result

    def submit_code(self, code: str) -> bool:
        return self.submit_code_result


class SubmitCodeRaisesClient(FakeClient):
    def submit_code(self, code: str) -> bool:
        raise requests.exceptions.ConnectionError("Remote end closed connection")


class TriggerPushRaisesClient(FakeClient):
    def trigger_push(self) -> str | None:
        raise requests.exceptions.ConnectionError("Remote end closed connection")


def make_callback(chat_id: int, data: str) -> SimpleNamespace:
    return SimpleNamespace(
        data=data,
        message=SimpleNamespace(chat=SimpleNamespace(id=chat_id), answer=AsyncMock()),
        answer=AsyncMock(),
    )


def make_message(chat_id: int, text: str) -> SimpleNamespace:
    return SimpleNamespace(chat=SimpleNamespace(id=chat_id), text=text, answer=AsyncMock())


class ForceReauthClient(FakeClient):
    def __init__(self, force_reauth_result: bool = True, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.force_reauth_result = force_reauth_result
        self.force_reauth_calls: list[str] = []

    def force_reauth(self, username: str) -> bool:
        self.force_reauth_calls.append(username)
        return self.force_reauth_result


class ForceReauthRaisesClient(FakeClient):
    def force_reauth(self, username: str) -> bool:
        raise requests.exceptions.ConnectionError("Remote end closed connection")


@pytest.mark.asyncio
async def test_start_ignores_disallowed_chat() -> None:
    client = FakeClient()
    state = ChatState()
    callback = make_callback(chat_id=1, data="start_2fa")

    await handle_start_or_retry(callback, client, state, allowed_chat_ids=frozenset({2}))

    callback.answer.assert_awaited_once_with()
    callback.message.answer.assert_not_called()
    assert state.is_awaiting_code(1) is False


@pytest.mark.asyncio
async def test_start_triggers_push_and_awaits_code() -> None:
    client = FakeClient(trigger_push_result="jdoe@icloud.com")
    state = ChatState()
    callback = make_callback(chat_id=1, data="start_2fa")

    await handle_start_or_retry(callback, client, state, allowed_chat_ids=frozenset({1}))

    assert state.is_awaiting_code(1) is True
    callback.message.answer.assert_awaited_once()
    assert "jdoe@icloud.com" in callback.message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_start_alerts_when_nothing_pending() -> None:
    client = FakeClient(trigger_push_result=None)
    state = ChatState()
    callback = make_callback(chat_id=1, data="start_2fa")

    await handle_start_or_retry(callback, client, state, allowed_chat_ids=frozenset({1}))

    callback.answer.assert_awaited_once()
    assert state.is_awaiting_code(1) is False


@pytest.mark.asyncio
async def test_start_alerts_when_trigger_push_raises() -> None:
    client = TriggerPushRaisesClient()
    state = ChatState()
    callback = make_callback(chat_id=1, data="start_2fa")

    await handle_start_or_retry(callback, client, state, allowed_chat_ids=frozenset({1}))

    callback.answer.assert_awaited_once()
    callback.message.answer.assert_not_called()
    assert state.is_awaiting_code(1) is False


@pytest.mark.asyncio
async def test_exit_stops_awaiting_code() -> None:
    client = FakeClient()
    state = ChatState()
    state.start_awaiting_code(1)
    callback = make_callback(chat_id=1, data="exit_2fa")

    await handle_exit(callback, state, allowed_chat_ids=frozenset({1}))

    assert state.is_awaiting_code(1) is False
    callback.message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_message_ignored_when_not_awaiting_code() -> None:
    client = FakeClient()
    state = ChatState()
    waiter = MfaResultWaiter()
    message = make_message(chat_id=1, text="123456")

    await handle_message(message, client, state, waiter, allowed_chat_ids=frozenset({1}))

    message.answer.assert_not_called()


@pytest.mark.asyncio
async def test_message_reports_success() -> None:
    client = FakeClient(submit_code_result=True)
    state = ChatState()
    state.start_awaiting_code(1)
    waiter = MfaResultWaiter()
    message = make_message(chat_id=1, text="123456")

    async def submit_and_resolve() -> None:
        await asyncio.sleep(0)  # let handle_message call waiter.start() first
        waiter.resolve(success=True, error=None, username="jdoe@icloud.com")

    await asyncio.gather(
        handle_message(message, client, state, waiter, allowed_chat_ids=frozenset({1})),
        submit_and_resolve(),
    )

    message.answer.assert_awaited_once()
    assert "jdoe@icloud.com" in message.answer.await_args.args[0]
    assert state.is_awaiting_code(1) is False


@pytest.mark.asyncio
async def test_message_reports_failure_with_retry_buttons() -> None:
    client = FakeClient(submit_code_result=True)
    state = ChatState()
    state.start_awaiting_code(1)
    waiter = MfaResultWaiter()
    message = make_message(chat_id=1, text="000000")

    async def submit_and_resolve() -> None:
        await asyncio.sleep(0)
        waiter.resolve(
            success=False,
            error="Failed to verify two-factor authentication code",
            username="jdoe@icloud.com",
        )

    await asyncio.gather(
        handle_message(message, client, state, waiter, allowed_chat_ids=frozenset({1})),
        submit_and_resolve(),
    )

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.await_args
    assert "Failed to verify" in args[0]
    assert "reply_markup" in kwargs
    assert state.is_awaiting_code(1) is False


@pytest.mark.asyncio
async def test_message_reports_connection_lost_when_submit_raises() -> None:
    client = SubmitCodeRaisesClient()
    state = ChatState()
    state.start_awaiting_code(1)
    waiter = MfaResultWaiter()
    message = make_message(chat_id=1, text="123456")

    await handle_message(message, client, state, waiter, allowed_chat_ids=frozenset({1}))

    message.answer.assert_awaited_once()
    assert "connection" in message.answer.await_args.args[0].lower()
    assert state.is_awaiting_code(1) is False


@pytest.mark.asyncio
async def test_message_times_out_when_no_result_is_pushed() -> None:
    client = FakeClient(submit_code_result=True)
    state = ChatState()
    state.start_awaiting_code(1)
    waiter = MfaResultWaiter()
    message = make_message(chat_id=1, text="123456")

    await handle_message(
        message, client, state, waiter, allowed_chat_ids=frozenset({1}), result_timeout=0.05
    )

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.await_args
    assert "Timed out" in args[0]
    assert "reply_markup" in kwargs
    assert state.is_awaiting_code(1) is False


@pytest.mark.asyncio
async def test_force_reauth_ignores_disallowed_chat() -> None:
    client = ForceReauthClient()
    callback = make_callback(chat_id=1, data="force_reauth:jdoe@icloud.com")

    await handle_force_reauth(callback, client, allowed_chat_ids=frozenset({2}))

    callback.answer.assert_awaited_once_with()
    callback.message.answer.assert_not_called()
    assert client.force_reauth_calls == []


@pytest.mark.asyncio
async def test_force_reauth_calls_client_with_embedded_username() -> None:
    client = ForceReauthClient(force_reauth_result=True)
    callback = make_callback(chat_id=1, data="force_reauth:jdoe@icloud.com")

    await handle_force_reauth(callback, client, allowed_chat_ids=frozenset({1}))

    assert client.force_reauth_calls == ["jdoe@icloud.com"]
    callback.answer.assert_awaited_once()
    callback.message.answer.assert_awaited_once()
    assert "jdoe@icloud.com" in callback.message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_force_reauth_alerts_when_username_unknown() -> None:
    client = ForceReauthClient(force_reauth_result=False)
    callback = make_callback(chat_id=1, data="force_reauth:unknown@icloud.com")

    await handle_force_reauth(callback, client, allowed_chat_ids=frozenset({1}))

    callback.answer.assert_awaited_once()
    callback.message.answer.assert_not_called()


@pytest.mark.asyncio
async def test_force_reauth_alerts_on_connection_error() -> None:
    client = ForceReauthRaisesClient()
    callback = make_callback(chat_id=1, data="force_reauth:jdoe@icloud.com")

    await handle_force_reauth(callback, client, allowed_chat_ids=frozenset({1}))

    callback.answer.assert_awaited_once()
    callback.message.answer.assert_not_called()
