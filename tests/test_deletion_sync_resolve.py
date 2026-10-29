import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Sequence
from unittest.mock import patch

import pytest
import yaml as _yaml

import icloudpd.cli as cli_module
from icloudpd import deletion_sync, manifest
from icloudpd.cli import parse
from icloudpd.config import UserConfig
from icloudpd.deletion_sync import DeletionCommand, ItemStatus, Verdict
from tests.test_deletion_sync_state import asset

LOGGER = logging.getLogger("test_deletion_sync_resolve")


def seed(directory: Path, missing_file: str = "gone.jpg") -> str:
    """Create a state.db with two held items; return its path."""
    handle = manifest.open(LOGGER, str(directory))
    assert handle is not None
    deletion_sync.ensure_schema(handle.connection)
    conn = handle.connection
    for rec in ("REC1", "REC2"):
        manifest.record_seen(LOGGER, handle, rec, str(directory / f"{rec}-{missing_file}"), 1)
        conn.execute(
            "INSERT INTO deletion_items (record_name, filename, asset_date_utc, detected_utc,"
            " status, status_changed_utc) VALUES (?, ?, '2024-01-02T00:00:00+00:00',"
            " '2026-10-01T00:00:00+00:00', 'held', '2026-10-01T00:00:00+00:00')",
            (rec, f"{rec}.JPG"),
        )
    conn.execute("UPDATE downloaded_assets SET missing_since_scan = 1")
    conn.execute("UPDATE deletion_state SET tripped = 1, tripped_utc = 'x'")
    conn.commit()
    handle.connection.close()
    return manifest.db_path(str(directory), None)


def user(directory: Path, name: str = "a", library: str = "PrimarySync") -> UserConfig:
    return parse(["-u", name, "-d", str(directory), "--library", library])[1][0]


def statuses(path: str) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [
            r[0] for r in conn.execute("SELECT status FROM deletion_items ORDER BY record_name")
        ]
    finally:
        conn.close()


def scalar(path: str, sql: str) -> object:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def run_cli(args: Sequence[str]) -> int:
    old = sys.argv
    sys.argv = ["icloudpd", *args]
    try:
        return cli_module.cli()
    finally:
        sys.argv = old


def test_list_prints_batch_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = seed(tmp_path)
    code = deletion_sync.run_command(DeletionCommand("list", "a", "PrimarySync"), [user(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "REC1.JPG" in out and "REC2.JPG" in out
    assert statuses(path) == ["held", "held"]
    assert scalar(path, "SELECT tripped FROM deletion_state") == 1


def test_approve_marks_approved_and_clears_trip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = seed(tmp_path)
    code = deletion_sync.run_command(
        DeletionCommand("approve", "a", "PrimarySync"), [user(tmp_path)]
    )
    assert code == 0
    assert "Approved 2" in capsys.readouterr().out
    assert statuses(path) == ["approved", "approved"]
    assert scalar(path, "SELECT tripped FROM deletion_state") == 0
    stamp = str(scalar(path, "SELECT MIN(status_changed_utc) FROM deletion_items"))
    assert stamp.endswith("+00:00") and stamp > "2026-10-01T00:00:00+00:00"


def test_reject_makes_asset_redownload(tmp_path: Path) -> None:
    path = seed(tmp_path)
    code = deletion_sync.run_command(
        DeletionCommand("reject", "a", "PrimarySync"), [user(tmp_path)]
    )
    assert code == 0
    assert statuses(path) == ["rejected", "rejected"]
    assert scalar(path, "SELECT tripped FROM deletion_state") == 0
    assert scalar(path, "SELECT COUNT(missing_since_scan) FROM downloaded_assets") == 0
    handle = manifest.open(LOGGER, str(tmp_path))
    assert handle is not None
    scan = deletion_sync.open_scan(LOGGER, handle, dry_run=False)
    planned = [(str(tmp_path / "REC1-gone.jpg"), 1)]
    assert deletion_sync.judge_asset(LOGGER, scan, asset("REC1"), planned) is Verdict.PROCEED
    handle.connection.close()


def test_no_held_items(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = seed(tmp_path)
    deletion_sync.run_command(DeletionCommand("approve", "a", "PrimarySync"), [user(tmp_path)])
    capsys.readouterr()
    code = deletion_sync.run_command(
        DeletionCommand("approve", "a", "PrimarySync"), [user(tmp_path)]
    )
    assert code == 0
    assert "No held" in capsys.readouterr().out
    assert statuses(path) == ["approved", "approved"]


def test_no_db_creates_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = deletion_sync.run_command(
        DeletionCommand("approve", "a", "PrimarySync"), [user(tmp_path)]
    )
    assert code == 0
    assert "No held deletion batch" in capsys.readouterr().out
    assert not os.path.exists(manifest.db_path(str(tmp_path), None))
    assert not (tmp_path / ".icloudpd").exists()


def test_selector_no_match(tmp_path: Path) -> None:
    assert (
        deletion_sync.run_command(DeletionCommand("list", "zzz", "PrimarySync"), [user(tmp_path)])
        == 2
    )
    assert (
        deletion_sync.run_command(DeletionCommand("list", "a", "SharedSync-X"), [user(tmp_path)])
        == 2
    )


def test_selector_ambiguous(tmp_path: Path) -> None:
    users = [user(tmp_path / "1"), user(tmp_path / "2")]
    assert deletion_sync.run_command(DeletionCommand("list", "a", "PrimarySync"), users) == 2


def test_works_with_config_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    seed(tmp_path / "p")
    shared = tmp_path / "s"
    seed(shared, missing_file="shared.jpg")
    conn = sqlite3.connect(manifest.db_path(str(shared), None))
    conn.execute("DELETE FROM deletion_items WHERE record_name = 'REC2'")
    conn.commit()
    conn.close()
    config = tmp_path / "config.yaml"
    config.write_text(
        _yaml.safe_dump(
            {
                "users": [
                    {"username": "a", "directory": str(tmp_path / "p")},
                    {"username": "a", "directory": str(shared), "library": "SharedSync-X"},
                ]
            }
        )
    )
    code = run_cli(
        [
            "--config",
            str(config),
            "--for-username",
            "a",
            "--for-library",
            "SharedSync-X",
            "--list-pending-deletions",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "REC1.JPG" in out and "REC2.JPG" not in out


def test_works_with_plain_cli_users(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    seed(tmp_path)
    code = run_cli(
        ["-u", "a", "-d", str(tmp_path), "--for-username", "a", "--list-pending-deletions"]
    )
    assert code == 0
    assert "REC1.JPG" in capsys.readouterr().out


def test_flags_mutually_exclusive(tmp_path: Path) -> None:
    base = ["-u", "a", "-d", str(tmp_path), "--for-username", "a"]
    assert run_cli([*base, "--list-pending-deletions", "--resolve-deletions", "approve"]) == 2
    assert run_cli(["-u", "a", "-d", str(tmp_path), "--list-pending-deletions"]) == 2
    assert run_cli(["-u", "a", "-d", str(tmp_path), "--resolve-deletions", "reject"]) == 2


def test_command_not_configurable(tmp_path: Path) -> None:
    from icloudpd.config_defaults import GLOBAL_OPTION_DEFAULTS

    assert "deletion_command" not in GLOBAL_OPTION_DEFAULTS
    global_config, _ = parse(["-u", "a", "-d", "/x"])
    assert global_config.deletion_command is None


def test_busy_db_fails_cleanly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = seed(tmp_path)
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with patch.object(deletion_sync, "_BUSY_TIMEOUT_SECONDS", 0.1):
            code = deletion_sync.run_command(
                DeletionCommand("approve", "a", "PrimarySync"), [user(tmp_path)]
            )
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert code == 1
    assert "busy" in capsys.readouterr().out
    assert statuses(path) == ["held", "held"]
    assert scalar(path, "SELECT tripped FROM deletion_state") == 1


def test_resolve_acts_only_on_shown_items_under_race(tmp_path: Path) -> None:
    path = seed(tmp_path)
    conn = sqlite3.connect(path)
    shown = [i.record_name for i in deletion_sync.list_items(conn, [ItemStatus.HELD])]
    other = sqlite3.connect(path)
    other.execute("UPDATE deletion_items SET status = 'deleted' WHERE record_name = 'REC2'")
    other.execute(
        "INSERT INTO deletion_items (record_name, filename, asset_date_utc, detected_utc,"
        " status, status_changed_utc) VALUES ('REC3', 'REC3.JPG', 'd', 'd', 'held', 'd')"
    )
    other.commit()
    other.close()
    changed = deletion_sync.resolve(conn, "approve", shown)
    conn.close()
    assert [i.record_name for i in changed] == ["REC1"]
    assert statuses(path) == ["approved", "deleted", "held"]
    assert scalar(path, "SELECT tripped FROM deletion_state") == 1


def test_reject_race_clears_marks_only_for_changed(tmp_path: Path) -> None:
    path = seed(tmp_path)
    conn = sqlite3.connect(path)
    other = sqlite3.connect(path)
    other.execute("UPDATE deletion_items SET status = 'approved' WHERE record_name = 'REC2'")
    other.commit()
    other.close()
    changed = deletion_sync.resolve(conn, "reject", ["REC1", "REC2"])
    conn.close()
    assert [i.record_name for i in changed] == ["REC1"]
    assert (
        scalar(path, "SELECT COUNT(*) FROM downloaded_assets WHERE missing_since_scan IS NULL") == 1
    )
    assert (
        scalar(path, "SELECT record_name FROM downloaded_assets WHERE missing_since_scan IS NULL")
        == "REC1"
    )


def test_list_does_not_touch_legacy_db(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    handle = manifest.open(LOGGER, str(tmp_path))
    assert handle is not None
    handle.connection.close()
    path = manifest.db_path(str(tmp_path), None)
    before = Path(path).read_bytes()
    code = deletion_sync.run_command(DeletionCommand("list", "a", "PrimarySync"), [user(tmp_path)])
    assert code == 0
    assert "No held deletion batch" in capsys.readouterr().out
    assert Path(path).read_bytes() == before


def test_selector_counts_before_directory_filter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    one = user(tmp_path)
    nodir = user(tmp_path)
    nodir.directory = ""
    cmd = DeletionCommand("list", "a", "PrimarySync")
    assert deletion_sync.run_command(cmd, [nodir]) == 2
    assert "no directory" in capsys.readouterr().out
    assert deletion_sync.run_command(cmd, [one, nodir]) == 2
    assert "selection must be unique" in capsys.readouterr().out


def test_for_library_defaults_to_primary_via_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(tmp_path)
    code = run_cli(
        ["-u", "a", "-d", str(tmp_path), "--for-username", "a", "--list-pending-deletions"]
    )
    assert code == 0
    assert "REC1.JPG" in capsys.readouterr().out
    code = run_cli(
        [
            "-u",
            "a",
            "-d",
            str(tmp_path),
            "--for-username",
            "a",
            "--for-library",
            "Other",
            "--list-pending-deletions",
        ]
    )
    assert code == 2


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_other_statuses_untouched(tmp_path: Path, action: str) -> None:
    path = seed(tmp_path)
    conn = sqlite3.connect(path)
    others = ["approved", "deleted", "failed", "skipped_gone", "skipped_reappeared"]
    for n, st in enumerate(others):
        conn.execute(
            "INSERT INTO deletion_items (record_name, filename, asset_date_utc, detected_utc,"
            " status, status_changed_utc) VALUES (?, 'f', 'd', 'd', ?, 'old')",
            (f"X{n}", st),
        )
    conn.commit()
    conn.close()
    code = deletion_sync.run_command(
        DeletionCommand(action, "a", "PrimarySync"),  # type: ignore[arg-type]
        [user(tmp_path)],
    )
    assert code == 0
    rows = (
        sqlite3.connect(path)
        .execute(
            "SELECT status, status_changed_utc FROM deletion_items WHERE record_name LIKE 'X%'"
            " ORDER BY record_name"
        )
        .fetchall()
    )
    assert rows == [(st, "old") for st in others]


@pytest.mark.parametrize("tilde", ["state_directory"])
def test_resolver_expands_tilde(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tilde: str,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)  # a literal "~/..." would resolve under here
    seed_dir = home / "lib"
    seed_dir.mkdir(parents=True)
    path = seed(seed_dir)
    if tilde == "state_directory":
        state = home / "st"
        state.mkdir()
        os.replace(path, state / "state.db")
        path = str(state / "state.db")
        args = ["-d", str(seed_dir), "--state-directory", "~/st"]
    else:
        args = ["-d", "~/lib"]
    users = parse(["-u", "a", *args])[1]
    assert deletion_sync.run_command(DeletionCommand("list", "a"), users) == 0
    assert "2 held deletion(s):" in capsys.readouterr().out
    assert deletion_sync.run_command(DeletionCommand("approve", "a"), users) == 0
    assert statuses(path) == ["approved", "approved"]


def test_library_paths() -> None:
    """directory is taken literally, as on master; only state_directory expands ~."""
    home = os.path.expanduser("~")
    assert manifest.library_paths("~/lib/", "~/st/../st") == (
        os.path.join("~", "lib"),
        os.path.join(home, "st"),
    )
    assert manifest.library_paths("/data//you", None) == ("/data/you", None)


def seed_part1(directory: Path) -> str:
    """A held batch in a Part 1 database: deletion_items has no keep_marked column."""
    path = seed(directory)
    conn = sqlite3.connect(path)
    try:
        conn.execute("ALTER TABLE deletion_items DROP COLUMN keep_marked")
        conn.commit()
    finally:
        conn.close()
    return path


def columns(path: str) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [r[1] for r in conn.execute("PRAGMA table_info(deletion_items)")]
    finally:
        conn.close()


def test_list_works_on_part1_db_without_migrating(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = seed_part1(tmp_path)
    before = Path(path).read_bytes()
    code = deletion_sync.run_command(DeletionCommand("list", "a", "PrimarySync"), [user(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "2 held deletion(s):" in out
    assert "REC1.JPG" in out and "REC2.JPG" in out
    assert Path(path).read_bytes() == before
    assert "keep_marked" not in columns(path)


@pytest.mark.parametrize("action,status", [("approve", "approved"), ("reject", "rejected")])
def test_approve_and_reject_work_on_part1_db(tmp_path: Path, action: str, status: str) -> None:
    path = seed_part1(tmp_path)
    command = DeletionCommand(action, "a", "PrimarySync")  # type: ignore[arg-type]
    assert deletion_sync.run_command(command, [user(tmp_path)]) == 0
    assert statuses(path) == [status, status]


def test_resolve_split_overlap_rejects(tmp_path: Path) -> None:
    """A name in both lists is rejected: the safe choice in a deletion tool."""
    path = seed(tmp_path)
    conn = sqlite3.connect(path)
    try:
        approved, rejected = deletion_sync.resolve_split(conn, ["REC1", "REC2"], ["REC1"])
    finally:
        conn.close()
    assert [i.record_name for i in approved] == ["REC2"]
    assert [i.record_name for i in rejected] == ["REC1"]
    assert statuses(path) == ["rejected", "approved"]
