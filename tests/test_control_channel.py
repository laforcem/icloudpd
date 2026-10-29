import dataclasses
import http.client
import logging
import pathlib
import sqlite3
import threading
import time
from typing import Any, Iterator, Sequence
from unittest.mock import patch
from urllib.parse import quote

import pytest
import yaml as _yaml
from flask.testing import FlaskClient
from waitress.server import BaseWSGIServer, create_server

from icloudpd import base, control, deletion_review, deletion_sync, manifest
from icloudpd.cli import parse
from icloudpd.config import GlobalConfig, UserConfig
from icloudpd.session_registry import SessionRegistry
from tests.test_deletion_review_thumbnails import MASTER
from tests.test_deletion_review_thumbnails import _service as thumbnail_service
from tests.test_session_registry import lock_held_elsewhere

LOGGER = logging.getLogger("test_control_channel")
TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _entry(tmp_path: pathlib.Path, username: str, library: str, sync: bool = True) -> UserConfig:
    _global, users = parse(["-u", username, "-d", str(tmp_path / "lib")])
    return dataclasses.replace(
        users[0],
        library=library,
        sync_deletions=sync,
        require_mount_marker=True,
        state_directory=str(tmp_path / f"state-{username}-{library}"),
    )


def _db(user: UserConfig) -> sqlite3.Connection:
    handle = manifest.open(LOGGER, user.directory, user.state_directory)
    assert handle is not None
    deletion_sync.ensure_schema(handle.connection)
    return handle.connection


def _seed(user: UserConfig, count: int, prefix: str = "R") -> list[str]:
    conn = _db(user)
    names = [f"{prefix}{i:02d}" for i in range(count)]
    for i, n in enumerate(names):
        ext = "MOV" if i == 0 else "JPG"
        conn.execute(
            "INSERT INTO deletion_items (record_name, filename, asset_date_utc, detected_utc,"
            " status, status_changed_utc) VALUES (?, ?, '2024-01-02T00:00:00+00:00', ?, 'held',"
            " 'x')",
            (n, f"{n}.{ext}", f"2026-10-01T00:00:{i:02d}+00:00"),
        )
    if count:
        conn.execute("UPDATE deletion_state SET tripped = 1, tripped_utc = 'x'")
    conn.commit()
    conn.close()
    return names


def _statuses(user: UserConfig) -> dict[str, str]:
    conn = _db(user)
    try:
        return dict(conn.execute("SELECT record_name, status FROM deletion_items"))
    finally:
        conn.close()


def _client(users: Sequence[UserConfig], registry: SessionRegistry | None = None) -> FlaskClient:
    app = control.build_control_app(
        LOGGER, TOKEN, users, registry or SessionRegistry(), clock=lambda: 1000.0
    )
    return app.test_client()


@pytest.fixture
def three(tmp_path: pathlib.Path) -> Iterator[list[UserConfig]]:
    users = [
        _entry(tmp_path, "a", "PrimarySync"),
        _entry(tmp_path, "a", "SharedSync-X"),
        _entry(tmp_path, "b", "PrimarySync"),
    ]
    _seed(users[0], 3, "A")
    _seed(users[1], 5, "S")
    _seed(users[2], 1, "B")
    yield users


def _key(user: UserConfig) -> str:
    return deletion_review.entry_key(user.username, user.library)


def test_no_token_401(three: list[UserConfig]) -> None:
    client = _client(three)
    assert client.get("/v1/entries").status_code == 401
    assert client.get("/nope").status_code == 401
    assert client.post(f"/v1/entries/{_key(three[0])}/resolve").status_code == 401


def test_wrong_token_401(three: list[UserConfig]) -> None:
    client = _client(three)
    for header in (f"Bearer {TOKEN}x", TOKEN, f"bearer {TOKEN}", "Bearer ", f"Basic {TOKEN}"):
        assert client.get("/v1/entries", headers={"Authorization": header}).status_code == 401
    assert client.get("/v1/entries", headers=AUTH).status_code == 200


def test_auth_uses_compare_digest(three: list[UserConfig]) -> None:
    client = _client(three)
    with patch("hmac.compare_digest", return_value=True) as compare:
        assert client.get("/v1/entries", headers={"Authorization": "x"}).status_code == 200
    compare.assert_called_once_with(b"x", f"Bearer {TOKEN}".encode())


def test_entries_lists_all_sync_entries_multi_account(
    tmp_path: pathlib.Path, three: list[UserConfig]
) -> None:
    off = _entry(tmp_path, "c", "PrimarySync", sync=False)
    _seed(off, 2, "C")
    response = _client([*three, off]).get("/v1/entries", headers=AUTH)
    assert response.status_code == 200
    entries = response.get_json()["entries"]
    assert len(entries) == 3
    assert len({e["key"] for e in entries}) == 3
    by_pair = {(e["username"], e["library"]): e for e in entries}
    assert set(by_pair) == {("a", "PrimarySync"), ("a", "SharedSync-X"), ("b", "PrimarySync")}
    assert by_pair[("a", "PrimarySync")]["held_count"] == 3
    assert by_pair[("a", "SharedSync-X")]["held_count"] == 5
    assert by_pair[("b", "PrimarySync")]["held_count"] == 1
    assert by_pair[("a", "PrimarySync")]["tripped"] is True
    assert by_pair[("b", "PrimarySync")]["key"] == _key(three[2])
    assert set(entries[0]) == {"key", "username", "library", "held_count", "tripped"}


def test_entries_without_state_db_are_empty_and_not_created(tmp_path: pathlib.Path) -> None:
    user = _entry(tmp_path, "a", "PrimarySync")
    client = _client([user])
    entries = client.get("/v1/entries", headers=AUTH).get_json()["entries"]
    assert entries == [
        {
            "key": _key(user),
            "username": "a",
            "library": "PrimarySync",
            "held_count": 0,
            "tripped": False,
        }
    ]
    page = client.get(f"/v1/entries/{_key(user)}/held", headers=AUTH).get_json()
    assert page["total"] == 0 and page["items"] == [] and page["batch_token"] == ""
    assert not pathlib.Path(user.state_directory or "", "state.db").exists()


def test_unknown_key_404(tmp_path: pathlib.Path, three: list[UserConfig]) -> None:
    off = _entry(tmp_path, "c", "PrimarySync", sync=False)
    client = _client([*three, off])
    for key in ("00000000", _key(off)):
        assert client.get(f"/v1/entries/{key}/held", headers=AUTH).status_code == 404
        body = {"keep": True, "batch_token": "x"}
        assert (
            client.post(f"/v1/entries/{key}/held/R00/keep", json=body, headers=AUTH).status_code
            == 404
        )
        body = {"action": "apply", "batch_token": "x"}
        assert client.post(f"/v1/entries/{key}/resolve", json=body, headers=AUTH).status_code == 404
        assert client.get(f"/v1/entries/{key}/held/R00/thumbnail", headers=AUTH).status_code == 404


def test_held_page_shape_and_paging(tmp_path: pathlib.Path) -> None:
    user = _entry(tmp_path, "a", "PrimarySync")
    _seed(user, 12)
    client = _client([user])
    first = client.get(f"/v1/entries/{_key(user)}/held", headers=AUTH).get_json()
    assert first["page"] == 1 and len(first["items"]) == 10
    assert first["items"][0] == {
        "number": 1,
        "record_name": "R00",
        "filename": "R00.MOV",
        "asset_date": "2024-01-02T00:00:00+00:00",
        "is_video": True,
        "keep": False,
    }
    assert first["items"][1]["is_video"] is False
    response = client.get(f"/v1/entries/{_key(user)}/held?page=2", headers=AUTH)
    assert response.status_code == 200
    page = response.get_json()
    assert set(page) == {
        "batch_token",
        "keep_token",
        "page",
        "pages",
        "total",
        "kept_count",
        "items",
    }
    assert page["keep_token"] == ""
    assert (page["page"], page["pages"], page["total"], page["kept_count"]) == (2, 2, 12, 0)
    assert [i["number"] for i in page["items"]] == [11, 12]
    assert page["batch_token"] == first["batch_token"] != ""
    for bad in ("0", "x", "-1"):
        assert (
            client.get(f"/v1/entries/{_key(user)}/held?page={bad}", headers=AUTH).status_code == 400
        )


def test_keep_then_apply_touches_only_that_entry(three: list[UserConfig]) -> None:
    client = _client(three)
    before_a, before_b = _statuses(three[0]), _statuses(three[2])
    key = _key(three[1])
    token = client.get(f"/v1/entries/{key}/held", headers=AUTH).get_json()["batch_token"]
    response = client.post(
        f"/v1/entries/{key}/held/S01/keep", json={"keep": True, "batch_token": token}, headers=AUTH
    )
    assert response.status_code == 200
    marks = response.get_json()["keep_token"]
    assert response.get_json() == {"total": 5, "kept_count": 1, "keep_token": marks}
    assert len(marks) == 8
    assert client.get(f"/v1/entries/{key}/held", headers=AUTH).get_json()["keep_token"] == marks
    response = client.post(
        f"/v1/entries/{key}/resolve",
        json={"action": "apply", "batch_token": token, "keep_token": marks},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.get_json() == {"approved": 4, "rejected": 1}
    after = _statuses(three[1])
    assert after["S01"] == "rejected"
    assert [s for n, s in after.items() if n != "S01"] == ["approved"] * 4
    assert _statuses(three[0]) == before_a
    assert _statuses(three[2]) == before_b
    assert set(before_a.values()) == {"held"}


def test_keep_all_rejects_everything(three: list[UserConfig]) -> None:
    client = _client(three)
    key = _key(three[0])
    token = client.get(f"/v1/entries/{key}/held", headers=AUTH).get_json()["batch_token"]
    response = client.post(
        f"/v1/entries/{key}/resolve",
        json={"action": "keep_all", "batch_token": token},
        headers=AUTH,
    )
    assert response.get_json() == {"approved": 0, "rejected": 3}
    assert set(_statuses(three[0]).values()) == {"rejected"}


@pytest.mark.parametrize(
    "body",
    [
        {"keep": "yes", "batch_token": "t"},
        {"keep": True},
        {"keep": True, "batch_token": 5},
        None,
    ],
)
def test_keep_bad_body_400(three: list[UserConfig], body: Any) -> None:
    client = _client(three)
    response = client.post(f"/v1/entries/{_key(three[0])}/held/A00/keep", json=body, headers=AUTH)
    assert response.status_code == 400
    assert set(_statuses(three[0]).values()) == {"held"}


@pytest.mark.parametrize(
    "body",
    [
        {"action": "approve", "batch_token": "t"},
        {"action": "apply"},
        {"action": "apply", "batch_token": None},
        {"action": "apply", "batch_token": "t"},
        {"action": "apply", "batch_token": "t", "keep_token": 5},
        None,
    ],
)
def test_resolve_bad_body_400(three: list[UserConfig], body: Any) -> None:
    client = _client(three)
    response = client.post(f"/v1/entries/{_key(three[0])}/resolve", json=body, headers=AUTH)
    assert response.status_code == 400
    assert set(_statuses(three[0]).values()) == {"held"}


def test_keep_record_not_held_404(three: list[UserConfig]) -> None:
    client = _client(three)
    key = _key(three[0])
    token = client.get(f"/v1/entries/{key}/held", headers=AUTH).get_json()["batch_token"]
    response = client.post(
        f"/v1/entries/{key}/held/S01/keep", json={"keep": True, "batch_token": token}, headers=AUTH
    )
    assert response.status_code == 404


def test_stale_token_409_returns_current_token(three: list[UserConfig]) -> None:
    client = _client(three)
    key = _key(three[0])
    current = client.get(f"/v1/entries/{key}/held", headers=AUTH).get_json()["batch_token"]
    for path, body in (
        ("held/A01/keep", {"keep": True, "batch_token": "deadbeef"}),
        ("resolve", {"action": "apply", "batch_token": "deadbeef", "keep_token": ""}),
    ):
        response = client.post(f"/v1/entries/{key}/{path}", json=body, headers=AUTH)
        assert response.status_code == 409
        assert response.get_json() == {"batch_token": current, "keep_token": ""}
    assert set(_statuses(three[0]).values()) == {"held"}
    assert client.get(f"/v1/entries/{key}/held", headers=AUTH).get_json()["kept_count"] == 0


def test_apply_with_stale_keep_token_409_both_tokens(three: list[UserConfig]) -> None:
    client = _client(three)
    key = _key(three[0])
    page = client.get(f"/v1/entries/{key}/held", headers=AUTH).get_json()
    token, seen = page["batch_token"], page["keep_token"]
    toggled = client.post(
        f"/v1/entries/{key}/held/A01/keep",
        json={"keep": True, "batch_token": token},
        headers=AUTH,
    ).get_json()["keep_token"]
    assert toggled != seen
    response = client.post(
        f"/v1/entries/{key}/resolve",
        json={"action": "apply", "batch_token": token, "keep_token": seen},
        headers=AUTH,
    )
    assert response.status_code == 409
    assert response.get_json() == {"batch_token": token, "keep_token": toggled}
    assert set(_statuses(three[0]).values()) == {"held"}


def test_busy_returns_503_syncing(three: list[UserConfig]) -> None:
    client = _client(three)
    key = _key(three[0])
    token = client.get(f"/v1/entries/{key}/held", headers=AUTH).get_json()["batch_token"]
    blocker = _db(three[0])
    blocker.execute("BEGIN IMMEDIATE")
    try:
        with patch.object(deletion_sync, "_BUSY_TIMEOUT_SECONDS", 0.05):
            for path, body in (
                ("held/A01/keep", {"keep": True, "batch_token": token}),
                ("resolve", {"action": "apply", "batch_token": token, "keep_token": ""}),
            ):
                response = client.post(f"/v1/entries/{key}/{path}", json=body, headers=AUTH)
                assert response.status_code == 503
                assert response.get_json() == {"reason": "syncing"}
            # Reads still work while a scan holds the write lock.
            assert client.get(f"/v1/entries/{key}/held", headers=AUTH).status_code == 200
            assert client.get("/v1/entries", headers=AUTH).status_code == 200
    finally:
        blocker.rollback()
        blocker.close()
    assert set(_statuses(three[0]).values()) == {"held"}


def test_thumbnail_ok_and_unavailable(three: list[UserConfig]) -> None:
    registry = SessionRegistry()
    client = _client(three, registry)
    url = f"/v1/entries/{_key(three[1])}/held/S02/thumbnail"
    with patch.object(deletion_review, "fetch_thumbnail", return_value=b"\xff\xd8jpeg") as fetch:
        response = client.get(url, headers=AUTH)
    assert response.status_code == 200
    assert response.mimetype == "image/jpeg"
    assert response.data == b"\xff\xd8jpeg"
    fetch.assert_called_once_with(registry, "a", "SharedSync-X", "S02", 1000.0)
    with patch.object(deletion_review, "fetch_thumbnail", return_value=None):
        response = client.get(url, headers=AUTH)
    assert response.status_code == 503
    assert response.get_json() == {"reason": "thumbnail_unavailable"}


@pytest.mark.parametrize("error", [RuntimeError("boom"), ConnectionError("down")])
def test_thumbnail_error_is_503_not_500(three: list[UserConfig], error: Exception) -> None:
    client = _client(three)
    url = f"/v1/entries/{_key(three[1])}/held/S02/thumbnail"
    with patch.object(deletion_review, "fetch_thumbnail", side_effect=error):
        response = client.get(url, headers=AUTH)
    assert response.status_code == 503
    assert response.get_json() == {"reason": "thumbnail_unavailable"}


# CloudKit record names are base64, so they can contain "/" and "+".
SLASHED = "ab/cd+ef"


@pytest.mark.parametrize("encoded", [True, False])
def test_thumbnail_and_keep_accept_record_name_with_slash(
    three: list[UserConfig], encoded: bool
) -> None:
    conn = _db(three[1])
    conn.execute(
        "INSERT INTO deletion_items (record_name, filename, asset_date_utc, detected_utc,"
        " status, status_changed_utc) VALUES (?, 'X.JPG', '2024-01-02T00:00:00+00:00',"
        " '2026-10-01T00:01:00+00:00', 'held', 'x')",
        (SLASHED,),
    )
    conn.commit()
    conn.close()
    client = _client(three)
    key = _key(three[1])
    name = quote(SLASHED, safe="") if encoded else SLASHED
    with patch.object(deletion_review, "fetch_thumbnail", return_value=b"\xff\xd8jpeg") as fetch:
        response = client.get(f"/v1/entries/{key}/held/{name}/thumbnail", headers=AUTH)
    assert response.status_code == 200
    assert fetch.call_args.args[3] == SLASHED
    token = client.get(f"/v1/entries/{key}/held", headers=AUTH).get_json()["batch_token"]
    response = client.post(
        f"/v1/entries/{key}/held/{name}/keep",
        json={"keep": True, "batch_token": token},
        headers=AUTH,
    )
    assert response.status_code == 200


def test_thumbnail_for_record_not_held_404(three: list[UserConfig]) -> None:
    client = _client(three)
    with patch.object(deletion_review, "fetch_thumbnail", return_value=b"x") as fetch:
        # S02 is held, but in a different entry
        response = client.get(f"/v1/entries/{_key(three[0])}/held/S02/thumbnail", headers=AUTH)
    assert response.status_code == 404
    fetch.assert_not_called()


# --- startup -------------------------------------------------------------------------------


def _sync_configs(tmp_path: pathlib.Path, *extra: str) -> tuple[GlobalConfig, list[UserConfig]]:
    global_config, users = parse(["-u", "a", "-d", str(tmp_path / "lib"), *extra])
    user = dataclasses.replace(
        users[0],
        sync_deletions=True,
        require_mount_marker=True,
        deletion_sync_threshold=5,
        state_directory=str(tmp_path / "s1"),
    )
    return global_config, [user]


def test_run_with_configs_no_token_file_no_listener(tmp_path: pathlib.Path) -> None:
    global_config, users = _sync_configs(tmp_path)
    assert global_config.control_token_file is None
    with (
        patch.object(base, "_process_all_users_once", return_value=0),
        patch.object(base, "Thread") as thread,
    ):
        assert base.run_with_configs(global_config, users) == 0
    assert all(c.kwargs.get("target") is not control.serve_control for c in thread.call_args_list)


def test_run_with_configs_token_file_starts_listener_on_control_port(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text(f"{TOKEN}\n")
    global_config, users = _sync_configs(
        tmp_path, "--control-token-file", str(token_file), "--control-port", "3456"
    )
    with (
        patch.object(base, "_process_all_users_once", return_value=0) as process,
        patch.object(base, "Thread") as thread,
        caplog.at_level(logging.DEBUG),
    ):
        assert base.run_with_configs(global_config, users) == 0
    calls = [c for c in thread.call_args_list if c.kwargs.get("target") is control.serve_control]
    assert len(calls) == 1
    kwargs = calls[0].kwargs
    assert kwargs["daemon"] is True
    _logger, token, configs, registry, host, port = kwargs["args"]
    assert (token, list(configs), host, port) == (TOKEN, users, "0.0.0.0", 3456)
    # the same registry the scans use
    assert process.call_args.args[4] is registry
    thread.return_value.start.assert_called()
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("content", [None, "", "  \n"])
def test_run_with_configs_bad_token_file_exits_2(
    tmp_path: pathlib.Path, content: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    token_file = tmp_path / "token"
    if content is not None:
        token_file.write_text(content)
    global_config, users = _sync_configs(tmp_path, "--control-token-file", str(token_file))
    with (
        patch.object(base, "_process_all_users_once", return_value=0) as process,
        patch.object(base, "Thread") as thread,
        caplog.at_level(logging.ERROR),
    ):
        assert base.run_with_configs(global_config, users) == 2
    process.assert_not_called()
    thread.assert_not_called()
    assert any(r.levelno == logging.ERROR and "control" in r.getMessage() for r in caplog.records)


def test_entry_key_collision_exits_2(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text(TOKEN)
    global_config, users = _sync_configs(tmp_path, "--control-token-file", str(token_file))
    second = dataclasses.replace(users[0], username="b", state_directory=str(tmp_path / "s2"))
    with (
        patch.object(base, "_process_all_users_once", return_value=0) as process,
        patch.object(base, "Thread") as thread,
        patch.object(deletion_review, "entry_key", return_value="deadbeef"),
        caplog.at_level(logging.ERROR),
    ):
        assert base.run_with_configs(global_config, [users[0], second]) == 2
    process.assert_not_called()
    thread.assert_not_called()
    assert "deadbeef" in caplog.text


def test_entry_key_collision_ignores_entries_without_sync(tmp_path: pathlib.Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text(TOKEN)
    global_config, users = _sync_configs(tmp_path, "--control-token-file", str(token_file))
    second = dataclasses.replace(
        users[0], username="b", sync_deletions=False, state_directory=str(tmp_path / "s2")
    )
    with (
        patch.object(base, "_process_all_users_once", return_value=0),
        patch.object(base, "Thread"),
        patch.object(deletion_review, "entry_key", return_value="deadbeef"),
    ):
        assert base.run_with_configs(global_config, [users[0], second]) == 0


def test_cli_and_yaml_control_options(tmp_path: pathlib.Path) -> None:
    global_config, _ = parse(["-u", "a", "-d", "/x"])
    assert global_config.control_token_file is None
    assert global_config.control_port == 2012
    global_config, _ = parse(
        ["-u", "a", "-d", "/x", "--control-token-file", "/t", "--control-port", "3000"]
    )
    assert (global_config.control_token_file, global_config.control_port) == ("/t", 3000)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        _yaml.safe_dump(
            {
                "app": {"control_token_file": "/y", "control_port": 3001},
                "users": [{"username": "a", "directory": "/x"}],
            }
        )
    )
    global_config, _ = parse(["--config", str(config_path)])
    assert (global_config.control_token_file, global_config.control_port) == ("/y", 3001)


# --- final-review fixes --------------------------------------------------------------------


def test_thumbnail_503_when_account_lock_held_elsewhere(three: list[UserConfig]) -> None:
    registry = SessionRegistry()
    registry.lock_timeout = 0.2
    service = thumbnail_service([{"S02": MASTER}])
    service.photos.private_libraries = {"SharedSync-X": service.photos}
    registry.publish("a", service)
    client = _client(three, registry)
    url = f"/v1/entries/{_key(three[1])}/held/S02/thumbnail"
    with lock_held_elsewhere(registry, "a"):
        started = time.monotonic()
        response = client.get(url, headers=AUTH)
        assert time.monotonic() - started < 2
    assert response.status_code == 503
    assert response.get_json() == {"reason": "thumbnail_unavailable"}
    service.session.get.assert_not_called()
    # once the lock is free, the same request is served
    response = client.get(url, headers=AUTH)
    assert response.status_code == 200 and response.data == b"JPEG"


@pytest.mark.parametrize("bad", ["²", "٣", "1²"])
def test_held_non_ascii_digit_page_is_400(three: list[UserConfig], bad: str) -> None:
    client = _client(three)
    response = client.get(
        f"/v1/entries/{_key(three[0])}/held", query_string={"page": bad}, headers=AUTH
    )
    assert response.status_code == 400
    assert response.get_json() == {"reason": "bad_page"}


def test_serve_control_bounds_threads_and_body_size(three: list[UserConfig]) -> None:
    with patch.object(control.waitress, "serve") as serve:
        control.serve_control(LOGGER, TOKEN, three, SessionRegistry(), "127.0.0.1", 3456)
    kwargs = serve.call_args.kwargs
    assert (kwargs["host"], kwargs["port"]) == ("127.0.0.1", 3456)
    assert kwargs["threads"] == 8
    assert kwargs["max_request_body_size"] == 16384


def test_oversized_body_rejected_by_waitress_413(three: list[UserConfig]) -> None:
    with patch.object(control.waitress, "serve") as serve:
        control.serve_control(LOGGER, TOKEN, three, SessionRegistry(), "127.0.0.1", 0)
    app = serve.call_args.args[0]
    options = {k: v for k, v in serve.call_args.kwargs.items() if k not in ("host", "port")}
    server = create_server(app, host="127.0.0.1", port=0, **options)
    assert isinstance(server, BaseWSGIServer)
    runner = threading.Thread(target=server.run, daemon=True)
    runner.start()
    try:
        port = int(server.getsockname()[1])
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("POST", f"/v1/entries/{_key(three[0])}/resolve", body=b"x" * 20000)
            assert connection.getresponse().status == 413
        finally:
            connection.close()
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("GET", "/v1/entries", headers=AUTH)
            assert connection.getresponse().status == 200
        finally:
            connection.close()
    finally:
        server.close()
        runner.join(5)
    assert set(_statuses(three[0]).values()) == {"held"}


def test_serve_control_failure_is_logged(
    three: list[UserConfig], caplog: pytest.LogCaptureFixture
) -> None:
    with (
        patch.object(control.waitress, "serve", side_effect=OSError(98, "Address in use")),
        caplog.at_level(logging.ERROR),
    ):
        control.serve_control(LOGGER, TOKEN, three, SessionRegistry(), "127.0.0.1", 3456)
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "control channel" in errors[0].getMessage()
    assert "Address in use" in errors[0].getMessage()
    assert TOKEN not in caplog.text
