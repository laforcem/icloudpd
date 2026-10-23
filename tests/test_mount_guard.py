import logging
import os
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import pytest

from icloudpd import mount_guard
from icloudpd.notifications import NotificationEvent

LOGGER = logging.getLogger("test_mount_guard")


@pytest.fixture(autouse=True)
def _reset_guard() -> Iterator[None]:
    mount_guard.reset()
    yield
    mount_guard.reset()


@pytest.fixture
def events() -> Iterator[list[NotificationEvent]]:
    captured: list[NotificationEvent] = []
    with patch(
        "icloudpd.mount_guard.notifications.notify",
        side_effect=lambda _logger, _script, event: captured.append(event),
    ):
        yield captured


def _mount(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".mounted").write_text("")


def _check(directory: Path, username: str = "u1@icloud.com") -> bool:
    return mount_guard.check(LOGGER, username, str(directory), "./notify.sh")


def test_marker_present_returns_true_and_does_not_notify(
    tmp_path: Path, events: list[NotificationEvent]
) -> None:
    _mount(tmp_path)
    assert _check(tmp_path) is True
    assert events == []


def test_marker_missing_returns_false_logs_error_and_notifies_once(
    tmp_path: Path, events: list[NotificationEvent], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger=LOGGER.name):
        assert _check(tmp_path) is False
    assert [e.event_type for e in events] == ["library_mount_missing"]
    assert events[0].username == "u1@icloud.com"
    assert events[0].data["directory"] == str(tmp_path)
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_repeated_missing_notifies_only_on_first_failure(
    tmp_path: Path, events: list[NotificationEvent], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger=LOGGER.name):
        for _ in range(3):
            assert _check(tmp_path) is False
    assert [e.event_type for e in events] == ["library_mount_missing"]
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 3


def test_restored_notifies_once_then_stays_quiet(
    tmp_path: Path, events: list[NotificationEvent]
) -> None:
    target = tmp_path / "lib"
    assert _check(target) is False
    _mount(target)
    assert _check(target) is True
    assert _check(target) is True
    assert [e.event_type for e in events] == ["library_mount_missing", "library_mount_restored"]


def test_second_outage_notifies_again(tmp_path: Path, events: list[NotificationEvent]) -> None:
    target = tmp_path / "lib"
    assert _check(target) is False
    _mount(target)
    assert _check(target) is True
    (target / ".mounted").unlink()
    assert _check(target) is False
    assert [e.event_type for e in events] == [
        "library_mount_missing",
        "library_mount_restored",
        "library_mount_missing",
    ]


def test_state_is_tracked_per_username(tmp_path: Path, events: list[NotificationEvent]) -> None:
    assert _check(tmp_path / "a", "a@icloud.com") is False
    assert _check(tmp_path / "b", "b@icloud.com") is False
    assert [(e.event_type, e.username) for e in events] == [
        ("library_mount_missing", "a@icloud.com"),
        ("library_mount_missing", "b@icloud.com"),
    ]


def test_marker_that_is_a_directory_counts_as_missing(
    tmp_path: Path, events: list[NotificationEvent]
) -> None:
    (tmp_path / ".mounted").mkdir()
    assert _check(tmp_path) is False
    assert [e.event_type for e in events] == ["library_mount_missing"]


def test_check_creates_nothing_under_directory(
    tmp_path: Path, events: list[NotificationEvent]
) -> None:
    target = tmp_path / "does" / "not" / "exist"
    assert _check(target) is False
    assert not os.path.exists(tmp_path / "does")
