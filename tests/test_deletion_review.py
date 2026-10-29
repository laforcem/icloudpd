import logging
import re
import sqlite3
from pathlib import Path

import pytest

from icloudpd import deletion_review, deletion_sync, manifest
from icloudpd.deletion_review import Busy, StaleBatch
from icloudpd.deletion_sync import ItemStatus

LOGGER = logging.getLogger("test_deletion_review")


def make_db(directory: Path) -> sqlite3.Connection:
    handle = manifest.open(LOGGER, str(directory))
    assert handle is not None
    deletion_sync.ensure_schema(handle.connection)
    return handle.connection


def add(
    conn: sqlite3.Connection,
    rec: str,
    status: str = "held",
    detected: str = "2026-10-01T00:00:00+00:00",
) -> None:
    conn.execute(
        "INSERT INTO deletion_items (record_name, filename, asset_date_utc, detected_utc,"
        " status, status_changed_utc) VALUES (?, ?, '2024-01-02T00:00:00+00:00', ?, ?, ?)",
        (rec, f"{rec}.JPG", detected, status, detected),
    )
    conn.commit()


def seed(conn: sqlite3.Connection, count: int) -> list[str]:
    names = [f"REC{i:02d}" for i in range(count)]
    for n in names:
        manifest.record_seen(LOGGER, manifest.ManifestHandle(connection=conn), n, f"/x/{n}", 1)
        add(conn, n)
    conn.execute("UPDATE downloaded_assets SET missing_since_scan = 1")
    conn.execute("UPDATE deletion_state SET tripped = 1, tripped_utc = 'x'")
    conn.commit()
    return names


def status_of(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT record_name, status FROM deletion_items"))


def marks(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute("SELECT COALESCE(SUM(keep_marked), 0) FROM deletion_items").fetchone()[0]
    )


def test_entry_key_shape_and_stability() -> None:
    key = deletion_review.entry_key("a", "PrimarySync")
    assert re.fullmatch(r"[0-9a-f]{8}", key)
    assert key == deletion_review.entry_key("a", "PrimarySync")
    assert key != deletion_review.entry_key("a", "SharedSync-x")


def test_batch_token_changes_when_batch_changes(tmp_path: Path) -> None:
    conn = make_db(tmp_path)
    add(conn, "A")
    first = deletion_review.batch_token(conn)
    assert re.fullmatch(r"[0-9a-f]{8}", first)
    add(conn, "B")
    second = deletion_review.batch_token(conn)
    assert second != first
    add(conn, "C", status="approved")
    assert deletion_review.batch_token(conn) == second


def test_batch_token_empty_is_blank(tmp_path: Path) -> None:
    conn = make_db(tmp_path)
    assert deletion_review.batch_token(conn) == ""


def test_held_page_numbers_and_order(tmp_path: Path) -> None:
    conn = make_db(tmp_path)
    for i in range(23):
        add(conn, f"R{i:02d}", detected=f"2026-10-01T00:00:{i:02d}+00:00")
    add(conn, "ZZ", status="approved")
    add(conn, "tie1", detected="2026-10-01T00:00:00+00:00")  # 24 held; ties with R00
    first = deletion_review.held_page(conn, 1)
    second = deletion_review.held_page(conn, 2)
    last = deletion_review.held_page(conn, 3)
    assert (second.pages, second.total, second.page) == (3, 24, 2)
    assert second.items[0].number == 11
    assert second.batch_token == deletion_review.batch_token(conn)
    assert [i.record_name for i in first.items[:2]] == ["R00", "tie1"]
    assert len(first.items) == 10 and first.items[0].number == 1
    assert len(last.items) == 4
    shown = [i.record_name for p in (first, second, last) for i in p.items]
    assert "ZZ" not in shown and len(shown) == 24
    out = deletion_review.held_page(conn, 9)
    assert out.items == [] and out.pages == 3


def test_set_keep_marks_and_counts(tmp_path: Path) -> None:
    conn = make_db(tmp_path)
    seed(conn, 3)
    token = deletion_review.batch_token(conn)
    assert deletion_review.set_keep(conn, "REC01", True, token) == (3, 1)
    page = deletion_review.held_page(conn, 1)
    assert page.kept_count == 1
    assert [i.keep for i in page.items] == [False, True, False]
    assert deletion_review.set_keep(conn, "REC01", False, token) == (3, 0)


def test_set_keep_unknown_or_not_held_record(tmp_path: Path) -> None:
    conn = make_db(tmp_path)
    add(conn, "A")
    add(conn, "B", status="approved")
    token = deletion_review.batch_token(conn)
    with pytest.raises(KeyError):
        deletion_review.set_keep(conn, "NOPE", True, token)
    with pytest.raises(KeyError):
        deletion_review.set_keep(conn, "B", True, token)


def test_apply_marks_split(tmp_path: Path) -> None:
    conn = make_db(tmp_path)
    names = seed(conn, 5)
    token = deletion_review.batch_token(conn)
    deletion_review.set_keep(conn, names[0], True, token)
    deletion_review.set_keep(conn, names[3], True, token)
    assert deletion_review.apply_review(conn, "apply", token) == (3, 2)
    statuses = status_of(conn)
    assert statuses[names[0]] == statuses[names[3]] == "rejected"
    assert [statuses[n] for n in (names[1], names[2], names[4])] == ["approved"] * 3
    missing = dict(conn.execute("SELECT record_name, missing_since_scan FROM downloaded_assets"))
    assert missing[names[0]] is None and missing[names[3]] is None
    assert missing[names[1]] == 1
    assert conn.execute("SELECT tripped FROM deletion_state").fetchone()[0] == 0
    assert marks(conn) == 0


def test_keep_all_rejects_everything(tmp_path: Path) -> None:
    conn = make_db(tmp_path)
    seed(conn, 4)
    token = deletion_review.batch_token(conn)
    assert deletion_review.apply_review(conn, "keep_all", token) == (0, 4)
    assert set(status_of(conn).values()) == {"rejected"}
    assert conn.execute("SELECT tripped FROM deletion_state").fetchone()[0] == 0


def test_stale_token_changes_nothing(tmp_path: Path) -> None:
    conn = make_db(tmp_path)
    names = seed(conn, 3)
    token = deletion_review.batch_token(conn)
    add(conn, "LATE")
    before = status_of(conn)
    with pytest.raises(StaleBatch) as info:
        deletion_review.apply_review(conn, "apply", token)
    assert info.value.batch_token == deletion_review.batch_token(conn) != token
    with pytest.raises(StaleBatch):
        deletion_review.set_keep(conn, names[0], True, token)
    assert status_of(conn) == before
    assert marks(conn) == 0


def test_busy_raises_busy(tmp_path: Path) -> None:
    conn = make_db(tmp_path)
    names = seed(conn, 2)
    token = deletion_review.batch_token(conn)
    path = manifest.db_path(str(tmp_path), None)
    other = sqlite3.connect(path, timeout=0.1)
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(Busy):
            deletion_review.set_keep(other, names[0], True, token)
        with pytest.raises(Busy):
            deletion_review.apply_review(other, "apply", token)
    finally:
        holder.execute("ROLLBACK")
        holder.close()
        other.close()


def test_migration_adds_keep_marked(tmp_path: Path) -> None:
    conn = make_db(tmp_path)
    conn.execute("ALTER TABLE deletion_items DROP COLUMN keep_marked")
    conn.execute(
        "INSERT INTO deletion_items (record_name, filename, asset_date_utc, detected_utc,"
        " status, status_changed_utc) VALUES ('A', 'A.JPG', 'd', 'd', 'held', 'd')"
    )
    conn.commit()
    assert "keep_marked" not in [r[1] for r in conn.execute("PRAGMA table_info(deletion_items)")]
    deletion_sync.ensure_schema(conn)
    deletion_sync.ensure_schema(conn)
    assert "keep_marked" in [r[1] for r in conn.execute("PRAGMA table_info(deletion_items)")]
    (item,) = deletion_sync.list_items(conn, [ItemStatus.HELD])
    assert item.keep_marked is False


def test_cli_resolver_ignores_marks(tmp_path: Path) -> None:
    conn = make_db(tmp_path)
    names = seed(conn, 3)
    token = deletion_review.batch_token(conn)
    deletion_review.set_keep(conn, names[0], True, token)
    changed = deletion_sync.resolve(conn, "approve", names)
    assert len(changed) == 3
    assert set(status_of(conn).values()) == {"approved"}
    assert marks(conn) == 0
