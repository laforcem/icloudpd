import inspect
import json
import os
from unittest import TestCase
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from tests.helpers import path_from_project_root, recreate_path, run_cassette


class SessionExpiringSoonNotificationTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self) -> None:
        self.root_path = path_from_project_root(__file__)
        self.fixtures_path = os.path.join(self.root_path, "fixtures")
        self.vcr_path = os.path.join(self.root_path, "vcr_cassettes")

    @freeze_time("2024-01-08")
    def test_session_expiring_soon_fires_inside_warning_window(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])
        cookie_dir = os.path.join(base_dir, "cookie")

        recreate_path(base_dir)
        recreate_path(cookie_dir)

        with patch("icloudpd.notifications.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            run_mock.return_value.stderr = ""
            result = run_cassette(
                os.path.join(self.vcr_path, "auth_non_2fa.yml"),
                [
                    "--username",
                    "jdoe@gmail.com",
                    "--password",
                    "password1",
                    "--notification-script",
                    "./test_script.sh",
                    "--cookie-directory",
                    cookie_dir,
                    "--auth-only",
                ],
            )
            self.assertEqual(result.exit_code, 0, "exit code")

            run_mock.assert_called_once()
            args, kwargs = run_mock.call_args
            self.assertEqual(args[0], ["test_script.sh"])
            payload = json.loads(kwargs["input"])
            self.assertEqual(payload["event_type"], "session_expiring_soon")
            self.assertEqual(payload["username"], "jdoe@gmail.com")
            self.assertIn("expires in", payload["message"])

    @freeze_time("2018-01-01")
    def test_session_expiring_soon_does_not_fire_far_from_expiry(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])
        cookie_dir = os.path.join(base_dir, "cookie")

        recreate_path(base_dir)
        recreate_path(cookie_dir)

        with patch("icloudpd.notifications.subprocess.run") as run_mock:
            result = run_cassette(
                os.path.join(self.vcr_path, "auth_non_2fa.yml"),
                [
                    "--username",
                    "jdoe@gmail.com",
                    "--password",
                    "password1",
                    "--notification-script",
                    "./test_script.sh",
                    "--cookie-directory",
                    cookie_dir,
                    "--auth-only",
                ],
            )
            self.assertEqual(result.exit_code, 0, "exit code")
            run_mock.assert_not_called()
