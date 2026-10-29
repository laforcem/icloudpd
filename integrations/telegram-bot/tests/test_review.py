import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import requests
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import SendRichMessage
from aiogram.types import InlineKeyboardMarkup
from aiohttp.test_utils import TestClient, TestServer
from bot.app import build_application
from bot.config import BotConfig
from bot.control_client import StaleBatchError, SyncingError
from bot.mfa_waiter import MfaResultWaiter
from bot.placeholder import PLACEHOLDER_JPEG
from bot.review import REDRAW_FAILED_TEXT, ReviewService, pack, render, unpack
from bot.state import ChatState

CHAT = 111
KEY = "abcd1234"
TOKEN = "tok00001"
ENTRY = {
    "key": KEY,
    "username": "jdoe@icloud.com",
    "library": "PrimarySync",
    "held_count": 23,
    "tripped": True,
}
TRIPPED = {
    "event_type": "deletion_sync_threshold_tripped",
    "username": "jdoe@icloud.com",
    "data": {"library": "PrimarySync", "held_count": 23},
}
STALE_TEXT = "The batch changed, nothing was deleted. Here's the updated batch."


def make_page(
    page: int = 1,
    total: int = 23,
    kept: tuple[int, ...] = (),
    token: str = TOKEN,
    keep_token: str | None = None,
) -> dict[str, Any]:
    pages = -(-total // 10)
    numbers = range((page - 1) * 10 + 1, min(page * 10, total) + 1)
    return {
        "batch_token": token,
        "keep_token": keep_token if keep_token is not None else (f"k{len(kept)}" if kept else ""),
        "page": page,
        "pages": pages,
        "total": total,
        "kept_count": len(kept),
        "items": [
            {
                "number": n,
                "record_name": f"rec{n}",
                "filename": f"IMG_{n:04d}.JPG",
                "asset_date": "2026-03-04T10:00:00+00:00",
                "is_video": False,
                "keep": n in kept,
            }
            for n in numbers
        ],
    }


def thumbs_for(page: dict[str, Any], value: bytes | None = b"x") -> dict[str, bytes | None]:
    return {i["record_name"]: value for i in page["items"]}


class FakeControlClient:
    def __init__(self) -> None:
        self.entries_result: list[dict[str, Any]] = [ENTRY]
        self.pages: dict[int, dict[str, Any]] = {p: make_page(p) for p in (1, 2, 3)}
        self.thumb: bytes | None = b"\xff\xd8jpeg"
        self.calls: list[tuple[Any, ...]] = []
        self.raise_on: dict[str, Exception] = {}
        self.resolve_result = {"approved": 22, "rejected": 1}

    def entries(self) -> list[dict[str, Any]]:
        self.calls.append(("entries",))
        return self.entries_result

    def page(self, key: str, page: int) -> dict[str, Any]:
        self.calls.append(("page", key, page))
        return self.pages[page]

    def thumbnail(self, key: str, record_name: str) -> bytes | None:
        self.calls.append(("thumbnail", key, record_name))
        return self.thumb

    def set_keep(self, key: str, record_name: str, keep: bool, token: str) -> dict[str, Any]:
        self.calls.append(("set_keep", key, record_name, keep, token))
        if "set_keep" in self.raise_on:
            raise self.raise_on["set_keep"]
        return {"total": 23, "kept_count": 1}

    def resolve(
        self, key: str, action: str, token: str, keep_token: str | None = None
    ) -> dict[str, Any]:
        self.calls.append(("resolve", key, action, token, keep_token))
        if "resolve" in self.raise_on:
            raise self.raise_on["resolve"]
        return self.resolve_result


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self._next_id = 100

    async def send_rich_message(self, **kwargs: Any) -> SimpleNamespace:
        self._next_id += 1
        self.sent.append(kwargs)
        return SimpleNamespace(message_id=self._next_id)

    async def edit_message_text(self, **kwargs: Any) -> bool:
        self.edits.append(kwargs)
        return True


def block_texts(rich: Any) -> list[str]:
    return [str(b.text) for b in rich.blocks if b.type == "paragraph"]


def collage_captions(rich: Any) -> list[str]:
    for block in rich.blocks:
        if block.type == "collage":
            return [str(b.caption.text) for b in block.blocks]
    return []


def button_texts(markup: InlineKeyboardMarkup | None) -> list[list[str]]:
    assert markup is not None
    return [[b.text for b in row] for row in markup.inline_keyboard]


def callback_data(markup: InlineKeyboardMarkup) -> list[str]:
    return [b.callback_data or "" for row in markup.inline_keyboard for b in row]


def make_callback(data: str, chat_id: int = CHAT, message_id: int = 101) -> SimpleNamespace:
    return SimpleNamespace(
        data=data,
        message=SimpleNamespace(chat=SimpleNamespace(id=chat_id), message_id=message_id),
        answer=AsyncMock(),
    )


def make_message(chat_id: int = CHAT) -> SimpleNamespace:
    return SimpleNamespace(chat=SimpleNamespace(id=chat_id), answer=AsyncMock())


def make_service(
    allowed: frozenset[int] = frozenset({CHAT}),
) -> tuple[ReviewService, FakeBot, FakeControlClient]:
    bot = FakeBot()
    client = FakeControlClient()
    return ReviewService(bot, client, allowed), bot, client  # type: ignore[arg-type]


def test_pack_unpack_roundtrip() -> None:
    data = pack(KEY, "t", 2, 13, TOKEN, "ab12cd34")
    assert data == f"ds:{KEY}:t:2:13:{TOKEN}:ab12cd34"
    cb = unpack(data)
    assert (cb.key, cb.op, cb.page, cb.arg, cb.token, cb.keep_token) == (
        KEY,
        "t",
        2,
        13,
        TOKEN,
        "ab12cd34",
    )
    assert unpack(pack(KEY, "a", 1, 0, TOKEN, "")).keep_token == ""


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "ds:x",
        "xx:abcd1234:t:1:1:tok:",
        f"ds:{KEY}:z:1:1:{TOKEN}:",
        f"ds:{KEY}:t:a:1:{TOKEN}:",
        f"ds:{KEY}:t:1:1:{TOKEN}",
    ],
)
def test_unpack_rejects_garbage(bad: str) -> None:
    with pytest.raises(ValueError):
        unpack(bad)


def test_pack_rejects_unknown_op() -> None:
    with pytest.raises(ValueError):
        pack(KEY, "x", 1, 1, TOKEN)


def test_callback_data_max_length() -> None:
    assert len(pack("a" * 8, "t", 999, 9999, "b" * 8, "c" * 8).encode()) <= 64


def test_render_collage_numbers_and_keyboard() -> None:
    page = make_page(2, kept=(13,))
    rich, markup = render(ENTRY, page, thumbs_for(page))
    assert collage_captions(rich) == [str(n) for n in range(11, 21)]
    header = block_texts(rich)[0]
    assert header == "⚠️ 23 photos held for deletion (jdoe@icloud.com · PrimarySync)."
    rows = button_texts(markup)
    assert rows[0] == ["🗑 11", "🗑 12", "💾 13", "🗑 14", "🗑 15"]
    assert rows[1] == ["🗑 16", "🗑 17", "🗑 18", "🗑 19", "🗑 20"]
    assert rows[2] == ["◀ Prev", "Next ▶"]
    assert rows[3] == ["✅ Delete 22, keep 1", "❌ Keep all"]
    data = callback_data(markup)
    assert pack(KEY, "t", 2, 13, TOKEN, "k1") in data
    assert pack(KEY, "p", 2, 1, TOKEN, "k1") in data
    assert pack(KEY, "p", 2, 3, TOKEN, "k1") in data
    assert pack(KEY, "a", 2, 0, TOKEN, "k1") in data
    assert pack(KEY, "k", 2, 0, TOKEN, "k1") in data


def test_render_nav_omitted_at_ends() -> None:
    _, first = render(ENTRY, make_page(1), {})
    assert button_texts(first)[2] == ["Next ▶"]
    _, last = render(ENTRY, make_page(3), {})
    rows = button_texts(last)
    assert rows[0] == ["🗑 21", "🗑 22", "🗑 23"]
    assert rows[1] == ["◀ Prev"]


def test_render_text_fallback_when_no_thumbs() -> None:
    page = make_page(1)
    rich, _ = render(ENTRY, page, thumbs_for(page, None))
    assert collage_captions(rich) == []
    texts = block_texts(rich)
    assert "1. IMG_0001.JPG · 2026-03-04" in texts
    assert "Thumbnails return after icloudpd's next successful login." in texts


def test_render_placeholder_when_some_thumbs_missing() -> None:
    page = make_page(1)
    thumbs = thumbs_for(page)
    thumbs["rec3"] = None
    rich, _ = render(ENTRY, page, thumbs)
    assert len(collage_captions(rich)) == 10


def test_render_video_caption_marker() -> None:
    page = make_page(1)
    page["items"][1]["is_video"] = True
    rich, _ = render(ENTRY, page, thumbs_for(page))
    captions = collage_captions(rich)
    assert captions[0] == "1"
    assert captions[1] == "▶ 2"


def test_render_serialises_uploads_as_attach() -> None:
    page = make_page(1)
    rich, markup = render(ENTRY, page, thumbs_for(page))
    method = SendRichMessage(chat_id=CHAT, rich_message=rich, reply_markup=markup)
    bot = Bot("42:TEST")
    form = AiohttpSession().build_form_data(bot, method)
    names = [f[0]["name"] for f in form._fields]
    assert len([n for n in names if n not in ("chat_id", "rich_message", "reply_markup")]) == 10
    body = next(f[2] for f in form._fields if f[0]["name"] == "rich_message")
    assert body.count("attach://") == 10


async def test_tripped_sends_one_rich_message_per_allowed_chat() -> None:
    service, bot, client = make_service(allowed=frozenset({CHAT, 222}))
    client.entries_result = [{**ENTRY, "key": "other000", "library": "SharedSync-X"}, ENTRY]
    await service.on_tripped(TRIPPED)
    assert sorted(s["chat_id"] for s in bot.sent) == [CHAT, 222]
    assert ("page", KEY, 1) in client.calls
    assert not any(c[0] == "page" and c[1] == "other000" for c in client.calls)
    assert (CHAT, KEY) in service.last_message and (222, KEY) in service.last_message


async def test_tripped_unknown_entry_sends_nothing() -> None:
    service, bot, client = make_service()
    client.entries_result = []
    await service.on_tripped(TRIPPED)
    assert bot.sent == []


async def test_tripped_again_marks_previous_superseded() -> None:
    service, bot, _ = make_service()
    await service.on_tripped(TRIPPED)
    first_id = service.last_message[(CHAT, KEY)]
    await service.on_tripped(TRIPPED)
    assert len(bot.sent) == 2
    assert service.last_message[(CHAT, KEY)] != first_id
    edit = bot.edits[0]
    assert edit["chat_id"] == CHAT and edit["message_id"] == first_id
    assert block_texts(edit["rich_message"]) == ["Superseded, see the newer message."]
    assert edit.get("reply_markup") is None


async def test_toggle_calls_set_keep_and_edits() -> None:
    service, bot, client = make_service()
    cb = make_callback(pack(KEY, "t", 1, 3, TOKEN, ""))
    await service.on_callback(cb)
    assert ("set_keep", KEY, "rec3", True, TOKEN) in client.calls
    assert len(bot.edits) == 1
    assert bot.edits[0]["message_id"] == 101
    cb.answer.assert_awaited_once()


async def test_toggle_on_kept_item_unkeeps() -> None:
    service, _, client = make_service()
    client.pages[1] = make_page(1, kept=(3,), keep_token="kx")
    await service.on_callback(make_callback(pack(KEY, "t", 1, 3, TOKEN, "kx")))
    assert ("set_keep", KEY, "rec3", False, TOKEN) in client.calls


async def test_page_edits_with_new_thumbs() -> None:
    service, bot, client = make_service()
    await service.on_callback(make_callback(pack(KEY, "p", 1, 2, TOKEN, "")))
    assert ("page", KEY, 2) in client.calls
    assert sum(1 for c in client.calls if c[0] == "thumbnail") == 10
    assert collage_captions(bot.edits[0]["rich_message"])[0] == "11"
    assert bot.edits[0]["reply_markup"] is not None


async def test_toggle_reuses_thumbnails_already_fetched() -> None:
    service, _, client = make_service()
    await service._draw(CHAT, 101, KEY, 1)
    first = sum(1 for c in client.calls if c[0] == "thumbnail")
    await service.on_callback(make_callback(pack(KEY, "t", 1, 3, TOKEN, "")))
    assert first == 10
    assert sum(1 for c in client.calls if c[0] == "thumbnail") == first


def test_render_draws_the_number_on_each_tile() -> None:
    page = make_page(1)
    rich, _ = render(ENTRY, page, thumbs_for(page, PLACEHOLDER_JPEG))
    tiles = [b for b in rich.blocks if b.type == "collage"][0].blocks
    sent = [t.photo.media.data for t in tiles]
    assert all(data != PLACEHOLDER_JPEG for data in sent)
    assert len(set(sent)) == len(sent)  # numbered differently, so all differ


async def test_apply_edits_final_text_no_buttons() -> None:
    service, bot, client = make_service()
    await service.on_callback(make_callback(pack(KEY, "a", 1, 0, TOKEN, "")))
    assert ("resolve", KEY, "apply", TOKEN, "") in client.calls
    edit = bot.edits[0]
    assert block_texts(edit["rich_message"]) == [
        "22 will be deleted at the next sync. 1 kept, re-downloading."
    ]
    assert edit.get("reply_markup") is None


async def test_keep_all_final_text() -> None:
    service, bot, client = make_service()
    client.resolve_result = {"approved": 0, "rejected": 23}
    await service.on_callback(make_callback(pack(KEY, "k", 1, 0, TOKEN, "")))
    assert ("resolve", KEY, "keep_all", TOKEN, None) in client.calls
    assert block_texts(bot.edits[0]["rich_message"]) == [
        "Nothing deleted. 23 photos will re-download at the next sync."
    ]
    assert bot.edits[0].get("reply_markup") is None


@pytest.mark.parametrize("op,arg", [("t", 3), ("a", 0), ("k", 0)])
async def test_stale_token_redraws_and_answers(op: str, arg: int) -> None:
    service, bot, client = make_service()
    stale = StaleBatchError("new00000")
    client.raise_on = {"set_keep": stale, "resolve": stale}
    client.pages[1] = make_page(1, token="new00000")
    cb = make_callback(pack(KEY, op, 1, arg, TOKEN, ""))
    await service.on_callback(cb)
    cb.answer.assert_awaited_once()
    assert cb.answer.await_args.args[0] == STALE_TEXT
    assert len(bot.edits) == 1
    assert all(":new00000:" in d for d in callback_data(bot.edits[0]["reply_markup"]))


async def test_page_with_stale_token_redraws_and_answers() -> None:
    service, bot, client = make_service()
    client.pages[2] = make_page(2, token="new00000")
    cb = make_callback(pack(KEY, "p", 1, 2, TOKEN, ""))
    await service.on_callback(cb)
    assert cb.answer.await_args.args[0] == STALE_TEXT
    assert len(bot.edits) == 1


@pytest.mark.parametrize("op,arg", [("t", 3), ("a", 0), ("k", 0)])
async def test_syncing_answers_retry_text_changes_nothing(op: str, arg: int) -> None:
    service, bot, client = make_service()
    client.raise_on = {"set_keep": SyncingError(), "resolve": SyncingError()}
    cb = make_callback(pack(KEY, op, 1, arg, TOKEN, ""))
    await service.on_callback(cb)
    assert cb.answer.await_args.args[0] == "icloudpd is syncing, try again in a minute."
    assert bot.edits == []


async def test_callback_from_disallowed_chat_ignored() -> None:
    service, bot, client = make_service()
    cb = make_callback(pack(KEY, "a", 1, 0, TOKEN, ""), chat_id=999)
    await service.on_callback(cb)
    assert client.calls == []
    assert bot.edits == []
    cb.answer.assert_awaited_once_with()


async def test_callback_works_without_prior_state() -> None:
    service, bot, _ = make_service()
    assert service.last_message == {}
    await service.on_callback(make_callback(pack(KEY, "p", 1, 3, TOKEN, ""), message_id=555))
    assert bot.edits[0]["message_id"] == 555


async def test_held_command_resends_each_held_entry() -> None:
    service, bot, client = make_service()
    client.entries_result = [
        ENTRY,
        {**ENTRY, "key": "other000", "library": "SharedSync-X", "held_count": 4},
        {**ENTRY, "key": "empty000", "held_count": 0},
    ]
    await service.on_held_command(make_message())
    assert len(bot.sent) == 2
    assert {k for (_, k) in service.last_message} == {KEY, "other000"}


async def test_held_command_nothing_held() -> None:
    service, bot, client = make_service()
    client.entries_result = [{**ENTRY, "held_count": 0}]
    message = make_message()
    await service.on_held_command(message)
    message.answer.assert_awaited_once_with("No held deletions.")
    assert bot.sent == []


async def test_held_command_disallowed_chat_ignored() -> None:
    service, bot, client = make_service()
    message = make_message(999)
    await service.on_held_command(message)
    assert client.calls == [] and bot.sent == []
    message.answer.assert_not_awaited()


async def test_summary_event_sends_nothing() -> None:
    service, bot, client = make_service()
    config = BotConfig(
        bot_token="42:TEST", allowed_chat_ids=frozenset({CHAT}), icloudpd_base_url="http://x"
    )
    _, notify_app = build_application(
        bot,  # type: ignore[arg-type]
        config,
        SimpleNamespace(),  # type: ignore[arg-type]
        ChatState(),
        MfaResultWaiter(),
        service,
    )
    async with TestClient(TestServer(notify_app)) as http:
        summary = {"event_type": "deletion_sync_summary", "username": "u", "data": {}}
        assert (await http.post("/notify", json=summary)).status == 204
        assert bot.sent == [] and client.calls == []
        assert (await http.post("/notify", json=TRIPPED)).status == 204
        # The review is sent in the background, after the 204.
        for _ in range(100):
            if bot.sent:
                break
            await asyncio.sleep(0.01)
    assert len(bot.sent) == 1


class EditFails:
    """edit_message_text replacement that raises the given Telegram error."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def __call__(self, **kwargs: Any) -> None:
        raise self.error


def net_error() -> TelegramNetworkError:
    return TelegramNetworkError(method=None, message="net")  # type: ignore[arg-type]


def raise_connection_error() -> list[dict[str, Any]]:
    raise requests.ConnectionError("down")


async def test_apply_sends_callbacks_keep_token_not_a_fresh_one() -> None:
    service, _, client = make_service()
    client.pages[1] = make_page(1, kept=(3,), keep_token="fresh999")
    await service.on_callback(make_callback(pack(KEY, "a", 1, 0, TOKEN, "seen1234")))
    assert ("resolve", KEY, "apply", TOKEN, "seen1234") in client.calls
    assert not any(c[0] == "page" for c in client.calls)


async def test_old_apply_after_other_message_toggled_goes_stale_path() -> None:
    service, bot, client = make_service()
    client.raise_on = {"resolve": StaleBatchError("t", "new")}
    client.pages[1] = make_page(1, kept=(3,), keep_token="new")
    cb = make_callback(pack(KEY, "a", 1, 0, TOKEN, ""))
    await service.on_callback(cb)
    assert cb.answer.await_args.args[0] == STALE_TEXT
    texts = [t for e in bot.edits for t in block_texts(e["rich_message"])]
    assert not any("will be deleted" in t for t in texts)
    assert all(d.endswith(":new") for d in callback_data(bot.edits[0]["reply_markup"]))


async def test_toggle_with_outdated_keep_token_redraws_without_changing() -> None:
    service, bot, client = make_service()
    client.pages[1] = make_page(1, kept=(3,), keep_token="newer")
    cb = make_callback(pack(KEY, "t", 1, 3, TOKEN, "old"))
    await service.on_callback(cb)
    assert not any(c[0] == "set_keep" for c in client.calls)
    assert cb.answer.await_args.args[0] == STALE_TEXT
    assert len(bot.edits) == 1


async def test_redraw_failure_after_toggle_answers_failure_text() -> None:
    service, bot, client = make_service()
    bot.edit_message_text = EditFails(net_error())  # type: ignore[method-assign]
    cb = make_callback(pack(KEY, "t", 1, 3, TOKEN, ""))
    await service.on_callback(cb)
    assert any(c[0] == "set_keep" for c in client.calls)
    cb.answer.assert_awaited_once()
    assert cb.answer.await_args.args[0] == REDRAW_FAILED_TEXT


async def test_control_failure_during_redraw_after_toggle_answers_failure_text() -> None:
    service, _, client = make_service()
    real_page = client.page
    calls = {"n": 0}

    def page_then_fail(key: str, page: int) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] > 1:
            raise requests.ConnectionError("down")
        return real_page(key, page)

    client.page = page_then_fail  # type: ignore[method-assign]
    cb = make_callback(pack(KEY, "t", 1, 3, TOKEN, ""))
    await service.on_callback(cb)
    assert any(c[0] == "set_keep" for c in client.calls)
    assert cb.answer.await_args.args[0] == REDRAW_FAILED_TEXT


async def test_not_modified_edit_is_ignored() -> None:
    service, bot, _ = make_service()
    error = TelegramBadRequest(
        method=None,  # type: ignore[arg-type]
        message="Bad Request: message is not modified",
    )
    bot.edit_message_text = EditFails(error)  # type: ignore[method-assign]
    cb = make_callback(pack(KEY, "p", 1, 2, TOKEN, ""))
    await service.on_callback(cb)
    assert cb.answer.await_args.args == ()


async def test_stale_handler_answers_even_when_redraw_raises() -> None:
    service, _, client = make_service()
    client.raise_on = {"resolve": StaleBatchError("t", "k")}
    client.entries = raise_connection_error  # type: ignore[method-assign]
    cb = make_callback(pack(KEY, "a", 1, 0, TOKEN, ""))
    await service.on_callback(cb)
    cb.answer.assert_awaited_once()
    assert cb.answer.await_args.args[0] == STALE_TEXT


async def test_apply_final_edit_failure_still_tells_user_it_was_applied() -> None:
    service, bot, _ = make_service()
    bot.edit_message_text = EditFails(net_error())  # type: ignore[method-assign]
    cb = make_callback(pack(KEY, "a", 1, 0, TOKEN, ""))
    await service.on_callback(cb)
    assert "22 will be deleted" in cb.answer.await_args.args[0]
