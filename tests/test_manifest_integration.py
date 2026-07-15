"""Integration tests: downloads produce manifest rows."""

import inspect
import os
import sqlite3
from unittest import TestCase

import pytest

from tests.helpers import path_from_project_root, run_icloudpd_test


class ManifestIntegrationTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self) -> None:
        self.root_path = path_from_project_root(__file__)
        self.fixtures_path = os.path.join(self.root_path, "fixtures")

    def _manifest_rows(self, data_dir: str) -> list[tuple[str, str, int]]:
        db_path = os.path.join(data_dir, ".icloudpd", "state.db")
        self.assertTrue(os.path.isfile(db_path), f"expected manifest db at {db_path}")
        connection = sqlite3.connect(db_path)
        try:
            cursor = connection.execute(
                "SELECT record_name, local_path, size_bytes FROM downloaded_assets"
            )
            return cursor.fetchall()
        finally:
            connection.close()

    def test_newly_downloaded_photo_gets_manifest_row(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])

        files_to_create = [
            ("2018/07/30", "IMG_7408.JPG", 1151066),
            ("2018/07/30", "IMG_7407.JPG", 656257),
        ]
        files_to_download = [("2018/07/31", "IMG_7409.JPG")]

        data_dir, _result = run_icloudpd_test(
            self.assertEqual,
            self.root_path,
            base_dir,
            "listing_photos.yml",
            files_to_create,
            files_to_download,
            [
                "--username",
                "jdoe@gmail.com",
                "--password",
                "password1",
                "--recent",
                "5",
                "--skip-videos",
                "--skip-live-photos",
                "--no-progress-bar",
                "--threads-num",
                "1",
            ],
        )

        rows = self._manifest_rows(data_dir)
        recorded_paths = {os.path.relpath(path, data_dir) for _rec, path, _size in rows}
        self.assertIn(os.path.normpath("2018/07/31/IMG_7409.JPG"), recorded_paths)
        # Pre-existing files matched via isfile() must also be recorded
        self.assertIn(os.path.normpath("2018/07/30/IMG_7408.JPG"), recorded_paths)
        self.assertIn(os.path.normpath("2018/07/30/IMG_7407.JPG"), recorded_paths)

    def test_legacy_original_suffix_file_gets_manifest_row_for_existing_path(self) -> None:
        # Reuses the fixtures (cookies + cassette) of the base.py
        # test_download_over_old_original_photos test: a pre-existing file named
        # with the legacy "-original" suffix (IMG_7408-original.JPG) must still be
        # detected via the fallback lookup, and the manifest must record the path
        # that actually exists on disk (the "-original" suffixed one), not the
        # new-style path that was never created.
        base_dir = os.path.join(self.fixtures_path, "test_download_over_old_original_photos")

        files_to_create = [
            ("2018/07/30", "IMG_7408-original.JPG", 1151066),
            ("2018/07/30", "IMG_7407.JPG", 656257),
        ]
        files_to_download = [("2018/07/31", "IMG_7409.JPG")]

        data_dir, _result = run_icloudpd_test(
            self.assertEqual,
            self.root_path,
            base_dir,
            "listing_photos.yml",
            files_to_create,
            files_to_download,
            [
                "--username",
                "jdoe@gmail.com",
                "--password",
                "password1",
                "--recent",
                "5",
                "--skip-videos",
                "--skip-live-photos",
                "--set-exif-datetime",
                "--no-progress-bar",
                "--threads-num",
                "1",
            ],
        )

        rows = self._manifest_rows(data_dir)
        recorded_paths = {os.path.relpath(path, data_dir) for _rec, path, _size in rows}
        self.assertIn(os.path.normpath("2018/07/31/IMG_7409.JPG"), recorded_paths)
        # The legacy "-original" suffixed path is what actually exists on disk,
        # so it must be recorded verbatim...
        self.assertIn(os.path.normpath("2018/07/30/IMG_7408-original.JPG"), recorded_paths)
        # ...and the new-style path, which was never created, must not be.
        self.assertNotIn(os.path.normpath("2018/07/30/IMG_7408.JPG"), recorded_paths)

    def test_legacy_original_suffix_file_with_wrong_size_dedups_to_correct_manifest_row(
        self,
    ) -> None:
        # Regression test: when a legacy "-original" suffixed file exists on disk
        # but its size doesn't match what iCloud reports, name-size-dedup-with-suffix
        # (the default file-match-policy) reassigns download_path to a new,
        # size-suffixed filename. If a file already exists at that size-suffixed
        # path, the manifest row must point at THAT freshly-resolved path (with
        # the correct size), not at the stale legacy "-original" file whose size
        # was just proven not to match.
        base_dir = os.path.join(self.fixtures_path, "test_download_over_old_original_photos")

        files_to_create = [
            # Legacy file present, but its size does NOT match iCloud's reported
            # size for IMG_7408.JPG (1151066), forcing the dedup branch.
            ("2018/07/30", "IMG_7408-original.JPG", 999),
            # The size-suffixed dedup target already exists on disk with the
            # correct size.
            ("2018/07/30", "IMG_7408-1151066.JPG", 1151066),
            ("2018/07/30", "IMG_7407.JPG", 656257),
        ]
        files_to_download = [("2018/07/31", "IMG_7409.JPG")]

        data_dir, _result = run_icloudpd_test(
            self.assertEqual,
            self.root_path,
            base_dir,
            "listing_photos.yml",
            files_to_create,
            files_to_download,
            [
                "--username",
                "jdoe@gmail.com",
                "--password",
                "password1",
                "--recent",
                "5",
                "--skip-videos",
                "--skip-live-photos",
                "--set-exif-datetime",
                "--no-progress-bar",
                "--threads-num",
                "1",
            ],
        )

        rows = self._manifest_rows(data_dir)
        recorded_paths = {os.path.relpath(path, data_dir) for _rec, path, _size in rows}
        self.assertIn(os.path.normpath("2018/07/31/IMG_7409.JPG"), recorded_paths)
        # The freshly-resolved, size-suffixed path is what actually matches
        # version.size and must be recorded...
        self.assertIn(os.path.normpath("2018/07/30/IMG_7408-1151066.JPG"), recorded_paths)
        # ...and the stale legacy "-original" path, whose size was proven wrong,
        # must not be recorded.
        self.assertNotIn(os.path.normpath("2018/07/30/IMG_7408-original.JPG"), recorded_paths)
