# tests/test_generate_xmp_file.py
import os
import tempfile
from unittest import TestCase
from unittest.mock import MagicMock

from icloudpd.xmp_sidecar import generate_xmp_file


class GenerateXMPFile(TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.download_path = os.path.join(self.tmpdir.name, "IMG_1234")
        self.sidecar_path = self.download_path + ".xmp"
        self.logger = MagicMock()
        self.asset_record: dict = {"fields": {}}

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_writes_file_when_none_exists(self) -> None:
        generate_xmp_file(self.logger, self.download_path, self.asset_record, dry_run=False)
        self.assertTrue(os.path.exists(self.sidecar_path))

    def test_skips_rewrite_when_content_unchanged(self) -> None:
        generate_xmp_file(self.logger, self.download_path, self.asset_record, dry_run=False)
        with open(self.sidecar_path, "rb") as f:
            first_content = f.read()
        first_mtime = os.path.getmtime(self.sidecar_path)
        # back-date mtime so a rewrite would be detectable
        os.utime(self.sidecar_path, (first_mtime - 10, first_mtime - 10))

        generate_xmp_file(self.logger, self.download_path, self.asset_record, dry_run=False)

        with open(self.sidecar_path, "rb") as f:
            second_content = f.read()
        self.assertEqual(first_content, second_content)
        self.assertEqual(first_mtime - 10, os.path.getmtime(self.sidecar_path))

    def test_rewrites_file_when_content_differs(self) -> None:
        generate_xmp_file(self.logger, self.download_path, self.asset_record, dry_run=False)

        # base64("New Title") — a genuinely different caption must still get written
        self.asset_record["fields"]["captionEnc"] = {
            "value": "TmV3IFRpdGxl",
            "type": "ENCRYPTED_BYTES",
        }
        generate_xmp_file(self.logger, self.download_path, self.asset_record, dry_run=False)

        with open(self.sidecar_path, "rb") as f:
            content = f.read()
        self.assertIn(b"New Title", content)
