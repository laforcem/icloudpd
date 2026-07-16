import datetime
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from icloudpd.logger import setup_logger
from icloudpd.session_expiry import (
    _load_last_warned,
    _save_last_warned,
    check_and_notify,
    earliest_relevant_expiry,
    state_file_path,
)


def _cookie(name: str, expires: float | None) -> SimpleNamespace:
    return SimpleNamespace(name=name, expires=expires)


def test_earliest_relevant_expiry_picks_soonest_of_two_cookies() -> None:
    later = datetime.datetime(2024, 2, 11, tzinfo=datetime.timezone.utc).timestamp()
    sooner = datetime.datetime(2024, 1, 12, tzinfo=datetime.timezone.utc).timestamp()
    cookies = [
        _cookie("X_APPLE_WEB_KB-ONHCNAXFAIPPFDMR5UZVNO6NIMY", later),
        _cookie("X-APPLE-WEBAUTH-USER", sooner),
        _cookie("X-APPLE-WEBAUTH-LOGIN", None),
    ]

    result = earliest_relevant_expiry(cookies)

    assert result == datetime.datetime.fromtimestamp(sooner, tz=datetime.timezone.utc)


def test_earliest_relevant_expiry_ignores_unrelated_cookies() -> None:
    cookies = [_cookie("dslang", 9999999999.0), _cookie("site", 9999999999.0)]

    assert earliest_relevant_expiry(cookies) is None


def test_earliest_relevant_expiry_returns_none_when_no_expires_present() -> None:
    cookies = [_cookie("X-APPLE-WEBAUTH-USER", None)]

    assert earliest_relevant_expiry(cookies) is None


def test_state_file_path_colocated_with_cookie_jar(tmp_path: object) -> None:
    result = state_file_path(str(tmp_path), "jdoe@gmail.com")

    assert result == os.path.join(str(tmp_path), "jdoegmailcom.notify_state.json")


def test_load_last_warned_returns_none_when_file_missing(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "state.json")

    assert _load_last_warned(setup_logger(), path) is None


def test_save_then_load_round_trips(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "state.json")
    when = datetime.datetime(2026, 7, 15, 9, 0, tzinfo=datetime.timezone.utc)

    _save_last_warned(setup_logger(), path, when)

    assert _load_last_warned(setup_logger(), path) == when


def test_load_last_warned_treats_corrupt_json_as_never_warned(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "state.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not valid json")

    assert _load_last_warned(setup_logger(), path) is None


def test_save_last_warned_preserves_other_event_types(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "state.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"some_other_event": {"last_warned_utc": "2020-01-01T00:00:00+00:00"}}, f)

    _save_last_warned(
        setup_logger(), path, datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc)
    )

    with open(path, encoding="utf-8") as f:
        state = json.load(f)
    assert state["some_other_event"]["last_warned_utc"] == "2020-01-01T00:00:00+00:00"
    assert state["session_expiring_soon"]["last_warned_utc"] == "2026-07-15T00:00:00+00:00"


def _cookies_expiring(expires_str: str) -> list[SimpleNamespace]:
    expires = datetime.datetime.fromisoformat(expires_str).timestamp()
    return [_cookie("X-APPLE-WEBAUTH-USER", expires)]


class _FakeSession:
    def __init__(self, cookies: list[SimpleNamespace]) -> None:
        self.cookies = cookies


class _FakeIcloud:
    def __init__(self, cookies: list[SimpleNamespace]) -> None:
        self.session = _FakeSession(cookies)


@freeze_time("2026-07-10T00:00:00+00:00")
def test_check_and_notify_fires_when_inside_warning_window(tmp_path: object) -> None:
    icloud = _FakeIcloud(_cookies_expiring("2026-07-13T00:00:00+00:00"))  # 3 days out

    with patch("icloudpd.notifications.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""
        check_and_notify(
            setup_logger(),
            icloud,
            "jdoe@gmail.com",
            str(tmp_path),
            "./notify.sh",
            warning_days=7,
            notification_interval_hours=24,
        )

    run_mock.assert_called_once()
    args, kwargs = run_mock.call_args
    payload = json.loads(kwargs["input"])
    assert payload["event_type"] == "session_expiring_soon"
    assert payload["username"] == "jdoe@gmail.com"
    assert payload["data"]["days_remaining"] == pytest.approx(3.0, abs=0.1)


@freeze_time("2026-01-01T00:00:00+00:00")
def test_check_and_notify_skips_when_outside_warning_window(tmp_path: object) -> None:
    icloud = _FakeIcloud(_cookies_expiring("2026-07-13T00:00:00+00:00"))  # ~193 days out

    with patch("icloudpd.notifications.subprocess.run") as run_mock:
        check_and_notify(
            setup_logger(),
            icloud,
            "jdoe@gmail.com",
            str(tmp_path),
            "./notify.sh",
            warning_days=7,
            notification_interval_hours=24,
        )

    run_mock.assert_not_called()


def test_check_and_notify_skips_when_no_notification_script(tmp_path: object) -> None:
    icloud = _FakeIcloud(_cookies_expiring("2026-07-13T00:00:00+00:00"))

    with patch("icloudpd.notifications.subprocess.run") as run_mock:
        check_and_notify(
            setup_logger(),
            icloud,
            "jdoe@gmail.com",
            str(tmp_path),
            None,
            warning_days=7,
            notification_interval_hours=24,
        )

    run_mock.assert_not_called()


def test_check_and_notify_skips_when_warning_days_is_zero(tmp_path: object) -> None:
    icloud = _FakeIcloud(_cookies_expiring("2026-07-13T00:00:00+00:00"))

    with patch("icloudpd.notifications.subprocess.run") as run_mock:
        check_and_notify(
            setup_logger(),
            icloud,
            "jdoe@gmail.com",
            str(tmp_path),
            "./notify.sh",
            warning_days=0,
            notification_interval_hours=24,
        )

    run_mock.assert_not_called()


def test_check_and_notify_skips_when_no_expiring_cookie(tmp_path: object) -> None:
    icloud = _FakeIcloud([])

    with patch("icloudpd.notifications.subprocess.run") as run_mock:
        check_and_notify(
            setup_logger(),
            icloud,
            "jdoe@gmail.com",
            str(tmp_path),
            "./notify.sh",
            warning_days=7,
            notification_interval_hours=24,
        )

    run_mock.assert_not_called()


@freeze_time("2026-07-10T00:00:00+00:00")
def test_check_and_notify_respects_cadence(tmp_path: object) -> None:
    icloud = _FakeIcloud(_cookies_expiring("2026-07-13T00:00:00+00:00"))

    with patch("icloudpd.notifications.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""
        check_and_notify(
            setup_logger(), icloud, "jdoe@gmail.com", str(tmp_path), "./notify.sh",
            warning_days=7, notification_interval_hours=24,
        )
        # A second check an hour later, well inside the 24h cadence, must not re-fire.
        with freeze_time("2026-07-10T01:00:00+00:00"):
            check_and_notify(
                setup_logger(), icloud, "jdoe@gmail.com", str(tmp_path), "./notify.sh",
                warning_days=7, notification_interval_hours=24,
            )

    run_mock.assert_called_once()
