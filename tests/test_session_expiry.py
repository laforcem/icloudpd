import datetime
import json
import os
from types import SimpleNamespace

from icloudpd.logger import setup_logger
from icloudpd.session_expiry import (
    _load_last_warned,
    _save_last_warned,
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
