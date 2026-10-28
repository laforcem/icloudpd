"""Deletion-sync state and the per-asset verdict.

Unlike manifest.py, this module is deliberately NOT best-effort. The manifest
is optional infrastructure whose absence must never break downloading. Deletion
sync decides whether to remove photos from iCloud, so a silently failed or
half-applied write could lead to a wrong deletion (or a lost safeguard such as
a held item or a tripped breaker). Every sqlite failure is therefore re-raised
as DeletionSyncError and callers must abort the deletion pass.
"""

from __future__ import annotations

import datetime
import functools
import json
import logging
import os
import sqlite3
import urllib.parse
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Sequence, TypeVar, cast

from icloudpd import manifest
from pyicloud_ipd.asset_version import add_suffix_to_filename
from pyicloud_ipd.services.photos import PhotoAsset, PhotoLibrary


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


NotifyFn = Callable[[str, str, dict[str, Any]], bool]  # (event_type, message, data) -> delivered
DeleteFn = Callable[[PhotoAsset], bool]  # True only on confirmed success

EVENT_ITEMS_CAP = 50
AUTO_DELETE_WINDOW = datetime.timedelta(days=7)
TERMINAL_RETENTION = datetime.timedelta(days=30)
_TERMINAL = (ItemStatus.DELETED, ItemStatus.SKIPPED_GONE, ItemStatus.SKIPPED_REAPPEARED)


def _iso(moment: datetime.datetime) -> str:
    return moment.astimezone(datetime.timezone.utc).isoformat()


def _item_entry(photo: PhotoAsset) -> dict[str, str]:
    return {"record_name": photo.id, "filename": photo.filename, "asset_date": _iso(photo.created)}


def _capped(entries: Sequence[dict[str, str]]) -> dict[str, Any]:
    return {"items": list(entries[:EVENT_ITEMS_CAP]), "total": len(entries)}


def _all_absent(conn: sqlite3.Connection, record_name: str) -> bool:
    rows = manifest.get_all_for_asset(manifest.ManifestHandle(connection=conn), record_name)
    return not any(os.path.isfile(r.local_path) for r in rows)


def _upsert(
    conn: sqlite3.Connection,
    photo: PhotoAsset,
    status: ItemStatus,
    now: str,
    via_approval: int,
) -> None:
    conn.execute(
        "INSERT INTO deletion_items (record_name, filename, asset_date_utc, detected_utc,"
        " status, status_changed_utc, record_change_tag, via_approval)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (record_name) DO UPDATE SET"
        " filename = excluded.filename, asset_date_utc = excluded.asset_date_utc,"
        " status = excluded.status, status_changed_utc = excluded.status_changed_utc,"
        " record_change_tag = excluded.record_change_tag, via_approval = excluded.via_approval",
        (
            photo.id,
            photo.filename,
            _iso(photo.created),
            now,
            status.value,
            now,
            _record_change_tag(photo),
            via_approval,
        ),
    )


def _execute(
    logger: logging.Logger,
    conn: sqlite3.Connection,
    photo: PhotoAsset,
    delete: DeleteFn,
    now: str,
    via_approval: int,
) -> ItemStatus:
    """Delete one asset in iCloud and commit its outcome before returning."""
    rid = photo.id
    if not _all_absent(conn, rid):
        _upsert(conn, photo, ItemStatus.SKIPPED_REAPPEARED, now, via_approval)
        # Restart the two-scan debounce if the file goes missing again.
        conn.execute(
            "UPDATE downloaded_assets SET missing_since_scan = NULL WHERE record_name = ?", (rid,)
        )
        conn.commit()
        logger.info("Not deleting %s: a local file has reappeared", photo.filename)
        return ItemStatus.SKIPPED_REAPPEARED
    if delete(photo):
        _upsert(conn, photo, ItemStatus.DELETED, now, via_approval)
        conn.execute("DELETE FROM downloaded_assets WHERE record_name = ?", (rid,))
        conn.commit()
        logger.info("Deleted %s in iCloud (moved to Recently Deleted)", photo.filename)
        return ItemStatus.DELETED
    _upsert(conn, photo, ItemStatus.FAILED, now, via_approval)
    conn.commit()
    logger.warning("Could not delete %s in iCloud; will retry next scan", photo.filename)
    return ItemStatus.FAILED


def _emit(
    logger: logging.Logger, notify: NotifyFn, event_type: str, message: str, data: dict[str, Any]
) -> None:
    """Notifications are best-effort: never let one fail the run."""
    try:
        if not notify(event_type, message, data):
            logger.warning("Could not deliver %s notification", event_type)
    except Exception as ex:
        logger.warning("Could not deliver %s notification: %s", event_type, ex)


@_wrap_sqlite
def finish_scan(
    logger: logging.Logger,
    scan: DeletionScan,
    *,
    threshold: int,
    delete: DeleteFn,
    notify: NotifyFn,
    now: datetime.datetime | None = None,
) -> None:
    """Run after a completed scan: execute approved items, apply the breaker, notify.

    Each item's outcome is committed as it happens, so an exception part-way
    keeps the deletions already confirmed. In dry-run nothing is written and
    neither `delete` nor `notify` is called; outcomes are only logged.
    """
    conn = scan.connection
    dry = scan.dry_run
    moment = now if now is not None else datetime.datetime.now(datetime.timezone.utc)
    stamp = _iso(moment)

    # 1. The scan enumerated every album to the end.
    if not dry:
        conn.execute(
            "UPDATE deletion_state SET last_completed_scan_seq = ? WHERE id = 1", (scan.scan_seq,)
        )
        conn.commit()

    deleted: list[PhotoAsset] = []
    failed: list[PhotoAsset] = []

    def run(photo: PhotoAsset, via_approval: int) -> None:
        if dry:
            if _all_absent(conn, photo.id):
                logger.info("[DRY RUN] Would delete %s", photo.filename)
            else:
                logger.info("[DRY RUN] Would skip %s: a local file has reappeared", photo.filename)
            return
        outcome = _execute(logger, conn, photo, delete, stamp, via_approval)
        if outcome == ItemStatus.DELETED:
            deleted.append(photo)
        elif outcome == ItemStatus.FAILED:
            failed.append(photo)

    # 2. Approved items bypass the breaker.
    for item in list_items(conn, [ItemStatus.APPROVED]):
        seen = scan.seen.get(item.record_name)
        if seen is not None:
            run(seen, 1)
        elif dry:
            logger.info("[DRY RUN] Would skip %s: no longer in iCloud", item.filename)
        else:
            conn.execute(
                "UPDATE deletion_items SET status = ?, status_changed_utc = ?"
                " WHERE record_name = ?",
                (ItemStatus.SKIPPED_GONE.value, stamp, item.record_name),
            )
            conn.commit()
            logger.info("Approved deletion of %s skipped: no longer in iCloud", item.filename)

    # 3. New candidates go through the circuit breaker.
    held = {i.record_name for i in list_items(conn, [ItemStatus.HELD])}
    new = [photo for rid, photo in scan.candidates.items() if rid not in held]
    if new:
        cutoff = _iso(moment - AUTO_DELETE_WINDOW)
        (recent,) = conn.execute(
            "SELECT COUNT(*) FROM deletion_items"
            " WHERE status = ? AND via_approval = 0 AND status_changed_utc >= ?",
            (ItemStatus.DELETED.value, cutoff),
        ).fetchone()
        (tripped,) = conn.execute("SELECT tripped FROM deletion_state WHERE id = 1").fetchone()
        count = len(held) + len(new) + recent
        if threshold > 0 and (tripped or count >= threshold):
            held_count = len(held) + len(new)
            if dry:
                logger.info("[DRY RUN] Would hold %d items (threshold %d)", held_count, threshold)
            else:
                for photo in new:
                    _upsert(conn, photo, ItemStatus.HELD, stamp, 0)
                conn.execute(
                    "UPDATE deletion_state SET tripped = 1,"
                    " tripped_utc = CASE WHEN tripped = 1 THEN tripped_utc ELSE ? END"
                    " WHERE id = 1",
                    (stamp,),
                )
                conn.commit()
                logger.warning(
                    "Deletion sync is holding %d items (threshold %d); nothing was deleted. "
                    "Approve or reject them with --resolve-deletions.",
                    held_count,
                    threshold,
                )
                entries = [
                    {
                        "record_name": i.record_name,
                        "filename": i.filename,
                        "asset_date": i.asset_date_utc,
                    }
                    for i in list_items(conn, [ItemStatus.HELD])
                ]
                _emit(
                    logger,
                    notify,
                    "deletion_sync_threshold_tripped",
                    f"Deletion sync is holding {held_count} item(s) for review "
                    f"(threshold {threshold}); nothing was deleted.",
                    {
                        "held_count": held_count,
                        "new_count": len(new),
                        "threshold": threshold,
                        **_capped(entries),
                    },
                )
        else:
            for photo in new:
                run(photo, 0)

    if dry:
        return

    # 5. Prune terminal rows past retention.
    placeholders = ",".join("?" for _ in _TERMINAL)
    conn.execute(
        f"DELETE FROM deletion_items WHERE status IN ({placeholders}) AND status_changed_utc < ?",
        [s.value for s in _TERMINAL] + [_iso(moment - TERMINAL_RETENTION)],
    )
    conn.commit()

    # 6. Summary.
    if deleted or failed:
        message = f"Deletion sync moved {len(deleted)} item(s) to iCloud Recently Deleted"
        if failed:
            message += f"; {len(failed)} failed and will be retried"
        _emit(
            logger,
            notify,
            "deletion_sync_summary",
            message,
            {
                "deleted_count": len(deleted),
                "failed_count": len(failed),
                **_capped([_item_entry(p) for p in deleted]),
            },
        )


def delete_asset(logger: logging.Logger, library_object: PhotoLibrary, photo: PhotoAsset) -> bool:
    """Move one asset to Recently Deleted. True only if iCloud confirmed it."""
    record_name = photo._asset_record["recordName"]
    url = (
        f"{library_object.service_endpoint}/records/modify?"
        f"{urllib.parse.urlencode(library_object.params)}"
    )
    post_data = json.dumps(
        {
            "atomic": True,
            "desiredKeys": ["isDeleted"],
            "operations": [
                {
                    "operationType": "update",
                    "record": {
                        "fields": {"isDeleted": {"value": 1}},
                        "recordChangeTag": photo._asset_record["recordChangeTag"],
                        "recordName": record_name,
                        "recordType": "CPLAsset",
                    },
                }
            ],
            "zoneID": library_object.zone_id,
        }
    )
    try:
        response = library_object.session.post(
            url, data=post_data, headers={"Content-type": "application/json"}
        )
        if not response.ok:
            logger.warning(
                "Deleting %s in iCloud failed: HTTP %s", photo.filename, response.status_code
            )
            return False
        records = response.json().get("records")
        if not isinstance(records, list):
            logger.warning("Deleting %s in iCloud: no records in the response", photo.filename)
            return False
        errors = [r for r in records if "serverErrorCode" in r]
        if errors:
            logger.warning(
                "Deleting %s in iCloud failed: %s", photo.filename, errors[0]["serverErrorCode"]
            )
            return False
        if not any(r.get("recordName") == record_name for r in records):
            logger.warning("Deleting %s in iCloud: record not confirmed", photo.filename)
            return False
        return True
    except Exception as ex:
        logger.warning("Deleting %s in iCloud failed: %s", photo.filename, ex)
        return False
