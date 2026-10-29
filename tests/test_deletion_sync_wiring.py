"""Deletion detection wired into the real download loop (cassette-driven).

These call cli.parse + base.run_with_configs rather than cli(): the cassettes
only support --recent, which cli() and run_with_configs reject together with
--sync-deletions; _Library.run patches out just that check.
"""

import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterator, Sequence
from unittest.mock import patch

import pytest
from vcr import VCR

from icloudpd import base, cli, deletion_sync, manifest, mount_guard
from icloudpd.status import StatusExchange
from tests.helpers import DEFAULT_ENV, create_files, path_from_project_root

vcr = VCR(decode_compressed_response=True, record_mode="none")

_ROOT = path_from_project_root(__file__)
_DELETED = os.path.join("2018", "07", "31", "IMG_7409.JPG")


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key, value in DEFAULT_ENV.items():
        if value is not None:
            monkeypatch.setenv(key, value)
    mount_guard.reset()
    with patch("icloudpd.notifications.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""
        yield
    mount_guard.reset()


class _Library:
    def __init__(self, tmp_path: Path, cassette: str = "listing_photos.yml") -> None:
        self.data_dir = str(tmp_path / "data")
        self.cookie_dir = str(tmp_path / "cookie")
        self.cassette = os.path.join(_ROOT, "vcr_cassettes", cassette)
        os.makedirs(self.data_dir)
        shutil.copytree(os.path.join(_ROOT, "cookie"), self.cookie_dir)

    def mount(self) -> None:
        Path(self.data_dir, ".mounted").write_text("")

    def run(self, params: Sequence[str]) -> int:
        global_config, users = cli.parse(
            [
                "--username",
                "jdoe@gmail.com",
                "--password",
                "password1",
                "--no-progress-bar",
                "--threads-num",
                "1",
                "--notification-script",
                "./test_script.sh",
                "-d",
                self.data_dir,
                "--cookie-directory",
                self.cookie_dir,
                *params,
            ]
        )
        # The cassettes need --recent, which run_with_configs (like cli()) rejects
        # with --sync-deletions; bypass only that check here.
        with (
            vcr.use_cassette(self.cassette),
            patch("icloudpd.base._deletion_sync_config_errors", return_value=[]),
        ):
            return base.run_with_configs(global_config, users)

    def path(self, relative: str) -> str:
        return os.path.join(self.data_dir, relative)

    def db(self) -> "closing[sqlite3.Connection]":
        return closing(sqlite3.connect(manifest.db_path(self.data_dir, None)))

    def scan_state(self) -> tuple[int, int]:
        with self.db() as conn:
            row = conn.execute(
                "SELECT scan_seq, last_completed_scan_seq FROM deletion_state WHERE id = 1"
            ).fetchone()
        return int(row[0]), int(row[1])

    def missing_since(self, relative: str) -> int | None:
        with self.db() as conn:
            row = conn.execute(
                "SELECT missing_since_scan FROM downloaded_assets WHERE local_path = ?",
                (self.path(relative),),
            ).fetchone()
        return None if row is None else row[0]


_LISTING = [
    "--recent",
    "5",
    "--skip-videos",
    "--skip-live-photos",
]
_SYNC = [*_LISTING, "--sync-deletions", "--require-mount-marker"]


def _listing_library(tmp_path: Path) -> _Library:
    library = _Library(tmp_path)
    create_files(
        library.data_dir,
        [("2018/07/30", "IMG_7408.JPG", 1151066), ("2018/07/30", "IMG_7407.JPG", 656257)],
    )
    library.mount()
    return library


def test_deleted_file_not_redownloaded_and_becomes_candidate(tmp_path: Path) -> None:
    library = _listing_library(tmp_path)
    assert library.run(_SYNC) == 0
    assert os.path.isfile(library.path(_DELETED))

    os.remove(library.path(_DELETED))
    assert library.run(_SYNC) == 0
    assert not os.path.isfile(library.path(_DELETED))
    assert library.missing_since(_DELETED) == 2

    completed: list[deletion_sync.DeletionScan] = []
    real_finish = deletion_sync.finish_scan

    def capture(logger: Any, scan: deletion_sync.DeletionScan, **kwargs: Any) -> None:
        completed.append(scan)
        real_finish(logger, scan, **kwargs)

    with (
        patch("icloudpd.deletion_sync.finish_scan", side_effect=capture),
        patch("icloudpd.deletion_sync.delete_asset", return_value=True) as delete_asset,
        patch("icloudpd.notifications.notify", return_value=True) as notify,
    ):
        assert library.run(_SYNC) == 0
    assert not os.path.isfile(library.path(_DELETED))
    assert len(completed) == 1
    assert [p.filename for p in completed[0].candidates.values()] == ["IMG_7409.JPG"]
    assert library.scan_state() == (3, 3)
    assert [c.args[2].filename for c in delete_asset.call_args_list] == ["IMG_7409.JPG"]
    with library.db() as conn:
        items = deletion_sync.list_items(conn, list(deletion_sync.ItemStatus))
        rows = conn.execute(
            "SELECT COUNT(*) FROM downloaded_assets WHERE local_path = ?",
            (library.path(_DELETED),),
        ).fetchone()[0]
    assert [(i.filename, i.status) for i in items] == [
        ("IMG_7409.JPG", deletion_sync.ItemStatus.DELETED)
    ]
    assert rows == 0
    events = [c.args[2] for c in notify.call_args_list]
    summaries = [e for e in events if e.event_type == "deletion_sync_summary"]
    assert len(summaries) == 1
    assert summaries[0].username == "jdoe@gmail.com"
    assert summaries[0].data["deleted_count"] == 1
    assert summaries[0].data["library"] == "PrimarySync"
    assert summaries[0].data["directory"] == os.path.normpath(library.data_dir)


@pytest.mark.parametrize(
    ("existing", "recorded"),
    [
        # Default policy (name-size-dedup-with-suffix): the plain name holds a
        # different-sized file, so the asset lives at the -<size> path.
        (
            [("IMG_7408.JPG", 999), ("IMG_7408-1151066.JPG", 1151066)],
            "IMG_7408-1151066.JPG",
        ),
        # Legacy -original name from older icloudpd versions.
        ([("IMG_7408-original.JPG", 1151066)], "IMG_7408-original.JPG"),
    ],
    ids=["dedup-suffix", "legacy-original"],
)
def test_variant_path_becomes_candidate(
    tmp_path: Path, existing: list[tuple[str, int]], recorded: str
) -> None:
    library = _Library(tmp_path)
    create_files(
        library.data_dir,
        [("2018/07/30", name, size) for name, size in existing]
        + [("2018/07/30", "IMG_7407.JPG", 656257)],
    )
    library.mount()
    recorded_path = os.path.join("2018", "07", "30", recorded)
    assert library.run(_SYNC) == 0
    assert library.missing_since(recorded_path) is None
    with library.db() as conn:
        rows = conn.execute(
            "SELECT local_path FROM downloaded_assets WHERE local_path LIKE ?",
            ("%IMG_7408%",),
        ).fetchall()
    assert rows == [(library.path(recorded_path),)]

    os.remove(library.path(recorded_path))
    # The cassette has no IMG_7408 download, so a re-download attempt would fail the run.
    assert library.run(_SYNC) == 0
    assert library.missing_since(recorded_path) == 2

    completed: list[deletion_sync.DeletionScan] = []
    real_finish = deletion_sync.finish_scan

    def capture(logger: Any, scan: deletion_sync.DeletionScan, **kwargs: Any) -> None:
        completed.append(scan)
        real_finish(logger, scan, **kwargs)

    with (
        patch("icloudpd.deletion_sync.finish_scan", side_effect=capture),
        patch("icloudpd.deletion_sync.delete_asset", return_value=True),
    ):
        assert library.run(_SYNC) == 0
    assert not os.path.isfile(library.path(recorded_path))
    assert [p.filename for p in completed[0].candidates.values()] == ["IMG_7408.JPG"]


def test_sync_off_redownloads(tmp_path: Path) -> None:
    library = _listing_library(tmp_path)
    assert library.run(_LISTING) == 0
    os.remove(library.path(_DELETED))
    assert library.run(_LISTING) == 0
    assert os.path.isfile(library.path(_DELETED))


def test_cancelled_scan_not_completed(tmp_path: Path) -> None:
    library = _listing_library(tmp_path)
    exchanges: list[StatusExchange] = []

    def make_exchange() -> StatusExchange:
        exchanges.append(StatusExchange())
        return exchanges[-1]

    real_where = base.where_builder

    def cancelling_where(*args: Any) -> bool:
        exchanges[-1].get_progress().cancel = True
        return real_where(*args)

    with (
        patch("icloudpd.base.StatusExchange", side_effect=make_exchange),
        patch("icloudpd.base.where_builder", side_effect=cancelling_where),
        patch("icloudpd.deletion_sync.finish_scan") as finish_scan,
    ):
        assert library.run(_SYNC) == 0
    finish_scan.assert_not_called()
    assert library.scan_state() == (1, 0)


def test_missing_marker_detects_nothing(tmp_path: Path) -> None:
    library = _listing_library(tmp_path)
    os.remove(os.path.join(library.data_dir, ".mounted"))
    with patch("icloudpd.deletion_sync.open_scan") as open_scan:
        assert library.run(_SYNC) != 0
    open_scan.assert_not_called()
    assert not os.path.isfile(library.path(_DELETED))


def test_manifest_unavailable_skips_user(tmp_path: Path) -> None:
    library = _listing_library(tmp_path)
    with patch("icloudpd.manifest.open", return_value=None):
        assert library.run(_SYNC) != 0
    assert not os.path.isfile(library.path(_DELETED))


def test_planned_paths_match_download(tmp_path: Path) -> None:
    library = _Library(tmp_path, "download_live_photos.yml")
    library.mount()
    planned: list[tuple[str, int]] = []
    real_judge = deletion_sync.judge_asset

    def capture(
        logger: Any,
        scan: deletion_sync.DeletionScan,
        photo: Any,
        paths: Sequence[tuple[str, int]],
    ) -> deletion_sync.Verdict:
        planned.extend(paths)
        return real_judge(logger, scan, photo, paths)

    def fake_download(
        _logger: Any, _dry_run: bool, _icloud: Any, _photo: Any, path: str, *_rest: Any
    ) -> bool:
        # The cassette has no medium-size downloads; write a stand-in file instead.
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_bytes(b"x")
        return True

    with (
        patch("icloudpd.deletion_sync.judge_asset", side_effect=capture),
        patch("icloudpd.download.download_media", side_effect=fake_download),
    ):
        exit_code = library.run(
            [
                "--recent",
                "3",
                "--size",
                "original",
                "--size",
                "medium",
                "--sync-deletions",
                "--require-mount-marker",
            ]
        )
    assert exit_code == 0
    with library.db() as conn:
        stored = [r[0] for r in conn.execute("SELECT local_path FROM downloaded_assets")]
    assert stored, "nothing was recorded in the manifest"
    variants = {v for p, s in planned for v in deletion_sync.path_variants(p, s)}
    assert set(stored) <= variants
    assert any(p.endswith("_HEVC.MOV") for p, _ in planned)
    assert any("-medium" in p for p, _ in planned)


def test_deletion_state_error_skips_user(tmp_path: Path) -> None:
    library = _listing_library(tmp_path)
    with patch(
        "icloudpd.deletion_sync.open_scan",
        side_effect=deletion_sync.DeletionSyncError("open_scan: disk I/O error"),
    ):
        assert library.run(_SYNC) == 1
    assert not os.path.isfile(library.path(_DELETED))


def test_threshold_holds_instead_of_deleting(tmp_path: Path) -> None:
    library = _listing_library(tmp_path)
    sync = [*_SYNC, "--deletion-sync-threshold", "1"]
    assert library.run(sync) == 0
    os.remove(library.path(_DELETED))
    assert library.run(sync) == 0
    with (
        patch("icloudpd.deletion_sync.delete_asset") as delete_asset,
        patch("icloudpd.notifications.notify", return_value=True) as notify,
    ):
        assert library.run(sync) == 0
    delete_asset.assert_not_called()
    with library.db() as conn:
        items = deletion_sync.list_items(conn, [deletion_sync.ItemStatus.HELD])
    assert [i.filename for i in items] == ["IMG_7409.JPG"]
    tripped = [
        c.args[2]
        for c in notify.call_args_list
        if c.args[2].event_type == "deletion_sync_threshold_tripped"
    ]
    assert len(tripped) == 1
    assert tripped[0].data["held_count"] == 1
    assert tripped[0].data["library"] == "PrimarySync"
    assert not os.path.isfile(library.path(_DELETED))


def _deletion_state(path: str) -> dict[str, list[Any]]:
    """Everything deletion sync owns. Excludes last_seen_utc, which the manifest refreshes
    for existing files even in dry-run (pre-existing manifest behaviour, not deletion state)."""
    with closing(sqlite3.connect(path)) as conn:
        return {
            "schema": conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall(),
            "items": conn.execute("SELECT * FROM deletion_items ORDER BY record_name").fetchall(),
            "state": conn.execute("SELECT * FROM deletion_state").fetchall(),
            "assets": conn.execute(
                "SELECT record_name, local_path, size_bytes, missing_since_scan"
                " FROM downloaded_assets ORDER BY record_name, local_path"
            ).fetchall(),
        }


@pytest.mark.parametrize("threshold", ["-1", "1"], ids=["would-delete", "would-hold"])
def test_dry_run_leaves_state_db_unchanged(
    tmp_path: Path, threshold: str, caplog: pytest.LogCaptureFixture
) -> None:
    library = _listing_library(tmp_path)
    sync = [*_SYNC, "--deletion-sync-threshold", threshold]
    assert library.run(sync) == 0
    os.remove(library.path(_DELETED))
    assert library.run(sync) == 0  # suspect, scan completed: a candidate from now on
    db = manifest.db_path(library.data_dir, None)
    before = _deletion_state(db)
    with (
        patch("icloudpd.deletion_sync.delete_asset") as delete_asset,
        patch("icloudpd.notifications.notify") as notify,
    ):
        for _ in range(3):
            assert library.run([*sync, "--dry-run"]) == 0
    delete_asset.assert_not_called()
    assert [
        c.args[2].event_type
        for c in notify.call_args_list
        if c.args[2].event_type.startswith("deletion_sync")
    ] == []
    expected = (
        "[DRY RUN] Would delete IMG_7409.JPG"
        if threshold == "-1"
        else "[DRY RUN] Would hold 1 items (threshold 1)"
    )
    assert caplog.text.count(expected) == 3
    after = _deletion_state(db)
    assert after == before
    assert any(row[3] == 2 for row in after["assets"])  # the suspect mark survived
    assert not os.path.isfile(library.path(_DELETED))


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores directory permissions"
)
def test_unreadable_folder_aborts_run(tmp_path: Path) -> None:
    library = _listing_library(tmp_path)
    assert library.run(_SYNC) == 0
    folder = Path(library.data_dir, "2018")
    folder.chmod(0)  # e.g. an ownership/ACL change: the files are still there
    try:
        with patch("icloudpd.deletion_sync.delete_asset") as delete_asset:
            for _ in range(2):
                assert library.run(_SYNC) != 0
    finally:
        folder.chmod(0o755)
    delete_asset.assert_not_called()
    assert os.path.isfile(library.path(_DELETED))
    assert library.missing_since(_DELETED) is None
    assert library.scan_state()[1] == 1
    with library.db() as conn:
        assert deletion_sync.list_items(conn, list(deletion_sync.ItemStatus)) == []


def test_mount_dropping_mid_scan_marks_and_deletes_nothing(tmp_path: Path) -> None:
    library = _listing_library(tmp_path)
    assert library.run(_SYNC) == 0
    os.remove(library.path(_DELETED))
    real_judge = deletion_sync.judge_asset

    def dropping_judge(*args: Any) -> deletion_sync.Verdict:
        marker = os.path.join(library.data_dir, ".mounted")
        if os.path.exists(marker):
            os.remove(marker)
        return real_judge(*args)

    with (
        patch("icloudpd.deletion_sync.judge_asset", side_effect=dropping_judge),
        patch("icloudpd.deletion_sync.delete_asset") as delete_asset,
    ):
        library.run(_SYNC)
    delete_asset.assert_not_called()
    assert library.missing_since(_DELETED) is None
    assert library.scan_state() == (2, 1)
    assert not os.path.isfile(library.path(_DELETED))


_AUTO_DELETE = [
    "--recent",
    "0",
    "--skip-videos",
    "--auto-delete",
    "--sync-deletions",
    "--require-mount-marker",
]


def _seed(library: _Library, record_names: Sequence[str]) -> None:
    with library.db() as conn:
        for name in record_names:
            conn.execute(
                "INSERT OR REPLACE INTO downloaded_assets (record_name, local_path, size_bytes,"
                " first_downloaded_utc, last_seen_utc) VALUES (?, ?, 1, 'a', 'b')",
                (name, library.path(f"{name}.JPG")),
            )
            conn.execute(
                "INSERT OR REPLACE INTO deletion_items (record_name, filename, asset_date_utc,"
                " detected_utc, status, status_changed_utc) VALUES (?, 'f', 'd', 'd', 'held', 'd')",
                (name,),
            )
        conn.commit()


def _known(library: _Library) -> int:
    with library.db() as conn:
        return int(
            conn.execute(
                "SELECT (SELECT COUNT(*) FROM downloaded_assets)"
                " + (SELECT COUNT(*) FROM deletion_items)"
            ).fetchone()[0]
        )


def test_auto_delete_forgets_recently_deleted(tmp_path: Path) -> None:
    library = _Library(tmp_path, "autodelete_photos.yml")
    library.mount()
    with patch(
        "icloudpd.deletion_sync.forget_asset", wraps=deletion_sync.forget_asset
    ) as forget_asset:
        assert library.run(_AUTO_DELETE) == 0
    names = [c.args[1] for c in forget_asset.call_args_list]
    assert names, "auto_delete visited no Recently Deleted records"

    _seed(library, names)
    assert library.run([*_AUTO_DELETE, "--dry-run"]) == 0
    assert _known(library) == 2 * len(names)
    assert library.run(_AUTO_DELETE) == 0
    assert _known(library) == 0


def test_tilde_directory_literal_when_sync_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Feature off, behavior unchanged: icloudpd never expands ~ in directory."""
    library = _Library(tmp_path)
    library.cassette = os.path.abspath(library.cassette)
    monkeypatch.setenv("HOME", str(tmp_path))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    literal = cwd / "~" / "data"
    create_files(
        str(literal),
        [("2018/07/30", "IMG_7408.JPG", 1151066), ("2018/07/30", "IMG_7407.JPG", 656257)],
    )
    library.data_dir = os.path.join("~", "data")
    assert library.run(_LISTING) == 0
    assert os.path.isfile(literal / _DELETED)
    assert not os.path.exists(tmp_path / "data" / _DELETED)
    with closing(sqlite3.connect(manifest.db_path(str(literal), None))) as conn:
        stored = {r[0] for r in conn.execute("SELECT local_path FROM downloaded_assets")}
    assert os.path.join("~", "data", _DELETED) in stored


def test_tilde_directory_rejected_with_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    library = _Library(tmp_path)
    library.data_dir = os.path.join("~", "data")
    global_config, users = cli.parse(
        ["--username", "u", "-d", library.data_dir, "--sync-deletions", "--require-mount-marker"]
    )
    with patch.object(base, "_process_all_users_once", return_value=0) as process:
        assert base.run_with_configs(global_config, users) == 2
    process.assert_not_called()
    assert "starts with '~'" in caplog.text


def test_dry_run_logs_suspects_at_info(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    library = _listing_library(tmp_path)
    assert library.run(_SYNC) == 0
    os.remove(library.path(_DELETED))
    assert library.run([*_SYNC, "--dry-run"]) == 0
    expected = "[DRY RUN] IMG_7409.JPG would become a deletion candidate after one more scan"
    assert [r.levelname for r in caplog.records if r.getMessage() == expected] == ["INFO"]
