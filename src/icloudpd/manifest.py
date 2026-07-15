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


@dataclass
class ManifestHandle:
    connection: sqlite3.Connection


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
    handle.connection.close()


def _now_utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
