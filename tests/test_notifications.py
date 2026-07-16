import dataclasses
import json
import logging
import subprocess
from unittest import TestCase
from unittest.mock import MagicMock, patch

import pytest
from freezegun import freeze_time

from icloudpd import notifications


class BuildEventTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self) -> None:
        self.logger = logging.getLogger("test_notifications")

    @freeze_time("2018-01-01T00:00:00+00:00")
    def test_build_event_sets_fields(self) -> None:
        event = notifications.build_event(
            event_type="session_expired",
            username="jdoe@gmail.com",
            message="hello",
        )
        self.assertEqual(event.event_type, "session_expired")
        self.assertEqual(event.username, "jdoe@gmail.com")
        self.assertEqual(event.message, "hello")
        self.assertEqual(event.timestamp, "2018-01-01T00:00:00+00:00")
        self.assertEqual(event.data, {})

    def test_build_event_carries_data(self) -> None:
        event = notifications.build_event(
            event_type="deletion_sync_summary",
            username="jdoe@gmail.com",
            message="Deleted 3 assets",
            data={"count": 3, "record_names": ["A", "B", "C"]},
        )
        self.assertEqual(event.data, {"count": 3, "record_names": ["A", "B", "C"]})


class NotifyTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self) -> None:
        self.logger = MagicMock(spec=logging.Logger)
        self.event = notifications.build_event(
            event_type="session_expired",
            username="jdoe@gmail.com",
            message="hello",
        )

    def test_notify_is_noop_when_script_path_is_none(self) -> None:
        with patch("icloudpd.notifications.subprocess.run") as run_mock:
            notifications.notify(self.logger, None, self.event)
            run_mock.assert_not_called()

    def test_notify_invokes_script_with_json_on_stdin(self) -> None:
        with patch("icloudpd.notifications.subprocess.run") as run_mock:
            run_mock.return_value = MagicMock(returncode=0, stderr="")
            notifications.notify(self.logger, "./notify.sh", self.event)
            run_mock.assert_called_once()
            args, kwargs = run_mock.call_args
            self.assertEqual(args[0], ["./notify.sh"])
            sent_payload = json.loads(kwargs["input"])
            self.assertEqual(sent_payload, dataclasses.asdict(self.event))
            self.assertEqual(kwargs["timeout"], 10.0)
            self.assertTrue(kwargs["text"])

    def test_notify_logs_warning_on_nonzero_exit(self) -> None:
        with patch("icloudpd.notifications.subprocess.run") as run_mock:
            run_mock.return_value = MagicMock(returncode=1, stderr="boom")
            notifications.notify(self.logger, "./notify.sh", self.event)
            self.logger.warning.assert_called_once()

    def test_notify_logs_warning_on_missing_script(self) -> None:
        with patch(
            "icloudpd.notifications.subprocess.run",
            side_effect=OSError("no such file"),
        ):
            notifications.notify(self.logger, "./missing.sh", self.event)
            self.logger.warning.assert_called_once()

    def test_notify_logs_warning_on_timeout(self) -> None:
        with patch(
            "icloudpd.notifications.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="./notify.sh", timeout=10.0),
        ):
            notifications.notify(self.logger, "./notify.sh", self.event)
            self.logger.warning.assert_called_once()

    def test_notify_respects_custom_timeout(self) -> None:
        with patch("icloudpd.notifications.subprocess.run") as run_mock:
            run_mock.return_value = MagicMock(returncode=0, stderr="")
            notifications.notify(self.logger, "./notify.sh", self.event, timeout_s=2.5)
            _, kwargs = run_mock.call_args
            self.assertEqual(kwargs["timeout"], 2.5)
