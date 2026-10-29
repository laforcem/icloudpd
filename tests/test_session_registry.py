import dataclasses
import logging
import os
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from requests import Response

from icloudpd.session_registry import SessionRegistry
from pyicloud_ipd.base import PyiCloudService
from pyicloud_ipd.exceptions import PyiCloudAPIResponseException
from pyicloud_ipd.session import PyiCloudSession

LOGGER = logging.getLogger("test_session_registry")


def _service() -> Any:
    return MagicMock(spec=PyiCloudService)


def test_lock_is_stable_per_username() -> None:
    r = SessionRegistry()
    assert r.lock("a") is r.lock("a")
    assert r.lock("a") is not r.lock("b")


def test_publish_sets_request_lock_and_get_returns_it() -> None:
    r = SessionRegistry()
    service = _service()
    r.publish("a", service)
    assert r.get("a") is service
    assert service.request_lock is r.lock("a")
    assert r.get("b") is None


def test_publish_none_clears_slot() -> None:
    r = SessionRegistry()
    r.publish("a", _service())
    r.publish("a", None)
    assert r.get("a") is None


def test_refresh_success_keeps_service() -> None:
    r = SessionRegistry()
    service = _service()
    service.revalidate_token.return_value = True
    r.publish("a", service)
    assert r.refresh("a", now=1000.0) is service
    assert r.get("a") is service


def test_refresh_failure_clears_slot() -> None:
    r = SessionRegistry()
    service = _service()
    service.revalidate_token.return_value = False
    r.publish("a", service)
    assert r.refresh("a", now=1000.0) is None
    assert r.get("a") is None


def test_refresh_2sa_required_clears_slot() -> None:
    from pyicloud_ipd.exceptions import PyiCloud2SARequiredException

    r = SessionRegistry()
    service = _service()
    service.revalidate_token.side_effect = PyiCloud2SARequiredException("a")
    r.publish("a", service)
    assert r.refresh("a", now=1000.0) is None
    assert r.get("a") is None


def test_refresh_empty_slot_does_not_call_apple() -> None:
    r = SessionRegistry()
    assert r.refresh("a", now=1000.0) is None


def test_refresh_rate_limited() -> None:
    r = SessionRegistry()
    service = _service()
    service.revalidate_token.return_value = True
    r.publish("a", service)
    r.refresh("a", now=1000.0)
    assert r.refresh("a", now=1599.0) is None
    assert service.revalidate_token.call_count == 1
    r.refresh("a", now=1600.0)
    assert service.revalidate_token.call_count == 2


def test_refresh_holds_account_lock() -> None:
    r = SessionRegistry()
    service = _service()
    held: list[bool] = []

    def revalidate() -> bool:
        held.append(r.lock("a")._is_owned())  # type: ignore[attr-defined]
        return True

    service.revalidate_token.side_effect = revalidate
    r.publish("a", service)
    r.refresh("a", now=1000.0)
    assert held == [True]


def test_refresh_never_uses_password_provider(tmp_path: Path) -> None:
    provider = MagicMock(return_value="secret")
    with patch.object(PyiCloudService, "authenticate"):
        service = PyiCloudService("com", "jdoe@gmail.com", provider, cookie_directory=str(tmp_path))
    with patch.object(
        PyiCloudService,
        "_validate_token",
        side_effect=PyiCloudAPIResponseException("Invalid", "421"),
    ):
        assert service.revalidate_token() is False
    provider.assert_not_called()


def test_revalidate_token_success_refreshes_state(tmp_path: Path) -> None:
    provider = MagicMock(return_value="secret")
    with patch.object(PyiCloudService, "authenticate"):
        service = PyiCloudService("com", "jdoe@gmail.com", provider, cookie_directory=str(tmp_path))
    assert service.request_lock is None
    service._photos = MagicMock()
    data = {"dsInfo": {"dsid": "123"}, "webservices": {"ckdatabasews": {"url": "u"}}}
    with patch.object(PyiCloudService, "_validate_token", return_value=data):
        assert service.revalidate_token() is True
    assert service.data == data
    assert service.params["dsid"] == "123"
    assert service._webservices == data["webservices"]
    assert service._photos is None
    provider.assert_not_called()


def _session(tmp_path: Path, request_lock: Any) -> PyiCloudSession:
    service = MagicMock()
    service.password_filter = None
    service.http_timeout = None
    service.session_data = {}
    service.session_path = os.path.join(str(tmp_path), "session.json")
    service.cookiejar_path = os.path.join(str(tmp_path), "cookies")
    service.request_lock = request_lock
    session = PyiCloudSession(service)
    session.cookies = MagicMock()
    return session


def _ok_response() -> Response:
    response = Response()
    response.status_code = 200
    response.headers["Content-Type"] = "text/plain"
    response._content = b"ok"
    return response


def test_request_holds_lock(tmp_path: Path) -> None:
    lock = threading.RLock()
    session = _session(tmp_path, lock)
    held: list[bool] = []

    def fake_request(*_args: Any, **_kwargs: Any) -> Response:
        held.append(lock._is_owned())  # type: ignore[attr-defined]
        return _ok_response()

    with patch("requests.Session.request", side_effect=fake_request):
        assert session.get("https://example.invalid/").ok
    assert held == [True]


def test_request_without_lock_still_works(tmp_path: Path) -> None:
    session = _session(tmp_path, None)
    with patch("requests.Session.request", return_value=_ok_response()):
        assert session.get("https://example.invalid/").ok


def test_reentrant_from_same_thread(tmp_path: Path) -> None:
    r = SessionRegistry()
    session = _session(tmp_path, r.lock("a"))
    result: list[bool] = []

    def worker() -> None:
        with r.lock("a"), patch("requests.Session.request", return_value=_ok_response()):
            result.append(session.get("https://example.invalid/").ok)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=5)
    assert not t.is_alive(), "deadlocked"
    assert result == [True]


def test_core_single_run_publishes() -> None:
    from icloudpd import base
    from icloudpd.cli import parse
    from icloudpd.status import StatusExchange

    global_config, users = parse(["--username", "u1@icloud.com", "--auth-only"])
    user_config = dataclasses.replace(users[0])
    r = SessionRegistry()
    service = _service()
    held: list[bool] = []

    def fake_authenticator(*_args: Any, **_kwargs: Any) -> Any:
        held.append(r.lock(user_config.username)._is_owned())  # type: ignore[attr-defined]
        return service

    with (
        patch("icloudpd.base.authenticator", side_effect=fake_authenticator),
        patch("icloudpd.base.session_expiry.check_and_notify"),
    ):
        code = base.core_single_run(
            LOGGER,
            StatusExchange(),
            global_config,
            user_config,
            {},
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            registry=r,
        )
    assert code == 0
    assert held == [True]
    assert r.get(user_config.username) is service


def test_core_single_run_auth_failure_clears_slot() -> None:
    from icloudpd import base
    from icloudpd.cli import parse
    from icloudpd.status import StatusExchange

    global_config, users = parse(["--username", "u1@icloud.com", "--auth-only"])
    user_config = users[0]
    r = SessionRegistry()
    r.publish(user_config.username, _service())

    with patch(
        "icloudpd.base.authenticator",
        side_effect=PyiCloudAPIResponseException("nope", "500"),
    ):
        code = base.core_single_run(
            LOGGER,
            StatusExchange(),
            global_config,
            user_config,
            {},
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            registry=r,
        )
    assert code == 1
    assert r.get(user_config.username) is None
