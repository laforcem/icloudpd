import dataclasses
import logging
import pathlib
import sys
from typing import Sequence
from unittest.mock import patch

import pytest
import yaml as _yaml

import icloudpd.cli as cli_module
from icloudpd import base, manifest
from icloudpd.cli import parse
from icloudpd.config import GlobalConfig, UserConfig

LOGGER = logging.getLogger("test_deletion_sync_config")


def _user(args: Sequence[str]) -> UserConfig:
    return parse(["-u", "a", "-d", "/x", *args])[1][0]


def _run_cli(args: Sequence[str]) -> int:
    old_argv = sys.argv
    sys.argv = ["icloudpd", *args]
    try:
        with patch.object(cli_module, "run_with_configs", return_value=0):
            return cli_module.cli()
    finally:
        sys.argv = old_argv


def _configs(*extra: str) -> tuple[GlobalConfig, UserConfig]:
    global_config, users = parse(["-u", "a", "-d", "/x", *extra])
    return global_config, users[0]


def test_defaults() -> None:
    user = _user([])
    assert user.sync_deletions is False
    assert user.deletion_sync_threshold == -1


def test_cli_flags() -> None:
    user = _user(["--sync-deletions", "--deletion-sync-threshold", "25"])
    assert user.sync_deletions is True
    assert user.deletion_sync_threshold == 25


def test_yaml_keys(tmp_path: pathlib.Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        _yaml.safe_dump(
            {
                "users": [
                    {
                        "username": "a",
                        "directory": "/x",
                        "sync_deletions": True,
                        "deletion_sync_threshold": 10,
                    }
                ]
            }
        )
    )
    _global, users = parse(["--config", str(config_path)])
    assert users[0].sync_deletions is True
    assert users[0].deletion_sync_threshold == 10


def test_rejects_recent(capsys: pytest.CaptureFixture[str]) -> None:
    code = _run_cli(
        ["-u", "a", "-d", "/x", "--require-mount-marker", "--sync-deletions", "--recent", "5"]
    )
    out = capsys.readouterr().out
    assert code == 2
    assert "--sync-deletions" in out and "--recent" in out


def test_rejects_until_found(capsys: pytest.CaptureFixture[str]) -> None:
    code = _run_cli(
        [
            "-u",
            "a",
            "-d",
            "/x",
            "--require-mount-marker",
            "--sync-deletions",
            "--until-found",
            "5",
        ]
    )
    out = capsys.readouterr().out
    assert code == 2
    assert "--sync-deletions" in out and "--until-found" in out


def test_rejects_without_mount_marker(capsys: pytest.CaptureFixture[str]) -> None:
    code = _run_cli(["-u", "a", "-d", "/x", "--sync-deletions"])
    out = capsys.readouterr().out
    assert code == 2
    assert "require_mount_marker" in out


@pytest.mark.parametrize("value", ["0", "-2"])
def test_rejects_invalid_threshold(value: str, capsys: pytest.CaptureFixture[str]) -> None:
    code = _run_cli(["-u", "a", "-d", "/x", f"--deletion-sync-threshold={value}"])
    out = capsys.readouterr().out
    assert code == 2
    assert "--deletion-sync-threshold" in out


def test_accepts_valid_config() -> None:
    assert (
        _run_cli(
            [
                "-u",
                "a",
                "-d",
                "/x",
                "--require-mount-marker",
                "--sync-deletions",
                "--deletion-sync-threshold",
                "1",
            ]
        )
        == 0
    )


def _pair(a_sync: bool, b_sync: bool) -> tuple[GlobalConfig, list[UserConfig]]:
    global_config, users = parse(["-u", "a", "-d", "/x"])
    first = dataclasses.replace(users[0], username="a", sync_deletions=a_sync)
    second = dataclasses.replace(users[0], username="b", sync_deletions=b_sync)
    return global_config, [first, second]


def test_shared_default_db_rejected(caplog: pytest.LogCaptureFixture) -> None:
    global_config, users = _pair(True, False)
    with caplog.at_level(logging.ERROR, logger=LOGGER.name):
        assert base._has_shared_deletion_db(LOGGER, users) is True
    assert "a" in caplog.text and "b" in caplog.text and "state_directory" in caplog.text
    assert base.run_with_configs(global_config, users) == 2


def test_shared_db_allowed_when_sync_off() -> None:
    _global, users = _pair(False, False)
    assert base._has_shared_deletion_db(LOGGER, users) is False


def _sync_user(
    state_directory: str | None = None, deletion_sync_threshold: int = -1
) -> tuple[GlobalConfig, list[UserConfig]]:
    global_config, user = _configs("--sync-deletions", "--require-mount-marker")
    return global_config, [
        dataclasses.replace(
            user,
            state_directory=state_directory,
            deletion_sync_threshold=deletion_sync_threshold,
        )
    ]


def test_warns_unbounded_threshold(caplog: pytest.LogCaptureFixture) -> None:
    global_config, users = _sync_user(state_directory="/s")
    with (
        patch.object(base, "_process_all_users_once", return_value=0),
        caplog.at_level(logging.WARNING),
    ):
        base.run_with_configs(global_config, users)
    assert any(
        r.levelno == logging.WARNING and "deletion_sync_threshold" in r.getMessage()
        for r in caplog.records
    )


def test_warns_no_state_directory(caplog: pytest.LogCaptureFixture) -> None:
    global_config, users = _sync_user(deletion_sync_threshold=5)
    with (
        patch.object(base, "_process_all_users_once", return_value=0),
        caplog.at_level(logging.WARNING),
    ):
        base.run_with_configs(global_config, users)
    assert any(
        r.levelno == logging.WARNING and "state_directory" in r.getMessage() for r in caplog.records
    )


def test_db_path() -> None:
    assert manifest.db_path("/d", None) == "/d/.icloudpd/state.db"
    assert manifest.db_path("/d", "/s") == "/s/state.db"
