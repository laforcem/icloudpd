"""Telegram review of held deletions: one rich message per entry, edited in place.

The service keeps no review state beyond the id of the latest message per
(chat, entry), used only to mark a replaced message as superseded. Every
button carries the entry key, page and batch token, so a bot restart does not
break messages that are already open.

Photos are uploaded (not linked): the typed aiogram classes carry a
BufferedInputFile in InputMediaPhoto.media, and the session turns it into an
`attach://` multipart part when the request is built.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import requests
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputRichBlockCollage,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichMessage,
    Message,
    RichBlockCaption,
)

from bot.control_client import ControlClient, StaleBatchError, SyncingError
from bot.placeholder import PLACEHOLDER_JPEG

logger = logging.getLogger(__name__)

PREFIX = "ds"
OPS = frozenset({"t", "p", "a", "k"})
STALE_TEXT = "The batch changed, nothing was deleted. Here's the updated batch."
SYNCING_TEXT = "icloudpd is syncing, try again in a minute."
REDRAW_FAILED_TEXT = "Couldn't update the message, tap Next/Prev to refresh."
APPLIED_NO_REDRAW_SUFFIX = " (Couldn't update the message.)"
UNREACHABLE_TEXT = "Couldn't reach icloudpd, try again in a minute."
GONE_TEXT = "This review is no longer available."
NOTHING_HELD_TEXT = "No held deletions."
SUPERSEDED_TEXT = "Superseded, see the newer message."
NO_THUMBS_TEXT = "Thumbnails return after icloudpd's next successful login."


@dataclass(frozen=True)
class Callback:
    key: str
    op: str
    page: int
    arg: int
    token: str
    keep_token: str


def pack(key: str, op: str, page: int, arg: int, token: str, keep_token: str = "") -> str:
    """`keep_token` is the fingerprint of the keep marks shown with the page."""
    if op not in OPS:
        raise ValueError(f"unknown op {op!r}")
    if ":" in key or ":" in token or ":" in keep_token or not key or not token:
        raise ValueError("key and token must be non-empty and contain no ':'")
    return f"{PREFIX}:{key}:{op}:{page}:{arg}:{token}:{keep_token}"


def unpack(data: str) -> Callback:
    parts = data.split(":")
    if len(parts) != 7 or parts[0] != PREFIX:
        raise ValueError(f"not a review callback: {data!r}")
    _, key, op, page, arg, token, keep_token = parts
    if op not in OPS or not key or not token or not page.isdigit() or not arg.isdigit():
        raise ValueError(f"malformed review callback: {data!r}")
    return Callback(
        key=key, op=op, page=int(page), arg=int(arg), token=token, keep_token=keep_token
    )


def _paragraph(text: str) -> InputRichBlockParagraph:
    return InputRichBlockParagraph(text=text)


def _text_message(text: str) -> InputRichMessage:
    return InputRichMessage(blocks=[_paragraph(text)])


def render(
    entry: dict[str, Any], page: dict[str, Any], thumbs: dict[str, bytes | None]
) -> tuple[InputRichMessage, InlineKeyboardMarkup]:
    items: list[dict[str, Any]] = page["items"]
    header = (
        f"⚠️ {page['total']} photos held for deletion ({entry['username']} · {entry['library']})."
    )
    blocks: list[Any] = [_paragraph(header)]
    if items and all(thumbs.get(i["record_name"]) is None for i in items):
        for i in items:
            date = str(i.get("asset_date") or "unknown date")[:10]
            blocks.append(_paragraph(f"{i['number']}. {i['filename']} · {date}"))
        blocks.append(_paragraph(NO_THUMBS_TEXT))
    else:
        tiles = []
        for i in items:
            data = thumbs.get(i["record_name"]) or PLACEHOLDER_JPEG
            label = f"▶ {i['number']}" if i["is_video"] else str(i["number"])
            tiles.append(
                InputRichBlockPhoto(
                    photo=InputMediaPhoto(
                        media=BufferedInputFile(data, filename=f"{i['number']}.jpg")
                    ),
                    caption=RichBlockCaption(text=label),
                )
            )
        if tiles:
            blocks.append(InputRichBlockCollage(blocks=tiles))
    return InputRichMessage(blocks=blocks), _keyboard(entry["key"], page)


def _keyboard(key: str, page: dict[str, Any]) -> InlineKeyboardMarkup:
    token, current, pages = page["batch_token"], page["page"], page["pages"]
    marks = page.get("keep_token", "")
    toggles = [
        InlineKeyboardButton(
            text=f"{'💾' if i['keep'] else '🗑'} {i['number']}",
            callback_data=pack(key, "t", current, i["number"], token, marks),
        )
        for i in page["items"]
    ]
    rows = [toggles[:5], toggles[5:10]]
    nav = []
    if current > 1:
        nav.append(
            InlineKeyboardButton(
                text="◀ Prev", callback_data=pack(key, "p", current, current - 1, token, marks)
            )
        )
    if current < pages:
        nav.append(
            InlineKeyboardButton(
                text="Next ▶", callback_data=pack(key, "p", current, current + 1, token, marks)
            )
        )
    kept = page["kept_count"]
    rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(
                text=f"✅ Delete {page['total'] - kept}, keep {kept}",
                callback_data=pack(key, "a", current, 0, token, marks),
            ),
            InlineKeyboardButton(
                text="❌ Keep all", callback_data=pack(key, "k", current, 0, token, marks)
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


class ReviewService:
    def __init__(
        self, bot: Bot, client: ControlClient, allowed_chat_ids: frozenset[int]
    ) -> None:
        self._bot = bot
        self._client = client
        self._allowed = allowed_chat_ids
        self.last_message: dict[tuple[int, str], int] = {}

    # -- inbound events ---------------------------------------------------

    async def on_tripped(self, event: dict[str, Any]) -> None:
        library = (event.get("data") or {}).get("library")
        try:
            entries = await asyncio.to_thread(self._client.entries)
            entry = next(
                (
                    e
                    for e in entries
                    if e["username"] == event.get("username") and e["library"] == library
                ),
                None,
            )
            if entry is None:
                logger.warning("No control-channel entry matches the tripped event; skipping")
                return
            await self._send_review(entry, sorted(self._allowed))
        except requests.RequestException as ex:
            logger.warning("Could not fetch held deletions from icloudpd: %s", type(ex).__name__)

    async def on_held_command(self, message: Message) -> None:
        chat_id = message.chat.id
        if chat_id not in self._allowed:
            return
        try:
            entries = await asyncio.to_thread(self._client.entries)
            held = [e for e in entries if e.get("held_count", 0) > 0]
            if not held:
                await message.answer(NOTHING_HELD_TEXT)
                return
            for entry in held:
                await self._send_review(entry, [chat_id])
        except (requests.RequestException, SyncingError):
            await message.answer(UNREACHABLE_TEXT)

    async def on_callback(self, callback: CallbackQuery) -> None:
        chat_id = callback.message.chat.id
        if chat_id not in self._allowed:
            await callback.answer()
            return
        try:
            cb = unpack(callback.data or "")
        except ValueError:
            await callback.answer()
            return
        message_id = callback.message.message_id
        try:
            await self._dispatch(callback, cb, chat_id, message_id)
        except StaleBatchError:
            # Answer first: the redraw is best effort and must not leave the tap unanswered.
            await callback.answer(STALE_TEXT)
            try:
                await self._draw(chat_id, message_id, cb.key, cb.page)
            except (requests.RequestException, SyncingError, TelegramAPIError) as ex:
                logger.warning("Could not redraw after a stale batch: %s", type(ex).__name__)
        except SyncingError:
            await callback.answer(SYNCING_TEXT, show_alert=True)
        except requests.RequestException as ex:
            logger.warning("Review action failed: %s", type(ex).__name__)
            await callback.answer(UNREACHABLE_TEXT, show_alert=True)
        except TelegramAPIError as ex:
            logger.warning("Review message update failed: %s", type(ex).__name__)
            await callback.answer(REDRAW_FAILED_TEXT, show_alert=True)

    # -- internals --------------------------------------------------------

    async def _dispatch(
        self, callback: CallbackQuery, cb: Callback, chat_id: int, mid: int
    ) -> None:
        client = self._client
        if cb.op == "t":
            page = await asyncio.to_thread(client.page, cb.key, cb.page)
            item = next((i for i in page["items"] if i["number"] == cb.arg), None)
            # The tap flips the state this message showed; if the marks moved since
            # (another message toggled), flipping now would do the opposite of the intent.
            if item is None or page.get("keep_token", "") != cb.keep_token:
                raise StaleBatchError(page["batch_token"], page.get("keep_token", ""))
            await asyncio.to_thread(
                client.set_keep, cb.key, item["record_name"], not item["keep"], cb.token
            )
            # The keep mark is saved; a failed redraw must not look like success.
            try:
                await self._draw(chat_id, mid, cb.key, cb.page)
            except (requests.RequestException, SyncingError, TelegramAPIError) as ex:
                logger.warning("Redraw after keep toggle failed: %s", type(ex).__name__)
                await callback.answer(REDRAW_FAILED_TEXT, show_alert=True)
                return
            await callback.answer()
        elif cb.op == "p":
            page = await asyncio.to_thread(client.page, cb.key, cb.arg)
            await self._draw(chat_id, mid, cb.key, cb.arg, prefetched=page)
            if page["batch_token"] != cb.token:
                await callback.answer(STALE_TEXT)
            else:
                await callback.answer()
        else:
            action = "apply" if cb.op == "a" else "keep_all"
            # Apply sends the keep token this message was drawn with, never a fresh one.
            result = await asyncio.to_thread(
                client.resolve,
                cb.key,
                action,
                cb.token,
                cb.keep_token if cb.op == "a" else None,
            )
            if cb.op == "a":
                text = (
                    f"{result['approved']} will be deleted at the next sync. "
                    f"{result['rejected']} kept, re-downloading."
                )
            else:
                text = (
                    f"Nothing deleted. {result['rejected']} photos will re-download "
                    "at the next sync."
                )
            try:
                await self._edit(chat_id, mid, _text_message(text), None)
            except TelegramAPIError as ex:
                # Already resolved on the server: say so rather than report a failure.
                logger.warning("Could not edit the final review text: %s", type(ex).__name__)
                await callback.answer(text + APPLIED_NO_REDRAW_SUFFIX, show_alert=True)
                return
            await callback.answer()

    async def _fetch_thumbs(self, key: str, page: dict[str, Any]) -> dict[str, bytes | None]:
        async def one(record_name: str) -> tuple[str, bytes | None]:
            try:
                return record_name, await asyncio.to_thread(
                    self._client.thumbnail, key, record_name
                )
            except requests.RequestException:
                return record_name, None

        results = await asyncio.gather(*(one(i["record_name"]) for i in page["items"]))
        return dict(results)

    async def _find_entry(self, key: str) -> dict[str, Any] | None:
        entries = await asyncio.to_thread(self._client.entries)
        return next((e for e in entries if e["key"] == key), None)

    async def _draw(
        self,
        chat_id: int,
        message_id: int,
        key: str,
        page_number: int,
        prefetched: dict[str, Any] | None = None,
    ) -> None:
        """Re-render an open message from current server state."""
        entry = await self._find_entry(key)
        if entry is None:
            await self._edit(chat_id, message_id, _text_message(GONE_TEXT), None)
            return
        page = prefetched or await asyncio.to_thread(self._client.page, key, page_number)
        if page["total"] == 0:
            await self._edit(chat_id, message_id, _text_message(NOTHING_HELD_TEXT), None)
            return
        if page["page"] > page["pages"] or not page["items"]:
            page = await asyncio.to_thread(self._client.page, key, page["pages"])
        thumbs = await self._fetch_thumbs(key, page)
        rich, markup = render(entry, page, thumbs)
        await self._edit(chat_id, message_id, rich, markup)

    async def _send_review(self, entry: dict[str, Any], chat_ids: list[int]) -> None:
        key = entry["key"]
        page = await asyncio.to_thread(self._client.page, key, 1)
        if page["total"] == 0:
            return
        thumbs = await self._fetch_thumbs(key, page)
        rich, markup = render(entry, page, thumbs)
        for chat_id in chat_ids:
            sent = await self._bot.send_rich_message(
                chat_id=chat_id, rich_message=rich, reply_markup=markup
            )
            previous = self.last_message.get((chat_id, key))
            self.last_message[(chat_id, key)] = sent.message_id
            if previous is not None:
                try:
                    await self._edit(chat_id, previous, _text_message(SUPERSEDED_TEXT), None)
                except TelegramAPIError as ex:
                    logger.info("Could not mark old review superseded: %s", type(ex).__name__)

    async def _edit(
        self,
        chat_id: int,
        message_id: int,
        rich: InputRichMessage,
        markup: InlineKeyboardMarkup | None,
    ) -> None:
        try:
            await self._bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, rich_message=rich, reply_markup=markup
            )
        except TelegramBadRequest as ex:
            # Only a no-op edit is benign; anything else the caller must handle.
            if "message is not modified" not in str(ex):
                raise
