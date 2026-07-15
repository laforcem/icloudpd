import logging
from unittest import TestCase

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
