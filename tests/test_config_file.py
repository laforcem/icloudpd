import pathlib

import pytest

from icloudpd.config_file import (
    ConfigFileError,
    RawConfigFile,
    load_config_file,
    merge_user_dict,
)


def _write(tmp_path: pathlib.Path, content: str) -> str:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(content)
    return str(config_path)


def test_load_config_file_parses_three_sections(tmp_path: pathlib.Path) -> None:
    path = _write(
        tmp_path,
        """
app:
  mfa_provider: webui
  watch_with_interval: 3600
all_users:
  directory: /data
users:
  - username: you@icloud.com
  - username: partner@icloud.com
    directory: /data/account2
""",
    )
    result = load_config_file(path)
    assert result == RawConfigFile(
        app={"mfa_provider": "webui", "watch_with_interval": 3600},
        all_users={"directory": "/data"},
        users=[
            {"username": "you@icloud.com"},
            {"username": "partner@icloud.com", "directory": "/data/account2"},
        ],
    )


def test_load_config_file_rejects_literal_password_key(tmp_path: pathlib.Path) -> None:
    path = _write(
        tmp_path,
        """
users:
  - username: you@icloud.com
    password: hunter2
""",
    )
    with pytest.raises(ConfigFileError, match="password"):
        load_config_file(path)


def test_load_config_file_requires_username_per_user(tmp_path: pathlib.Path) -> None:
    path = _write(
        tmp_path,
        """
users:
  - directory: /data
""",
    )
    with pytest.raises(ConfigFileError, match="username"):
        load_config_file(path)


def test_load_config_file_rejects_unknown_top_level_section(tmp_path: pathlib.Path) -> None:
    path = _write(
        tmp_path,
        """
users:
  - username: you@icloud.com
bogus_section:
  foo: bar
""",
    )
    with pytest.raises(ConfigFileError, match="bogus_section"):
        load_config_file(path)


def test_merge_user_dict_overrides_all_users_per_field() -> None:
    all_users = {"directory": "/data", "skip_videos": True}
    user = {"username": "partner@icloud.com", "directory": "/data/account2"}
    assert merge_user_dict(all_users, user) == {
        "directory": "/data/account2",
        "skip_videos": True,
        "username": "partner@icloud.com",
    }
