import datetime
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest

from icloudpd import deletion_sync, manifest
from icloudpd.deletion_sync import DeletionSyncError, ItemStatus, Verdict
from pyicloud_ipd.services.photos import PhotoAsset

LOGGER = logging.getLogger("test_deletion_sync_state")


class FakeAsset:
    def __init__(self, record_name: str = "REC1", tag: str = "tag1") -> None:
        self.id = record_name
        self.filename = "IMG_1.JPG"
        self.created = datetime.datetime(2024, 1, 2, tzinfo=datetime.timezone.utc)
        self._asset_record = {"recordName": record_name, "recordChangeTag": tag}


def asset(record_name: str = "REC1", tag: str = "tag1") -> PhotoAsset:
    return cast(PhotoAsset, FakeAsset(record_name, tag))


@pytest.fixture
def handle(tmp_path: Path) -> manifest.ManifestHandle:
    h = manifest.open(LOGGER, str(tmp_path / "lib"))
    assert h is not None
    return h


def make_file(tmp_path: Path, name: str) -> str:
    p = tmp_path / name
    p.write_bytes(b"x")
    return str(p)


def record(h: manifest.ManifestHandle, path: str, rec: str = "REC1") -> None:
    manifest.record_seen(LOGGER, h, rec, path, 1)
    h.connection.commit()


def missing_since(h: manifest.ManifestHandle, rec: str = "REC1") -> list[Any]:
    deletion_sync.ensure_schema(h.connection)
    return [
        r[0]
        for r in h.connection.execute(
            "SELECT missing_since_scan FROM downloaded_assets WHERE record_name = ?", (rec,)
        )
    ]


def complete(h: manifest.ManifestHandle, seq: int) -> None:
    h.connection.execute("UPDATE deletion_state SET last_completed_scan_seq = ?", (seq,))
    h.connection.commit()


def add_item(h: manifest.ManifestHandle, status: str, rec: str = "REC1") -> None:
    deletion_sync.ensure_schema(h.connection)
    h.connection.execute(
        "INSERT INTO deletion_items (record_name, filename, asset_date_utc, detected_utc,"
        " status, status_changed_utc) VALUES (?, 'IMG_1.JPG', 'd', 'd', ?, 'd')",
        (rec, status),
    )
    h.connection.commit()


def item_count(h: manifest.ManifestHandle) -> int:
    return int(h.connection.execute("SELECT COUNT(*) FROM deletion_items").fetchone()[0])


def test_present_asset_proceeds(tmp_path: Path, handle: manifest.ManifestHandle) -> None:
    path = make_file(tmp_path, "IMG_1.JPG")
    record(handle, path)
    scan = deletion_sync.open_scan(LOGGER, handle, False)
    assert deletion_sync.judge_asset(LOGGER, scan, asset(), [(path, 1)]) == Verdict.PROCEED


def test_partial_live_photo_proceeds(tmp_path: Path, handle: manifest.ManifestHandle) -> None:
    a = make_file(tmp_path, "IMG_1.JPG")
    b = make_file(tmp_path, "IMG_1.MOV")
    record(handle, a)
    record(handle, b)
    os.remove(b)
    scan = deletion_sync.open_scan(LOGGER, handle, False)
    verdict = deletion_sync.judge_asset(LOGGER, scan, asset(), [(a, 1), (b, 1)])
    assert verdict == Verdict.PROCEED
    assert missing_since(handle) == [None, None]


def test_fully_missing_is_suspect_then_candidate(
    tmp_path: Path, handle: manifest.ManifestHandle
) -> None:
    path = make_file(tmp_path, "IMG_1.JPG")
    record(handle, path)
    os.remove(path)
    scan1 = deletion_sync.open_scan(LOGGER, handle, False)
    assert deletion_sync.judge_asset(LOGGER, scan1, asset(), [(path, 1)]) == Verdict.SUSPECT
    complete(handle, scan1.scan_seq)
    scan2 = deletion_sync.open_scan(LOGGER, handle, False)
    assert deletion_sync.judge_asset(LOGGER, scan2, asset(), [(path, 1)]) == Verdict.CANDIDATE
    assert "REC1" in scan2.candidates


def test_incomplete_scan_does_not_advance(tmp_path: Path, handle: manifest.ManifestHandle) -> None:
    path = make_file(tmp_path, "IMG_1.JPG")
    record(handle, path)
    os.remove(path)
    scan1 = deletion_sync.open_scan(LOGGER, handle, False)
    assert deletion_sync.judge_asset(LOGGER, scan1, asset(), [(path, 1)]) == Verdict.SUSPECT
    scan2 = deletion_sync.open_scan(LOGGER, handle, False)
    assert scan2.scan_seq == 2
    assert deletion_sync.judge_asset(LOGGER, scan2, asset(), [(path, 1)]) == Verdict.SUSPECT
    assert missing_since(handle) == [2]
    complete(handle, 2)
    scan3 = deletion_sync.open_scan(LOGGER, handle, False)
    assert deletion_sync.judge_asset(LOGGER, scan3, asset(), [(path, 1)]) == Verdict.CANDIDATE


def test_path_change_never_candidate(tmp_path: Path, handle: manifest.ManifestHandle) -> None:
    old = str(tmp_path / "old" / "IMG_1.JPG")
    new = str(tmp_path / "new" / "IMG_1.JPG")
    record(handle, old)
    for _ in range(3):
        scan = deletion_sync.open_scan(LOGGER, handle, False)
        assert deletion_sync.judge_asset(LOGGER, scan, asset(), [(new, 1)]) == Verdict.PROCEED
        complete(handle, scan.scan_seq)


def test_suffix_variant_matches(tmp_path: Path, handle: manifest.ManifestHandle) -> None:
    planned = str(tmp_path / "IMG_1.JPG")
    recorded = str(tmp_path / "IMG_1-123.JPG")
    record(handle, recorded)
    scan1 = deletion_sync.open_scan(LOGGER, handle, False)
    assert deletion_sync.judge_asset(LOGGER, scan1, asset(), [(planned, 123)]) == Verdict.SUSPECT
    complete(handle, scan1.scan_seq)
    scan2 = deletion_sync.open_scan(LOGGER, handle, False)
    assert deletion_sync.judge_asset(LOGGER, scan2, asset(), [(planned, 123)]) == Verdict.CANDIDATE


def test_reappeared_clears_mark(tmp_path: Path, handle: manifest.ManifestHandle) -> None:
    path = make_file(tmp_path, "IMG_1.JPG")
    record(handle, path)
    os.remove(path)
    scan1 = deletion_sync.open_scan(LOGGER, handle, False)
    assert deletion_sync.judge_asset(LOGGER, scan1, asset(), [(path, 1)]) == Verdict.SUSPECT
    assert missing_since(handle) == [1]
    Path(path).write_bytes(b"x")
    scan2 = deletion_sync.open_scan(LOGGER, handle, False)
    assert deletion_sync.judge_asset(LOGGER, scan2, asset(), [(path, 1)]) == Verdict.PROCEED
    assert missing_since(handle) == [None]


def test_held_item_skips_and_records_seen(tmp_path: Path, handle: manifest.ManifestHandle) -> None:
    path = str(tmp_path / "IMG_1.JPG")
    record(handle, path)
    add_item(handle, "held")
    scan = deletion_sync.open_scan(LOGGER, handle, False)
    assert deletion_sync.judge_asset(LOGGER, scan, asset(tag="NEW"), [(path, 1)]) == Verdict.HELD
    assert "REC1" in scan.seen
    tag = handle.connection.execute("SELECT record_change_tag FROM deletion_items").fetchone()[0]
    assert tag == "NEW"


def test_held_item_reappeared_locally_is_dropped(
    tmp_path: Path, handle: manifest.ManifestHandle
) -> None:
    path = make_file(tmp_path, "IMG_1.JPG")
    record(handle, path)
    add_item(handle, "held")
    scan = deletion_sync.open_scan(LOGGER, handle, False)
    assert deletion_sync.judge_asset(LOGGER, scan, asset(), [(path, 1)]) == Verdict.PROCEED
    assert item_count(handle) == 0


def test_rejected_item_proceeds(tmp_path: Path, handle: manifest.ManifestHandle) -> None:
    path = str(tmp_path / "IMG_1.JPG")
    record(handle, path)
    add_item(handle, "rejected")
    scan = deletion_sync.open_scan(LOGGER, handle, False)
    assert deletion_sync.judge_asset(LOGGER, scan, asset(), [(path, 1)]) == Verdict.PROCEED
    assert item_count(handle) == 1
    Path(path).write_bytes(b"x")
    assert deletion_sync.judge_asset(LOGGER, scan, asset(), [(path, 1)]) == Verdict.PROCEED
    assert item_count(handle) == 0


def test_same_asset_twice_in_one_scan(tmp_path: Path, handle: manifest.ManifestHandle) -> None:
    path = str(tmp_path / "IMG_1.JPG")
    record(handle, path)
    scan1 = deletion_sync.open_scan(LOGGER, handle, False)
    for _ in range(2):
        assert deletion_sync.judge_asset(LOGGER, scan1, asset(), [(path, 1)]) == Verdict.SUSPECT
    assert missing_since(handle) == [1]
    complete(handle, 1)
    scan2 = deletion_sync.open_scan(LOGGER, handle, False)
    for _ in range(2):
        assert deletion_sync.judge_asset(LOGGER, scan2, asset(), [(path, 1)]) == Verdict.CANDIDATE
    assert len(scan2.candidates) == 1


def test_dry_run_writes_nothing(tmp_path: Path, handle: manifest.ManifestHandle) -> None:
    path = str(tmp_path / "IMG_1.JPG")
    record(handle, path)
    deletion_sync.ensure_schema(handle.connection)
    before = list(handle.connection.iterdump())
    scan = deletion_sync.open_scan(LOGGER, handle, True)
    assert scan.scan_seq == 1
    assert deletion_sync.judge_asset(LOGGER, scan, asset(), [(path, 1)]) == Verdict.SUSPECT
    assert list(handle.connection.iterdump()) == before


def test_migrates_old_db(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "old.db"))
    conn.executescript(
        """
        CREATE TABLE downloaded_assets (
            record_name TEXT NOT NULL, local_path TEXT NOT NULL, size_bytes INTEGER NOT NULL,
            checksum TEXT NULL, first_downloaded_utc TEXT NOT NULL, last_seen_utc TEXT NOT NULL,
            PRIMARY KEY (record_name, local_path));
        INSERT INTO downloaded_assets VALUES ('R', '/p', 1, NULL, 'a', 'b');
        """
    )
    for _ in range(2):
        deletion_sync.ensure_schema(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(downloaded_assets)")]
    assert "missing_since_scan" in cols
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"deletion_items", "deletion_state"} <= names
    assert conn.execute("SELECT COUNT(*) FROM deletion_state").fetchone()[0] == 1
    assert conn.execute("SELECT record_name, local_path FROM downloaded_assets").fetchall() == [
        ("R", "/p")
    ]


def test_list_items(handle: manifest.ManifestHandle) -> None:
    add_item(handle, "held")
    add_item(handle, "rejected", "REC2")
    items = deletion_sync.list_items(handle.connection, [ItemStatus.HELD])
    assert [(i.record_name, i.status) for i in items] == [("REC1", ItemStatus.HELD)]


def test_sqlite_failure_raises(tmp_path: Path, handle: manifest.ManifestHandle) -> None:
    path = str(tmp_path / "IMG_1.JPG")
    record(handle, path)
    scan = deletion_sync.open_scan(LOGGER, handle, False)
    handle.connection.close()
    with pytest.raises(DeletionSyncError):
        deletion_sync.judge_asset(LOGGER, scan, asset(), [(path, 1)])
