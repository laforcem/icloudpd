import pathlib

import pytest

from icloudpd.config_file import (
    ConfigFileError,
    RawConfigFile,
    _coerce_scalar_fields,
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


def test_load_config_file_rejects_malformed_yaml(tmp_path: pathlib.Path) -> None:
    path = _write(tmp_path, "app: [unterminated")
    with pytest.raises(ConfigFileError, match="failed to parse YAML"):
        load_config_file(path)


def test_coerce_lowercase_fields() -> None:
    result = _coerce_scalar_fields({"log_level": "DEBUG", "mfa_provider": "WEBUI"})
    assert result == {"log_level": "debug", "mfa_provider": "webui"}


def test_coerce_list_elements_lowercased() -> None:
    result = _coerce_scalar_fields({"sizes": ["ORIGINAL", "MEDIUM"]})
    assert result["sizes"] == ["original", "medium"]


def test_coerce_invalid_timestamp_raises() -> None:
    with pytest.raises(ConfigFileError, match="did not parse"):
        _coerce_scalar_fields({"skip_created_before": "not-a-date"})


def test_load_config_file_rejects_unknown_key_in_app(tmp_path: pathlib.Path) -> None:
    path = _write(
        tmp_path,
        """
app:
  bogus_option: 1
users:
  - username: you@icloud.com
""",
    )
    with pytest.raises(ConfigFileError, match="app") as excinfo:
        load_config_file(path)
    assert "bogus_option" in str(excinfo.value)


def test_load_config_file_rejects_unknown_key_in_all_users(tmp_path: pathlib.Path) -> None:
    path = _write(
        tmp_path,
        """
all_users:
  directroy: /data
users:
  - username: you@icloud.com
""",
    )
    with pytest.raises(ConfigFileError, match="all_users") as excinfo:
        load_config_file(path)
    assert "directroy" in str(excinfo.value)


def test_load_config_file_rejects_unknown_key_in_user_entry(tmp_path: pathlib.Path) -> None:
    path = _write(
        tmp_path,
        """
users:
  - username: you@icloud.com
    directroy: /data
""",
    )
    with pytest.raises(ConfigFileError, match=r"users\[0\]") as excinfo:
        load_config_file(path)
    assert "directroy" in str(excinfo.value)


def test_load_config_file_rejects_norway_problem_for_string_field(
    tmp_path: pathlib.Path,
) -> None:
    path = _write(
        tmp_path,
        """
users:
  - username: you@icloud.com
    directory: /data
    library: no
""",
    )
    with pytest.raises(ConfigFileError, match="library") as excinfo:
        load_config_file(path)
    assert "quote" in str(excinfo.value).lower()


def test_load_config_file_allows_legitimate_bool_field(tmp_path: pathlib.Path) -> None:
    path = _write(
        tmp_path,
        """
users:
  - username: you@icloud.com
    directory: /data
    skip_videos: no
""",
    )
    result = load_config_file(path)
    assert result.users[0]["skip_videos"] is False
