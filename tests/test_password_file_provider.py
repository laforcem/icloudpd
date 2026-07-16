import pathlib

import pytest

from icloudpd.base import resolve_constant_password
from icloudpd.config_file import ConfigFileError


def test_resolve_constant_password_prefers_password_file(tmp_path: pathlib.Path) -> None:
    secret_path = tmp_path / "secret.txt"
    secret_path.write_text("from-file\n")
    assert resolve_constant_password(password="from-arg", password_file=str(secret_path)) == (
        "from-file"
    )


def test_resolve_constant_password_falls_back_to_password_arg() -> None:
    assert resolve_constant_password(password="from-arg", password_file=None) == "from-arg"


def test_resolve_constant_password_strips_trailing_newline(tmp_path: pathlib.Path) -> None:
    secret_path = tmp_path / "secret.txt"
    secret_path.write_text("value-with-newline\n")
    assert (
        resolve_constant_password(password=None, password_file=str(secret_path))
        == "value-with-newline"
    )


def test_resolve_constant_password_none_when_neither_given() -> None:
    assert resolve_constant_password(password=None, password_file=None) is None


def test_resolve_constant_password_raises_clear_error_for_missing_file(
    tmp_path: pathlib.Path,
) -> None:
    missing_path = tmp_path / "does-not-exist.txt"
    with pytest.raises(ConfigFileError, match="could not be read"):
        resolve_constant_password(password=None, password_file=str(missing_path))
