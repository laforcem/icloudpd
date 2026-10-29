"""Review of held deletion batches: per-photo keep marks and a guarded apply.

The batch token (a hash of the held record names) lets a writer prove it acted
on the batch the user saw. It is checked inside the write transaction, so a scan
that adds or removes a held item between the page view and the tap cannot slip
through.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal

import requests

from icloudpd import deletion_sync
from icloudpd.deletion_sync import DeletionSyncError, ItemStatus
from icloudpd.session_registry import SessionRegistry
from pyicloud_ipd.exceptions import (
    PyiCloudAPIResponseException,
    PyiCloudConnectionErrorException,
)

PAGE_SIZE = 10

_HELD = ItemStatus.HELD.value


class StaleBatch(Exception):
    """The held batch changed since the caller's token was issued."""

    def __init__(self, batch_token: str) -> None:
        super().__init__(f"held batch changed (now {batch_token or 'empty'})")
        self.batch_token = batch_token


class Busy(Exception):
    """state.db is write-locked by another process."""


@dataclass(frozen=True)
class ReviewItem:
    number: int
    record_name: str
    filename: str
    asset_date_utc: str
    keep: bool


@dataclass(frozen=True)
class ReviewPage:
    batch_token: str
    page: int
    pages: int
    total: int
    kept_count: int
    items: list[ReviewItem]


def entry_key(username: str, library: str) -> str:
    return hashlib.sha256(f"{username}\0{library}".encode()).hexdigest()[:8]


def batch_token(connection: sqlite3.Connection) -> str:
    """8 hex chars over the sorted held record names; blank when nothing is held."""
    names = [
        r[0]
        for r in connection.execute(
            "SELECT record_name FROM deletion_items WHERE status = ? ORDER BY record_name",
            (_HELD,),
        )
    ]
    if not names:
        return ""
    return hashlib.sha256("\n".join(names).encode()).hexdigest()[:8]


def _counts(connection: sqlite3.Connection) -> tuple[int, int]:
    total, kept = connection.execute(
        "SELECT COUNT(*), COALESCE(SUM(keep_marked), 0) FROM deletion_items WHERE status = ?",
        (_HELD,),
    ).fetchone()
    return int(total), int(kept)


def held_page(connection: sqlite3.Connection, page: int) -> ReviewPage:
    try:
        total, kept = _counts(connection)
        token = batch_token(connection)
        pages = max(1, -(-total // PAGE_SIZE)) if total else 0
        offset = (page - 1) * PAGE_SIZE
        rows = (
            connection.execute(
                "SELECT record_name, filename, asset_date_utc, keep_marked FROM deletion_items"
                " WHERE status = ? ORDER BY detected_utc, record_name LIMIT ? OFFSET ?",
                (_HELD, PAGE_SIZE, offset),
            ).fetchall()
            if page >= 1
            else []
        )
    except sqlite3.Error as ex:
        raise DeletionSyncError(f"held_page: {ex}") from ex
    items = [
        ReviewItem(
            number=offset + n + 1,
            record_name=r[0],
            filename=r[1],
            asset_date_utc=r[2],
            keep=bool(r[3]),
        )
        for n, r in enumerate(rows)
    ]
    return ReviewPage(
        batch_token=token, page=page, pages=pages, total=total, kept_count=kept, items=items
    )


def _begin(connection: sqlite3.Connection, token: str) -> None:
    """Open the write transaction and verify the token inside it."""
    try:
        connection.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as ex:
        if "locked" in str(ex) or "busy" in str(ex):
            raise Busy(str(ex)) from ex
        raise DeletionSyncError(f"begin: {ex}") from ex
    current = batch_token(connection)
    if current != token:
        connection.rollback()
        raise StaleBatch(current)


def set_keep(
    connection: sqlite3.Connection, record_name: str, keep: bool, token: str
) -> tuple[int, int]:
    """Mark or unmark one held photo as 'keep'. Returns (total, kept_count)."""
    _begin(connection, token)
    try:
        changed = connection.execute(
            "UPDATE deletion_items SET keep_marked = ? WHERE record_name = ? AND status = ?",
            (1 if keep else 0, record_name, _HELD),
        ).rowcount
        if not changed:
            connection.rollback()
            raise KeyError(record_name)
        counts = _counts(connection)
        connection.commit()
    except sqlite3.Error as ex:
        connection.rollback()
        raise DeletionSyncError(f"set_keep: {ex}") from ex
    except BaseException:
        connection.rollback()
        raise
    return counts


def apply_review(
    connection: sqlite3.Connection, action: Literal["apply", "keep_all"], token: str
) -> tuple[int, int]:
    """Approve the unmarked held items and reject the marked ones (all, for keep_all).

    Returns (approved count, rejected count).
    """
    _begin(connection, token)
    try:
        held = deletion_sync.list_items(connection, [ItemStatus.HELD])
        if action == "keep_all":
            approve: list[str] = []
            reject = [i.record_name for i in held]
        else:
            approve = [i.record_name for i in held if not i.keep_marked]
            reject = [i.record_name for i in held if i.keep_marked]
        approved, rejected = deletion_sync.apply_resolution(connection, approve, reject)
        connection.commit()
    except sqlite3.Error as ex:
        connection.rollback()
        raise DeletionSyncError(f"apply_review: {ex}") from ex
    except BaseException:
        connection.rollback()
        raise
    return len(approved), len(rejected)


_JPEG_FIELD = re.compile(r"^resJPEG\w+Res$")
_REAUTH_CODES = {"401", "421", "450"}
_NETWORK_ERRORS = (requests.RequestException, PyiCloudConnectionErrorException)


def thumbnail_field(master: dict[str, Any]) -> str | None:
    """Name of the smallest JPEG derivative field on a master record, or None.

    Only JPEG fields qualify: a video's small derivative (resVidSmallRes) is a video.
    """
    fields = master.get("fields", {})
    if "resJPEGThumbRes" in fields:
        return "resJPEGThumbRes"
    candidates = [k for k in fields if _JPEG_FIELD.match(k)]
    if not candidates:
        return None
    return min(candidates, key=lambda k: fields[k].get("value", {}).get("size", 0))


def _library_object(service: Any, library: str) -> Any:
    if not library:
        return service.photos
    if library in service.photos.private_libraries:
        return service.photos.private_libraries[library]
    return service.photos.shared_libraries[library]


def fetch_thumbnail(
    registry: SessionRegistry, username: str, library: str, record_name: str, now: float
) -> bytes | None:
    """JPEG bytes for a held photo using the account's live session, or None.

    Never prompts for a password or 2FA; None means "show a placeholder".
    """
    try:
        service = registry.get(username) or registry.refresh(username, now)
    except _NETWORK_ERRORS:
        return None
    if service is None:
        return None
    for attempt in (1, 2):
        try:
            lib = _library_object(service, library)
            master = lib.lookup_masters([record_name]).get(record_name)
            field = master and thumbnail_field(master)
            if not master or not field:
                return None
            content: bytes = service.session.get(
                master["fields"][field]["value"]["downloadURL"]
            ).content
            return content
        except PyiCloudAPIResponseException as e:
            if attempt == 2 or e.code not in _REAUTH_CODES:
                return None
            try:
                service = registry.refresh(username, now)
            except _NETWORK_ERRORS:
                return None
            if service is None:
                return None
        except (*_NETWORK_ERRORS, KeyError):
            return None
    return None
