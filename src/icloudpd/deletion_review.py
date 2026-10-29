"""Review of held deletion batches: per-photo keep marks and a guarded apply.

The batch token (a hash of the held record names) lets a writer prove it acted
on the batch the user saw. It is checked inside the write transaction, so a scan
that adds or removes a held item between the page view and the tap cannot slip
through.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Literal

from icloudpd import deletion_sync
from icloudpd.deletion_sync import DeletionSyncError, ItemStatus

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
