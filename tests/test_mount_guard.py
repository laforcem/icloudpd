import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

import pytest

from icloudpd import mount_guard
from icloudpd.notifications import NotificationEvent
from tests.helpers import create_files, path_from_project_root, run_cassette

LOGGER = logging.getLogger("test_mount_guard")


@pytest.fixture(autouse=True)
def _reset_guard() -> Iterator[None]:
    mount_guard.reset()
    yield
    mount_guard.reset()


@pytest.fixture
def events() -> Iterator[list[NotificationEvent]]:
    captured: list[NotificationEvent] = []
    def fake_notify(_logger: Any, _script: Any, event: NotificationEvent) -> bool:
        captured.append(event)
        return True

    with patch("icloudpd.mount_guard.notifications.notify", side_effect=fake_notify):
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


def _failing_then_ok(results: list[bool], captured: list[NotificationEvent]) -> Any:
    outcomes = iter(results)

    def fake_notify(_logger: Any, _script: Any, event: NotificationEvent) -> bool:
        captured.append(event)
        return next(outcomes)

    return fake_notify


def test_failed_missing_alert_is_retried_next_cycle_until_it_is_delivered(tmp_path: Path) -> None:
    captured: list[NotificationEvent] = []
    with patch(
        "icloudpd.mount_guard.notifications.notify",
        side_effect=_failing_then_ok([False, True, True], captured),
    ):
        assert _check(tmp_path) is False  # alert fails
        assert _check(tmp_path) is False  # retried, succeeds
        assert _check(tmp_path) is False  # delivered already: quiet
    assert [e.event_type for e in captured] == ["library_mount_missing"] * 2


def test_failed_restored_alert_is_retried_next_cycle(tmp_path: Path) -> None:
    captured: list[NotificationEvent] = []
    target = tmp_path / "lib"
    with patch(
        "icloudpd.mount_guard.notifications.notify",
        side_effect=_failing_then_ok([True, False, True], captured),
    ):
        assert _check(target) is False  # missing alert delivered
        _mount(target)
        assert _check(target) is True  # restored alert fails
        assert _check(target) is True  # retried, succeeds
        assert _check(target) is True  # quiet
    assert [e.event_type for e in captured] == [
        "library_mount_missing",
        "library_mount_restored",
        "library_mount_restored",
    ]


# --- core_single_run wiring ---------------------------------------------------

_ROOT = path_from_project_root(__file__)
_DOWNLOADED = os.path.join("2018", "07", "31", "IMG_7409.JPG")


class _Run:
    """One icloudpd invocation against the recorded listing_photos cassette."""

    def __init__(self, tmp_path: Path) -> None:
        self.data_dir = str(tmp_path / "data")
        self.cookie_dir = str(tmp_path / "cookie")
        os.makedirs(self.data_dir)
        shutil.copytree(os.path.join(_ROOT, "cookie"), self.cookie_dir)
        create_files(
            self.data_dir,
            [("2018/07/30", "IMG_7408.JPG", 1151066), ("2018/07/30", "IMG_7407.JPG", 656257)],
        )

    def mount(self) -> None:
        Path(self.data_dir, ".mounted").write_text("")

    def run(self, *extra: str) -> tuple[int, list[dict[str, Any]]]:
        with patch("icloudpd.notifications.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            run_mock.return_value.stderr = ""
            result = run_cassette(
                os.path.join(_ROOT, "vcr_cassettes", "listing_photos.yml"),
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
                    "--notification-script",
                    "./test_script.sh",
                    "-d",
                    self.data_dir,
                    "--cookie-directory",
                    self.cookie_dir,
                    *extra,
                ],
            )
            events = [json.loads(c.kwargs["input"]) for c in run_mock.call_args_list]
        return result.exit_code, events

    def downloaded(self) -> bool:
        return os.path.isfile(os.path.join(self.data_dir, _DOWNLOADED))


def _types(events: list[dict[str, Any]], *wanted: str) -> list[str]:
    return [e["event_type"] for e in events if e["event_type"] in wanted]


_GUARD_EVENTS = ("library_mount_missing", "library_mount_restored")


def test_marker_present_run_proceeds(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.mount()
    exit_code, events = run.run("--require-mount-marker")
    assert exit_code == 0
    assert run.downloaded()
    assert _types(events, *_GUARD_EVENTS) == []


def test_marker_missing_exits_nonzero_and_writes_nothing(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    exit_code, events = run.run("--require-mount-marker")
    assert exit_code == 1
    assert not run.downloaded()
    assert not os.path.exists(os.path.join(run.data_dir, ".icloudpd"))
    assert _types(events, *_GUARD_EVENTS) == ["library_mount_missing"]


def test_flag_off_ignores_missing_marker(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    exit_code, events = run.run()
    assert exit_code == 0
    assert run.downloaded()
    assert _types(events, *_GUARD_EVENTS) == []


def test_auth_only_skips_the_guard(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    exit_code, events = run.run("--require-mount-marker", "--auth-only")
    assert exit_code == 0
    assert _types(events, *_GUARD_EVENTS) == []


def test_marker_returns_next_run_proceeds(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    first_exit, first_events = run.run("--require-mount-marker")
    assert first_exit == 1
    run.mount()
    second_exit, second_events = run.run("--require-mount-marker")
    assert second_exit == 0
    assert run.downloaded()
    assert _types(first_events, *_GUARD_EVENTS) == ["library_mount_missing"]
    assert _types(second_events, *_GUARD_EVENTS) == ["library_mount_restored"]


# --- single-run mode skips a user and carries on ------------------------------


def _users(*names: str) -> tuple[Any, list[Any]]:
    import dataclasses

    from icloudpd.cli import parse

    global_config, users = parse(["--directory", "abc", "--username", "u1"])
    return global_config, [dataclasses.replace(users[0], username=n) for n in names]


def _process(results: list[int]) -> tuple[int, list[str]]:
    from icloudpd import base
    from icloudpd.status import StatusExchange

    global_config, users = _users(*[f"u{i}@icloud.com" for i in range(len(results))])
    seen: list[str] = []
    outcomes = iter(results)

    def fake_core(_logger: Any, _status: Any, _global: Any, user: Any, *_rest: Any) -> int:
        seen.append(user.username)
        return next(outcomes)

    with patch("icloudpd.base.core_single_run", side_effect=fake_core):
        code = base._process_all_users_once(global_config, users, LOGGER, StatusExchange())
    return code, seen


def test_single_run_skipped_user_does_not_stop_later_users_but_exit_stays_nonzero() -> None:
    from icloudpd.base import USER_SKIPPED

    code, seen = _process([USER_SKIPPED, 0])
    assert seen == ["u0@icloud.com", "u1@icloud.com"]
    assert code == 1


def test_single_run_ordinary_failure_still_stops_the_run() -> None:
    code, seen = _process([1, 0])
    assert seen == ["u0@icloud.com"]
    assert code == 1


def test_single_run_all_users_fine_exits_zero() -> None:
    code, seen = _process([0, 0])
    assert seen == ["u0@icloud.com", "u1@icloud.com"]
    assert code == 0
