"""Persistent record of which iCloud assets have been downloaded to which local paths.

One manifest database lives per download directory, at
<download_dir>/.icloudpd/state.db. All operations here are best-effort:
failures are logged and swallowed rather than raised, because this module
is infrastructure for other features and its absence must never break
the core download loop.
"""

from __future__ import annotations

import datetime
import logging
import os
import sqlite3
from dataclasses import dataclass
from typing import Iterator, Sequence

_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloaded_assets (
    record_name           TEXT NOT NULL,
    local_path             TEXT NOT NULL,
    size_bytes              INTEGER NOT NULL,
    checksum                TEXT NULL,
    first_downloaded_utc   TEXT NOT NULL,
    last_seen_utc          TEXT NOT NULL,
    PRIMARY KEY (record_name, local_path)
);
"""


@dataclass(frozen=True)
class ManifestRow:
    record_name: str
    local_path: str
    size_bytes: int
    checksum: str | None
    first_downloaded_utc: str
    last_seen_utc: str


# How many record_seen writes may accumulate before they are committed.
# Bounds data loss if the process is killed mid-run while avoiding a
# synchronous commit (fsync) per asset, which dominates scan time on
# large libraries.
FLUSH_THRESHOLD = 100


@dataclass
class ManifestHandle:
    connection: sqlite3.Connection
    pending_writes: int = 0


def open(logger: logging.Logger, download_dir: str) -> ManifestHandle | None:
    """Open (creating if needed) the manifest database for a download directory.

    Returns None if the database could not be opened or created, in which
    case callers should proceed without manifest tracking rather than fail.
    """
    manifest_dir = os.path.join(download_dir, ".icloudpd")
    try:
        os.makedirs(manifest_dir, exist_ok=True)
        db_path = os.path.join(manifest_dir, "state.db")
        connection = sqlite3.connect(db_path)
        connection.execute(_SCHEMA)
        connection.commit()
        return ManifestHandle(connection=connection)
    except OSError as ex:
        logger.warning("Could not open asset manifest in %s: %s", download_dir, ex)
        return None
    except sqlite3.Error as ex:
        logger.warning("Could not open asset manifest in %s: %s", download_dir, ex)
        return None


def close(handle: ManifestHandle) -> None:
    try:
        handle.connection.commit()
        handle.pending_writes = 0
    except sqlite3.Error:
        pass
    handle.connection.close()


def _now_utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def record_seen(
    logger: logging.Logger,
    handle: ManifestHandle,
    record_name: str,
    local_path: str,
    size_bytes: int,
) -> None:
    """Record that a file for this asset exists locally right now.

    Upserts on (record_name, local_path): inserts a fresh row on first
    sight, or refreshes last_seen_utc (and size_bytes) if the row already
    exists. Never raises - failures are logged and swallowed.

    Writes are batched: they become durable only after FLUSH_THRESHOLD
    accumulated writes or on close(), never per call.
    """
    now = _now_utc_iso()
    try:
        handle.connection.execute(
            """
            INSERT INTO downloaded_assets
                (record_name, local_path, size_bytes, checksum,
                 first_downloaded_utc, last_seen_utc)
            VALUES (?, ?, ?, NULL, ?, ?)
            ON CONFLICT (record_name, local_path) DO UPDATE SET
                size_bytes = excluded.size_bytes,
                last_seen_utc = excluded.last_seen_utc
            """,
            (record_name, local_path, size_bytes, now, now),
        )
        handle.pending_writes += 1
        if handle.pending_writes >= FLUSH_THRESHOLD:
            handle.connection.commit()
            handle.pending_writes = 0
    except sqlite3.Error as ex:
        logger.warning(
            "Could not record manifest entry for %s (%s): %s", record_name, local_path, ex
        )


def get_all_for_asset(handle: ManifestHandle, record_name: str) -> Sequence[ManifestRow]:
    cursor = handle.connection.execute(
        """
        SELECT record_name, local_path, size_bytes, checksum,
               first_downloaded_utc, last_seen_utc
        FROM downloaded_assets
        WHERE record_name = ?
        """,
        (record_name,),
    )
    return [ManifestRow(*row) for row in cursor.fetchall()]


def all_records(handle: ManifestHandle) -> Iterator[ManifestRow]:
    cursor = handle.connection.execute(
        """
        SELECT record_name, local_path, size_bytes, checksum,
               first_downloaded_utc, last_seen_utc
        FROM downloaded_assets
        """
    )
    for row in cursor:
        yield ManifestRow(*row)


def prune(
    logger: logging.Logger, handle: ManifestHandle, record_name: str, local_path: str
) -> None:
    try:
        handle.connection.execute(
            "DELETE FROM downloaded_assets WHERE record_name = ? AND local_path = ?",
            (record_name, local_path),
        )
        handle.connection.commit()
    except sqlite3.Error as ex:
        logger.warning(
            "Could not prune manifest entry for %s (%s): %s", record_name, local_path, ex
        )
