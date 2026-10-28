"""Deletion-sync state and the per-asset verdict.

Unlike manifest.py, this module is deliberately NOT best-effort. The manifest
is optional infrastructure whose absence must never break downloading. Deletion
sync decides whether to remove photos from iCloud, so a silently failed or
half-applied write could lead to a wrong deletion (or a lost safeguard such as
a held item or a tripped breaker). Every sqlite failure is therefore re-raised
as DeletionSyncError and callers must abort the deletion pass.
"""

from __future__ import annotations

import functools
import logging
import os
import sqlite3
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Sequence, TypeVar, cast

from icloudpd import manifest
from pyicloud_ipd.asset_version import add_suffix_to_filename
from pyicloud_ipd.services.photos import PhotoAsset


class DeletionSyncError(Exception):
    """Any sqlite failure in this module."""


class Verdict(Enum):
    PROCEED = "proceed"  # download as today
    SUSPECT = "suspect"  # fully missing, first scan: skip download
    CANDIDATE = "candidate"  # fully missing, confirmed: skip download, collected for finish_scan
    HELD = "held"  # held/approved item: skip download


class ItemStatus(str, Enum):
    HELD = "held"
    APPROVED = "approved"
    REJECTED = "rejected"
    DELETED = "deleted"
    SKIPPED_GONE = "skipped_gone"
    SKIPPED_REAPPEARED = "skipped_reappeared"
    FAILED = "failed"


@dataclass(frozen=True)
class DeletionItem:
    record_name: str
    filename: str
    asset_date_utc: str
    status: ItemStatus
    detected_utc: str
    status_changed_utc: str


@dataclass
class DeletionScan:
    connection: sqlite3.Connection
    scan_seq: int
    last_completed_scan_seq: int
    dry_run: bool
    candidates: dict[str, PhotoAsset]  # record_name -> asset, new this scan
    seen: dict[str, PhotoAsset]  # held/approved items visited this scan


_SCHEMA = """
CREATE TABLE IF NOT EXISTS deletion_items (
    record_name        TEXT PRIMARY KEY,
    filename           TEXT NOT NULL,
    asset_date_utc     TEXT NOT NULL,
    detected_utc       TEXT NOT NULL,
    status             TEXT NOT NULL,
    status_changed_utc TEXT NOT NULL,
    record_change_tag  TEXT NULL,
    via_approval       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS deletion_state (
    id                      INTEGER PRIMARY KEY CHECK (id = 1),
    scan_seq                INTEGER NOT NULL DEFAULT 0,
    last_completed_scan_seq INTEGER NOT NULL DEFAULT 0,
    tripped                 INTEGER NOT NULL DEFAULT 0,
    tripped_utc             TEXT NULL
);
INSERT OR IGNORE INTO deletion_state (id) VALUES (1);
"""

_F = TypeVar("_F", bound=Callable[..., Any])


def _wrap_sqlite(func: _F) -> _F:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except sqlite3.Error as ex:
            raise DeletionSyncError(f"{func.__name__}: {ex}") from ex

    return cast(_F, wrapper)


@_wrap_sqlite
def ensure_schema(connection: sqlite3.Connection) -> None:
    columns = [row[1] for row in connection.execute("PRAGMA table_info(downloaded_assets)")]
    if "missing_since_scan" not in columns:
        connection.execute(
            "ALTER TABLE downloaded_assets ADD COLUMN missing_since_scan INTEGER NULL"
        )
    connection.executescript(_SCHEMA)
    connection.commit()


@_wrap_sqlite
def open_scan(
    logger: logging.Logger, handle: manifest.ManifestHandle, dry_run: bool
) -> DeletionScan:
    connection = handle.connection
    if dry_run:
        # Leave the on-disk database untouched: judge against an in-memory copy.
        copy = sqlite3.connect(":memory:")
        connection.backup(copy)
        connection = copy
    ensure_schema(connection)
    if not dry_run:
        connection.execute("UPDATE deletion_state SET scan_seq = scan_seq + 1 WHERE id = 1")
        connection.commit()
    seq, completed = connection.execute(
        "SELECT scan_seq, last_completed_scan_seq FROM deletion_state WHERE id = 1"
    ).fetchone()
    if dry_run:
        seq += 1
    logger.debug("Deletion scan %d opened (last completed: %d)", seq, completed)
    return DeletionScan(
        connection=connection,
        scan_seq=seq,
        last_completed_scan_seq=completed,
        dry_run=dry_run,
        candidates={},
        seen={},
    )


def path_variants(path: str, size_bytes: int) -> list[str]:
    """Paths under which download_builder may have stored a file planned at `path`."""
    return [
        path,
        add_suffix_to_filename("-original", path),
        f"-{size_bytes}.".join(path.rsplit(".", 1)),
    ]


def _record_change_tag(photo: PhotoAsset) -> str | None:
    tag = photo._asset_record.get("recordChangeTag")
    return str(tag) if tag is not None else None


@_wrap_sqlite
def judge_asset(
    logger: logging.Logger,
    scan: DeletionScan,
    photo: PhotoAsset,
    planned: Sequence[tuple[str, int]],
) -> Verdict:
    conn = scan.connection
    rid = photo.id
    write = not scan.dry_run

    def clear_mark() -> None:
        conn.execute(
            "UPDATE downloaded_assets SET missing_since_scan = NULL"
            " WHERE record_name = ? AND missing_since_scan IS NOT NULL",
            (rid,),
        )

    def drop_item() -> None:
        conn.execute("DELETE FROM deletion_items WHERE record_name = ?", (rid,))

    rows = manifest.get_all_for_asset(manifest.ManifestHandle(connection=conn), rid)
    item = conn.execute(
        "SELECT status FROM deletion_items WHERE record_name = ?", (rid,)
    ).fetchone()
    status = item[0] if item else None
    present = [r for r in rows if os.path.isfile(r.local_path)]
    matches = any(r.local_path in path_variants(p, s) for r in rows for (p, s) in planned)
    fully_missing = bool(rows) and matches and not present

    if status in (ItemStatus.HELD.value, ItemStatus.APPROVED.value):
        if present:
            if write:
                drop_item()
                clear_mark()
                conn.commit()
            logger.debug("Held asset %s reappeared locally; dropping item", rid)
            return Verdict.PROCEED
        if write:
            conn.execute(
                "UPDATE deletion_items SET record_change_tag = ? WHERE record_name = ?",
                (_record_change_tag(photo), rid),
            )
            conn.commit()
        scan.seen[rid] = photo
        return Verdict.HELD

    if status == ItemStatus.REJECTED.value:
        if present and write:
            drop_item()
            conn.commit()
        return Verdict.PROCEED

    if not fully_missing:
        if write:
            clear_mark()
            if status == ItemStatus.FAILED.value:
                drop_item()
            conn.commit()
        return Verdict.PROCEED

    newest, unmarked = conn.execute(
        "SELECT MAX(missing_since_scan), COUNT(*) - COUNT(missing_since_scan)"
        " FROM downloaded_assets WHERE record_name = ?",
        (rid,),
    ).fetchone()
    # Every row must carry a mark; a NULL row was never observed missing.
    mark = None if unmarked else newest
    if mark is not None and mark <= scan.last_completed_scan_seq:
        scan.candidates[rid] = photo
        return Verdict.CANDIDATE
    if mark != scan.scan_seq and write:
        conn.execute(
            "UPDATE downloaded_assets SET missing_since_scan = ? WHERE record_name = ?",
            (scan.scan_seq, rid),
        )
        conn.commit()
    return Verdict.SUSPECT


@_wrap_sqlite
def mark_completed(scan: DeletionScan) -> None:
    """Record that this scan enumerated every album to the end (no-op in dry-run)."""
    if scan.dry_run:
        return
    scan.connection.execute(
        "UPDATE deletion_state SET last_completed_scan_seq = ? WHERE id = 1", (scan.scan_seq,)
    )
    scan.connection.commit()


@_wrap_sqlite
def list_items(
    connection: sqlite3.Connection, statuses: Sequence[ItemStatus]
) -> list[DeletionItem]:
    if not statuses:
        return []
    placeholders = ",".join("?" for _ in statuses)
    cursor = connection.execute(
        "SELECT record_name, filename, asset_date_utc, status, detected_utc, status_changed_utc"
        f" FROM deletion_items WHERE status IN ({placeholders}) ORDER BY detected_utc, record_name",
        [s.value for s in statuses],
    )
    return [
        DeletionItem(
            record_name=r[0],
            filename=r[1],
            asset_date_utc=r[2],
            status=ItemStatus(r[3]),
            detected_utc=r[4],
            status_changed_utc=r[5],
        )
        for r in cursor.fetchall()
    ]
