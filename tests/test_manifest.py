import logging
import os
from pathlib import Path
from unittest import TestCase

import pytest

from icloudpd import manifest


class OpenManifestTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.logger = logging.getLogger("test_manifest")

    def test_open_creates_db_file_under_dot_icloudpd(self) -> None:
        download_dir = str(self.tmp_path)
        handle = manifest.open(self.logger, download_dir)
        self.assertIsNotNone(handle)
        db_path = os.path.join(download_dir, ".icloudpd", "state.db")
        self.assertTrue(os.path.isfile(db_path))
        assert handle is not None
        manifest.close(handle)

    def test_open_creates_downloaded_assets_table(self) -> None:
        download_dir = str(self.tmp_path)
        handle = manifest.open(self.logger, download_dir)
        assert handle is not None
        cursor = handle.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='downloaded_assets'"
        )
        self.assertEqual(cursor.fetchone()[0], "downloaded_assets")
        manifest.close(handle)

    def test_open_is_idempotent_across_processes(self) -> None:
        download_dir = str(self.tmp_path)
        handle1 = manifest.open(self.logger, download_dir)
        assert handle1 is not None
        manifest.close(handle1)
        handle2 = manifest.open(self.logger, download_dir)
        assert handle2 is not None
        manifest.close(handle2)

    def test_open_returns_none_and_logs_on_unwritable_directory(self) -> None:
        blocker_path = os.path.join(str(self.tmp_path), "blocked")
        with open(blocker_path, "w") as f:
            f.write("not a directory")
        handle = manifest.open(self.logger, blocker_path)
        self.assertIsNone(handle)


class RecordSeenTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.logger = logging.getLogger("test_manifest")
        handle = manifest.open(self.logger, str(self.tmp_path))
        assert handle is not None
        self.handle = handle

    def test_record_seen_inserts_new_row(self) -> None:
        manifest.record_seen(self.logger, self.handle, "REC1", "/data/IMG_1.JPG", 12345)
        rows = manifest.get_all_for_asset(self.handle, "REC1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].record_name, "REC1")
        self.assertEqual(rows[0].local_path, "/data/IMG_1.JPG")
        self.assertEqual(rows[0].size_bytes, 12345)
        self.assertIsNone(rows[0].checksum)
        self.assertEqual(rows[0].first_downloaded_utc, rows[0].last_seen_utc)

    def test_record_seen_on_existing_row_updates_last_seen_only(self) -> None:
        manifest.record_seen(self.logger, self.handle, "REC1", "/data/IMG_1.JPG", 12345)
        first_seen = manifest.get_all_for_asset(self.handle, "REC1")[0].first_downloaded_utc

        manifest.record_seen(self.logger, self.handle, "REC1", "/data/IMG_1.JPG", 12345)
        rows = manifest.get_all_for_asset(self.handle, "REC1")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].first_downloaded_utc, first_seen)

    def test_record_seen_different_local_path_same_record_name_adds_second_row(self) -> None:
        # e.g. a still photo and its Live Photo video component
        manifest.record_seen(self.logger, self.handle, "REC1", "/data/IMG_1.JPG", 12345)
        manifest.record_seen(self.logger, self.handle, "REC1", "/data/IMG_1_HEVC.MOV", 99999)

        rows = manifest.get_all_for_asset(self.handle, "REC1")
        self.assertEqual(len(rows), 2)
        paths = {row.local_path for row in rows}
        self.assertEqual(paths, {"/data/IMG_1.JPG", "/data/IMG_1_HEVC.MOV"})

    def test_record_seen_swallows_sqlite_errors(self) -> None:
        manifest.close(self.handle)  # closed connection -> sqlite3.ProgrammingError on use
        # Must not raise
        manifest.record_seen(self.logger, self.handle, "REC1", "/data/IMG_1.JPG", 12345)


class AllRecordsAndPruneTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.logger = logging.getLogger("test_manifest")
        handle = manifest.open(self.logger, str(self.tmp_path))
        assert handle is not None
        self.handle = handle

    def test_all_records_returns_every_row(self) -> None:
        manifest.record_seen(self.logger, self.handle, "REC1", "/data/a.jpg", 1)
        manifest.record_seen(self.logger, self.handle, "REC2", "/data/b.jpg", 2)

        rows = list(manifest.all_records(self.handle))
        self.assertEqual(len(rows), 2)
        record_names = {row.record_name for row in rows}
        self.assertEqual(record_names, {"REC1", "REC2"})

    def test_all_records_on_empty_manifest_returns_empty(self) -> None:
        rows = list(manifest.all_records(self.handle))
        self.assertEqual(rows, [])

    def test_prune_removes_only_matching_row(self) -> None:
        manifest.record_seen(self.logger, self.handle, "REC1", "/data/a.jpg", 1)
        manifest.record_seen(self.logger, self.handle, "REC1", "/data/a_HEVC.MOV", 2)

        manifest.prune(self.logger, self.handle, "REC1", "/data/a.jpg")

        rows = manifest.get_all_for_asset(self.handle, "REC1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].local_path, "/data/a_HEVC.MOV")

    def test_prune_nonexistent_row_is_a_no_op(self) -> None:
        manifest.prune(self.logger, self.handle, "NOPE", "/data/nope.jpg")
        # Must not raise
        self.assertEqual(list(manifest.all_records(self.handle)), [])

    def test_prune_swallows_sqlite_errors(self) -> None:
        manifest.close(self.handle)  # closed connection -> sqlite3.ProgrammingError on use
        # Must not raise
        manifest.prune(self.logger, self.handle, "REC1", "/data/a.jpg")
