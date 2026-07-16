"""In-process fake Telegram Bot API for tests, so handler/dispatcher code can
run for real without a bot token, a real chat, or any network call.

MockedSession/MockedBot are vendored (near-verbatim) from aiogram's own test
suite (aiogram/tests/mocked_bot.py, MIT licensed, same license as aiogram) -
aiogram uses this pattern to test its own framework, so it's already proven
against the exact Bot/Dispatcher internals this bot depends on.
https://github.com/aiogram/aiogram/blob/dev-3.x/tests/mocked_bot.py

queue_ok() is a small addition on top: MockedBot.add_result_for() queues
responses LIFO (last queued is consumed first), which is fine for aiogram's
own one-call-per-test style but awkward for a multi-step conversation like
ours. queue_ok() queues FIFO instead, so responses can be listed in the same
order the handler is expected to call them.
"""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncGenerator
from typing import Any, TypeVar

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.methods.base import Response, TelegramType
from aiogram.types import UNSET_PARSE_MODE, ResponseParameters, User

MethodResult = TypeVar("MethodResult")


class MockedSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.responses: deque[Response[Any]] = deque()
        self.requests: deque[TelegramMethod[Any]] = deque()
        self.closed = True

    def add_result(self, response: Response[TelegramType]) -> Response[TelegramType]:
        self.responses.append(response)
        return response

    def get_request(self) -> TelegramMethod[Any]:
        return self.requests.pop()

    async def close(self) -> None:
        self.closed = True

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = UNSET_PARSE_MODE,
    ) -> TelegramType:
        self.closed = False
        self.requests.append(method)
        response: Response[TelegramType] = self.responses.pop()
        self.check_response(
            bot=bot,
            method=method,
            status_code=response.error_code,
            content=response.model_dump_json(),
        )
        return response.result  # type: ignore[return-value]

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:  # pragma: no cover
        yield b""


class MockedBot(Bot):
    session: MockedSession  # type: ignore[assignment]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(kwargs.pop("token", "42:TEST"), session=MockedSession(), **kwargs)
        self._me = User(
            id=self.id,
            is_bot=True,
            first_name="FirstName",
            last_name="LastName",
            username="tbot",
            language_code="uk-UA",
        )

    def add_result_for(
        self,
        method: type[TelegramMethod[TelegramType]],
        ok: bool,
        result: TelegramType = None,  # type: ignore[assignment]
        description: str | None = None,
        error_code: int = 200,
        migrate_to_chat_id: int | None = None,
        retry_after: int | None = None,
    ) -> Response[TelegramType]:
        response = Response[method.__returning__](  # type: ignore[valid-type]
            ok=ok,
            result=result,
            description=description,
            error_code=error_code,
            parameters=ResponseParameters(
                migrate_to_chat_id=migrate_to_chat_id,
                retry_after=retry_after,
            ),
        )
        self.session.add_result(response)
        return response

    def get_request(self) -> TelegramMethod[Any]:
        return self.session.get_request()


def queue_ok(
    bot: MockedBot,
    method: type[TelegramMethod[MethodResult]],
    result: MethodResult,
) -> None:
    """Queue a canned OK response for the next call to `method`, FIFO across
    calls to this function (unlike MockedBot.add_result_for, which is LIFO)."""
    response = Response[method.__returning__](  # type: ignore[valid-type]
        ok=True, result=result, error_code=200
    )
    bot.session.responses.appendleft(response)
