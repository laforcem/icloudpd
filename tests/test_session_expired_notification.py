import inspect
import json
import os
from unittest import TestCase
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from tests.helpers import path_from_project_root, recreate_path, run_cassette


class SessionExpiredNotificationTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self) -> None:
        self.root_path = path_from_project_root(__file__)
        self.fixtures_path = os.path.join(self.root_path, "fixtures")
        self.vcr_path = os.path.join(self.root_path, "vcr_cassettes")

    @freeze_time("2018-01-01")
    def test_2sa_required_notification_script_receives_json_event(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])
        cookie_dir = os.path.join(base_dir, "cookie")
        data_dir = os.path.join(base_dir, "data")

        for dir in [base_dir, cookie_dir, data_dir]:
            recreate_path(dir)

        with patch("icloudpd.notifications.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            run_mock.return_value.stderr = ""
            result = run_cassette(
                os.path.join(self.vcr_path, "auth_requires_2fa.yml"),
                [
                    "--username",
                    "jdoe@gmail.com",
                    "--password",
                    "password1",
                    "--notification-script",
                    "./test_script.sh",
                    "-d",
                    data_dir,
                    "--cookie-directory",
                    cookie_dir,
                ],
            )
            self.assertEqual(result.exit_code, 1, "exit code")

            run_mock.assert_called_once()
            args, kwargs = run_mock.call_args
            self.assertEqual(args[0], ["test_script.sh"])
            payload = json.loads(kwargs["input"])
            self.assertEqual(payload["event_type"], "session_expired")
            self.assertEqual(payload["username"], "jdoe@gmail.com")
            self.assertIn("two-step authentication has expired", payload["message"])
