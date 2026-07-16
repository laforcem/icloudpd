from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import handle_exit, handle_message, handle_start_or_retry
from bot.icloudpd_client import MfaStatus
from bot.state import ChatState


class FakeClient:
    def __init__(
        self,
        trigger_push_result: bool = True,
        submit_code_result: bool = True,
        status_sequence: list[MfaStatus] | None = None,
    ) -> None:
        self.trigger_push_result = trigger_push_result
        self.submit_code_result = submit_code_result
        self._status_sequence = status_sequence or [MfaStatus("IDLE", None, "jdoe@icloud.com")]

    def trigger_push(self) -> bool:
        return self.trigger_push_result

    def submit_code(self, code: str) -> bool:
        return self.submit_code_result

    def get_status(self) -> MfaStatus:
        if len(self._status_sequence) > 1:
            return self._status_sequence.pop(0)
        return self._status_sequence[0]


def make_callback(chat_id: int, data: str) -> SimpleNamespace:
    return SimpleNamespace(
        data=data,
        message=SimpleNamespace(chat=SimpleNamespace(id=chat_id), answer=AsyncMock()),
        answer=AsyncMock(),
    )


def make_message(chat_id: int, text: str) -> SimpleNamespace:
    return SimpleNamespace(chat=SimpleNamespace(id=chat_id), text=text, answer=AsyncMock())


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
    client = FakeClient(trigger_push_result=True)
    state = ChatState()
    callback = make_callback(chat_id=1, data="start_2fa")

    await handle_start_or_retry(callback, client, state, allowed_chat_ids=frozenset({1}))

    assert state.is_awaiting_code(1) is True
    callback.message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_alerts_when_nothing_pending() -> None:
    client = FakeClient(trigger_push_result=False)
    state = ChatState()
    callback = make_callback(chat_id=1, data="start_2fa")

    await handle_start_or_retry(callback, client, state, allowed_chat_ids=frozenset({1}))

    callback.answer.assert_awaited_once()
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
    message = make_message(chat_id=1, text="123456")

    await handle_message(message, client, state, allowed_chat_ids=frozenset({1}))

    message.answer.assert_not_called()


@pytest.mark.asyncio
async def test_message_reports_success() -> None:
    client = FakeClient(
        submit_code_result=True,
        status_sequence=[MfaStatus("IDLE", None, "jdoe@icloud.com")],
    )
    state = ChatState()
    state.start_awaiting_code(1)
    message = make_message(chat_id=1, text="123456")

    await handle_message(message, client, state, allowed_chat_ids=frozenset({1}))

    message.answer.assert_awaited_once()
    assert "jdoe@icloud.com" in message.answer.await_args.args[0]
    assert state.is_awaiting_code(1) is False


@pytest.mark.asyncio
async def test_message_reports_failure_with_retry_buttons() -> None:
    client = FakeClient(
        submit_code_result=True,
        status_sequence=[
            MfaStatus(
                "AWAITING_MFA_TRIGGER",
                "Failed to verify two-factor authentication code",
                "jdoe@icloud.com",
            )
        ],
    )
    state = ChatState()
    state.start_awaiting_code(1)
    message = make_message(chat_id=1, text="000000")

    await handle_message(message, client, state, allowed_chat_ids=frozenset({1}))

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.await_args
    assert "Failed to verify" in args[0]
    assert "reply_markup" in kwargs
    assert state.is_awaiting_code(1) is False
