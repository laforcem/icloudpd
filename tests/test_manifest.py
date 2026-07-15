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
