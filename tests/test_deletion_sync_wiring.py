"""Deletion detection wired into the real download loop (cassette-driven).

These call cli.parse + base.run_with_configs rather than cli(): the cassettes
only support --recent, which cli() rejects together with --sync-deletions.
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
        with vcr.use_cassette(self.cassette):
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
    real_mark = deletion_sync.mark_completed

    def capture(scan: deletion_sync.DeletionScan) -> None:
        completed.append(scan)
        real_mark(scan)

    with patch("icloudpd.deletion_sync.mark_completed", side_effect=capture):
        assert library.run(_SYNC) == 0
    assert not os.path.isfile(library.path(_DELETED))
    with library.db() as conn:
        assert deletion_sync.list_items(conn, list(deletion_sync.ItemStatus)) == []
    assert len(completed) == 1
    assert [p.filename for p in completed[0].candidates.values()] == ["IMG_7409.JPG"]
    assert library.scan_state() == (3, 3)


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
    ):
        assert library.run(_SYNC) == 0
    assert library.scan_state() == (1, 0)


def test_missing_marker_detects_nothing(tmp_path: Path) -> None:
    library = _listing_library(tmp_path)
    os.remove(os.path.join(library.data_dir, ".mounted"))
    with patch(
        "icloudpd.deletion_sync.open_scan", side_effect=AssertionError("open_scan called")
    ) as open_scan:
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
