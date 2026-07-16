import datetime
import inspect
import os
import pathlib
import shutil
import zoneinfo
from argparse import ArgumentError
from typing import Sequence, Tuple
from unittest import TestCase

import pytest
import yaml as _yaml  # only used to write fixture files in these tests

from icloudpd.cli import format_help, parse
from icloudpd.config import GlobalConfig, UserConfig
from icloudpd.log_level import LogLevel
from icloudpd.mfa_provider import MFAProvider
from icloudpd.password_provider import PasswordProvider
from pyicloud_ipd.file_match import FileMatchPolicy
from pyicloud_ipd.live_photo_mov_filename_policy import LivePhotoMovFilenamePolicy
from pyicloud_ipd.raw_policy import RawTreatmentPolicy
from pyicloud_ipd.version_size import AssetVersionSize, LivePhotoVersionSize
from tests.helpers import (
    frozen_tz,
    path_from_project_root,
    run_icloudpd_test,
    run_main,
)


class CliTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self, caplog: pytest.LogCaptureFixture) -> None:
        self._caplog = caplog
        self.root_path = path_from_project_root(__file__)
        self.fixtures_path = os.path.join(self.root_path, "fixtures")

    def test_cli_help(self) -> None:
        result = format_help()
        # Test that help output contains key sections and content rather than exact formatting
        self.assertIn(
            "usage: icloudpd [GLOBAL] [COMMON] [<USER> [COMMON] <USER> [COMMON] ...]", result
        )
        self.assertIn("GLOBAL options. Applied for all user settings.", result)
        self.assertIn(
            "COMMON options. If specified before the first username, then used as defaults for settings for all users.",
            result,
        )
        self.assertIn("USER options. Can be specified for setting user configuration only.", result)

        # Test that all major options are present
        self.assertIn("--help, -h", result)
        self.assertIn("--version", result)
        self.assertIn("--username", result)
        self.assertIn("--directory", result)
        self.assertIn("--password-provider", result)
        self.assertIn("--mfa-provider", result)
        self.assertIn("--size", result)
        self.assertIn("--live-photo-size", result)
        self.assertIn("--auth-only", result)
        self.assertIn("--dry-run", result)

        # Test that option descriptions are present
        self.assertIn("Show this information", result)
        self.assertIn("Show the version, commit hash, and timestamp", result)
        self.assertIn("Apple ID email address. Starts a new configuration", result)
        # Directory option exists with proper help text (format varies by Python version)
        self.assertTrue(
            "-d, --directory DIRECTORY" in result
            or "-d DIRECTORY, --directory DIRECTORY" in result,
            "Expected directory option format not found in help text",
        )
        self.assertIn("Local directory to use for downloads", result)

    def test_cli_parser(self) -> None:
        with frozen_tz("Etc/UTC"):
            self.assertEqual.__self__.maxDiff = None  # type: ignore[attr-defined]
            self.assertEqual(
                parse(["--help"]),
                (
                    GlobalConfig(
                        help=True,
                        version=False,
                        use_os_locale=False,
                        only_print_filenames=False,
                        log_level=LogLevel.DEBUG,
                        no_progress_bar=False,
                        threads_num=1,
                        domain="com",
                        watch_with_interval=None,
                        password_providers=[
                            PasswordProvider.PARAMETER,
                            PasswordProvider.KEYRING,
                            PasswordProvider.CONSOLE,
                        ],
                        mfa_provider=MFAProvider.CONSOLE,
                        webui_port=2011,
                    ),
                    [],
                ),
                "--help",
            )
            self.assertEqual(
                parse(["--mfa-provider", "weBui"]),
                (
                    GlobalConfig(
                        help=False,
                        version=False,
                        use_os_locale=False,
                        only_print_filenames=False,
                        log_level=LogLevel.DEBUG,
                        no_progress_bar=False,
                        threads_num=1,
                        domain="com",
                        watch_with_interval=None,
                        password_providers=[
                            PasswordProvider.PARAMETER,
                            PasswordProvider.KEYRING,
                            PasswordProvider.CONSOLE,
                        ],
                        mfa_provider=MFAProvider.WEBUI,
                        webui_port=2011,
                    ),
                    [],
                ),
                "--mfa-provider weBui",
            )
            self.assertEqual(
                parse(
                    [
                        "--password-provider",
                        "weBui",
                        "--password-provider",
                        "CoNSoLe",
                        "--password-provider",
                        "WeBuI",
                    ]
                ),
                (
                    GlobalConfig(
                        help=False,
                        version=False,
                        use_os_locale=False,
                        only_print_filenames=False,
                        log_level=LogLevel.DEBUG,
                        no_progress_bar=False,
                        threads_num=1,
                        domain="com",
                        watch_with_interval=None,
                        password_providers=[PasswordProvider.WEBUI, PasswordProvider.CONSOLE],
                        mfa_provider=MFAProvider.CONSOLE,
                        webui_port=2011,
                    ),
                    [],
                ),
                "password-providers",
            )
            self.assertEqual(
                parse(["--version", "--use-os-locale"]),
                (
                    GlobalConfig(
                        help=False,
                        version=True,
                        use_os_locale=True,
                        only_print_filenames=False,
                        log_level=LogLevel.DEBUG,
                        no_progress_bar=False,
                        threads_num=1,
                        domain="com",
                        watch_with_interval=None,
                        password_providers=[
                            PasswordProvider.PARAMETER,
                            PasswordProvider.KEYRING,
                            PasswordProvider.CONSOLE,
                        ],
                        mfa_provider=MFAProvider.CONSOLE,
                        webui_port=2011,
                    ),
                    [],
                ),
                "--version --use-os-locale",
            )
            self.assertEqual(
                parse(
                    ["--directory", "abc", "--username", "u1", "--username", "u2", "--directory", "def"]
                ),
                (
                    GlobalConfig(
                        help=False,
                        version=False,
                        use_os_locale=False,
                        only_print_filenames=False,
                        log_level=LogLevel.DEBUG,
                        no_progress_bar=False,
                        threads_num=1,
                        domain="com",
                        watch_with_interval=None,
                        password_providers=[
                            PasswordProvider.PARAMETER,
                            PasswordProvider.KEYRING,
                            PasswordProvider.CONSOLE,
                        ],
                        mfa_provider=MFAProvider.CONSOLE,
                        webui_port=2011,
                    ),
                    [
                        UserConfig(
                            directory="abc",
                            username="u1",
                            auth_only=False,
                            cookie_directory="~/.pyicloud",
                            password=None,
                            password_file=None,
                            sizes=[AssetVersionSize.ORIGINAL],
                            live_photo_size=LivePhotoVersionSize.ORIGINAL,
                            recent=None,
                            until_found=None,
                            albums=[],
                            list_albums=False,
                            library="PrimarySync",
                            list_libraries=False,
                            skip_videos=False,
                            skip_live_photos=False,
                            xmp_sidecar=False,
                            force_size=False,
                            auto_delete=False,
                            folder_structure="{:%Y/%m/%d}",
                            set_exif_datetime=False,
                            notification_script=None,
                            delete_after_download=False,
                            keep_icloud_recent_days=None,
                            dry_run=False,
                            keep_unicode_in_filenames=False,
                            live_photo_mov_filename_policy=LivePhotoMovFilenamePolicy.SUFFIX,
                            align_raw=RawTreatmentPolicy.AS_IS,
                            file_match_policy=FileMatchPolicy.NAME_SIZE_DEDUP_WITH_SUFFIX,
                            skip_created_before=None,
                            skip_created_after=None,
                            skip_photos=False,
                        ),
                        UserConfig(
                            directory="def",
                            auth_only=False,
                            cookie_directory="~/.pyicloud",
                            username="u2",
                            password=None,
                            password_file=None,
                            sizes=[AssetVersionSize.ORIGINAL],
                            live_photo_size=LivePhotoVersionSize.ORIGINAL,
                            recent=None,
                            until_found=None,
                            albums=[],
                            list_albums=False,
                            library="PrimarySync",
                            list_libraries=False,
                            skip_videos=False,
                            skip_live_photos=False,
                            xmp_sidecar=False,
                            force_size=False,
                            auto_delete=False,
                            folder_structure="{:%Y/%m/%d}",
                            set_exif_datetime=False,
                            notification_script=None,
                            delete_after_download=False,
                            keep_icloud_recent_days=None,
                            dry_run=False,
                            keep_unicode_in_filenames=False,
                            live_photo_mov_filename_policy=LivePhotoMovFilenamePolicy.SUFFIX,
                            align_raw=RawTreatmentPolicy.AS_IS,
                            file_match_policy=FileMatchPolicy.NAME_SIZE_DEDUP_WITH_SUFFIX,
                            skip_created_before=None,
                            skip_created_after=None,
                            skip_photos=False,
                        ),
                    ],
                ),
                "defaults propagated and overwritten",
            )
            self.assertEqual(
                parse(
                    [
                        "-d",
                        "abc",
                        "--username",
                        "u1",
                        "--skip-created-before",
                        "2025-01-02",
                        "--skip-created-after",
                        "2d",
                    ]
                ),
                (
                    GlobalConfig(
                        help=False,
                        version=False,
                        use_os_locale=False,
                        only_print_filenames=False,
                        log_level=LogLevel.DEBUG,
                        no_progress_bar=False,
                        threads_num=1,
                        domain="com",
                        watch_with_interval=None,
                        password_providers=[
                            PasswordProvider.PARAMETER,
                            PasswordProvider.KEYRING,
                            PasswordProvider.CONSOLE,
                        ],
                        mfa_provider=MFAProvider.CONSOLE,
                        webui_port=2011,
                    ),
                    [
                        UserConfig(
                            directory="abc",
                            username="u1",
                            auth_only=False,
                            cookie_directory="~/.pyicloud",
                            password=None,
                            password_file=None,
                            sizes=[AssetVersionSize.ORIGINAL],
                            live_photo_size=LivePhotoVersionSize.ORIGINAL,
                            recent=None,
                            until_found=None,
                            albums=[],
                            list_albums=False,
                            library="PrimarySync",
                            list_libraries=False,
                            skip_videos=False,
                            skip_live_photos=False,
                            xmp_sidecar=False,
                            force_size=False,
                            auto_delete=False,
                            folder_structure="{:%Y/%m/%d}",
                            set_exif_datetime=False,
                            notification_script=None,
                            delete_after_download=False,
                            keep_icloud_recent_days=None,
                            dry_run=False,
                            keep_unicode_in_filenames=False,
                            live_photo_mov_filename_policy=LivePhotoMovFilenamePolicy.SUFFIX,
                            align_raw=RawTreatmentPolicy.AS_IS,
                            file_match_policy=FileMatchPolicy.NAME_SIZE_DEDUP_WITH_SUFFIX,
                            skip_created_before=datetime.datetime(
                                year=2025, month=1, day=2, tzinfo=zoneinfo.ZoneInfo(key="Etc/UTC")
                            ),
                            skip_created_after=datetime.timedelta(days=2),
                            skip_photos=False,
                        ),
                    ],
                ),
                "valid skip-created parsed",
            )
            with pytest.raises(
                ArgumentError,
                match="argument --skip-created-before: Not an ISO timestamp or time interval in days",
            ):
                _ = parse(
                    [
                        "-d",
                        "abc",
                        "--username",
                        "u1",
                        "--skip-created-before",
                        "2025-01-33",
                        "--skip-created-after",
                        "2d",
                    ]
                )
            with pytest.raises(
                ArgumentError,
                match="argument --skip-created-after: Not an ISO timestamp or time interval in days",
            ):
                _ = parse(
                    [
                        "-d",
                        "abc",
                        "--username",
                        "u1",
                        "--skip-created-before",
                        "2025-01-02",
                        "--skip-created-after",
                        "2",
                    ]
                )

    def test_cli(self) -> None:
        result = run_main(["--help"])
        self.assertEqual(result.exit_code, 0, "exit code")

    def test_log_levels(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])

        parameters: Sequence[Tuple[str, Sequence[str], Sequence[str]]] = [
            ("debug", ["DEBUG", "INFO"], []),
            ("info", ["INFO"], ["DEBUG"]),
            ("error", [], ["DEBUG", "INFO"]),
        ]
        for log_level, expected, not_expected in parameters:
            self._caplog.clear()
            _, result = run_icloudpd_test(
                self.assertEqual,
                self.root_path,
                base_dir,
                "listing_photos.yml",
                [],
                [],
                [
                    "--username",
                    "jdoe@gmail.com",
                    "--password",
                    "password1",
                    "--recent",
                    "0",
                    "--log-level",
                    log_level,
                ],
            )
            self.assertEqual(result.exit_code, 0, "exit code")
            for text in expected:
                self.assertIn(text, self._caplog.text)
            for text in not_expected:
                self.assertNotIn(text, self._caplog.text)

    def test_tqdm(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])

        _, result = run_icloudpd_test(
            self.assertEqual,
            self.root_path,
            base_dir,
            "listing_photos.yml",
            [],
            [],
            [
                "--username",
                "jdoe@gmail.com",
                "--password",
                "password1",
                "--recent",
                "0",
            ],
            additional_env={"FORCE_TQDM": "yes"},
        )
        self.assertEqual(result.exit_code, 0, "exit code")

    def test_unicode_directory(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])

        _, result = run_icloudpd_test(
            self.assertEqual,
            self.root_path,
            base_dir,
            "listing_photos.yml",
            [],
            [],
            [
                "--username",
                "jdoe@gmail.com",
                "--password",
                "password1",
                "--recent",
                "0",
                "--log-level",
                "info",
            ],
        )
        self.assertEqual(result.exit_code, 0, "exit code")

    def test_missing_directory(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])
        # need path removed
        if os.path.exists(base_dir):
            shutil.rmtree(base_dir)

        result = run_main(
            [
                "--username",
                "jdoe@gmail.com",
                "--password",
                "password1",
                "--recent",
                "0",
                "--log-level",
                "info",
                "-d",
                base_dir,
            ],
        )
        self.assertEqual(result.exit_code, 2, "exit code")

        self.assertFalse(os.path.exists(base_dir), f"{base_dir} exists")

    def test_missing_directory_param(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])
        result = run_main(
            [
                "--username",
                "jdoe@gmail.com",
                "--password",
                "password1",
                "--recent",
                "0",
                "--log-level",
                "info",
            ],
        )
        self.assertEqual(result.exit_code, 2, "exit code")

        self.assertFalse(os.path.exists(base_dir), f"{base_dir} exists")

    def test_conflict_options_delete_after_download_and_auto_delete(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])
        result = run_main(
            [
                "--username",
                "jdoe@gmail.com",
                "--password",
                "password1",
                "-d",
                "/tmp",
                "--delete-after-download",
                "--auto-delete",
            ],
        )
        self.assertEqual(result.exit_code, 2, "exit code")

        self.assertFalse(os.path.exists(base_dir), f"{base_dir} exists")

    def test_conflict_options_delete_after_download_and_keep_icloud_recent_days(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])
        result = run_main(
            [
                "--username",
                "jdoe@gmail.com",
                "--password",
                "password1",
                "-d",
                "/tmp",
                "--delete-after-download",
                "--keep-icloud-recent-days",
                "1",
            ],
        )
        self.assertEqual(result.exit_code, 2, "exit code")

        self.assertFalse(os.path.exists(base_dir), f"{base_dir} exists")


def test_session_expiry_options_parse_custom_values() -> None:
    _global_config, user_configs = parse(
        [
            "--directory",
            "abc",
            "--username",
            "u1",
            "--session-expiry-warning-days",
            "3",
            "--session-expiry-notification-interval-hours",
            "12",
        ]
    )
    assert user_configs[0].session_expiry_warning_days == 3
    assert user_configs[0].session_expiry_notification_interval_hours == 12


def test_session_expiry_options_default_values() -> None:
    _global_config, user_configs = parse(["--directory", "abc", "--username", "u1"])
    assert user_configs[0].session_expiry_warning_days == 7
    assert user_configs[0].session_expiry_notification_interval_hours == 24


def test_webui_port_default_value() -> None:
    global_config, _user_configs = parse(["--directory", "abc", "--username", "u1"])
    assert global_config.webui_port == 2011


def test_webui_port_custom_value() -> None:
    global_config, _user_configs = parse(
        ["--directory", "abc", "--username", "u1", "--webui-port", "9999"]
    )
    assert global_config.webui_port == 9999


def _write_config(tmp_path: pathlib.Path, data: dict) -> str:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(_yaml.safe_dump(data))
    return str(config_path)


def test_config_file_drives_multi_account_run(tmp_path: pathlib.Path) -> None:
    config_path = _write_config(
        tmp_path,
        {
            "app": {"mfa_provider": "webui", "watch_with_interval": 3600},
            "all_users": {"directory": "/data"},
            "users": [
                {"username": "you@icloud.com"},
                {"username": "partner@icloud.com", "directory": "/data/account2"},
            ],
        },
    )
    global_config, user_configs = parse(["--config", config_path])
    assert global_config.mfa_provider == MFAProvider.WEBUI
    assert global_config.watch_with_interval == 3600
    assert len(user_configs) == 2
    assert user_configs[0].username == "you@icloud.com"
    assert user_configs[0].directory == "/data"
    assert user_configs[1].username == "partner@icloud.com"
    assert user_configs[1].directory == "/data/account2"


def test_cli_arg_overrides_config_file_value(tmp_path: pathlib.Path) -> None:
    config_path = _write_config(
        tmp_path,
        {
            "all_users": {"directory": "/data"},
            "users": [{"username": "you@icloud.com"}],
        },
    )
    _global_config, user_configs = parse(
        ["--config", config_path, "--directory", "/override"]
    )
    assert user_configs[0].directory == "/override"


def test_config_file_and_cli_username_are_mutually_exclusive(tmp_path: pathlib.Path) -> None:
    config_path = _write_config(
        tmp_path,
        {"users": [{"username": "you@icloud.com", "directory": "/data"}]},
    )
    with pytest.raises(ArgumentError, match="users"):
        parse(["--config", config_path, "-u", "someone@icloud.com", "--directory", "/x"])


def test_default_config_path_used_when_no_flag_given(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        _yaml.safe_dump({"users": [{"username": "you@icloud.com", "directory": "/data"}]})
    )
    monkeypatch.setattr("icloudpd.cli.DEFAULT_CONFIG_PATH", str(config_path))
    _global_config, user_configs = parse([])
    assert user_configs[0].username == "you@icloud.com"


def test_password_file_field_is_populated_from_config(tmp_path: pathlib.Path) -> None:
    secret_path = tmp_path / "secret.txt"
    secret_path.write_text("hunter2\n")
    config_path = _write_config(
        tmp_path,
        {
            "users": [
                {
                    "username": "you@icloud.com",
                    "directory": "/data",
                    "password_file": str(secret_path),
                }
            ]
        },
    )
    _global_config, user_configs = parse(["--config", config_path])
    assert user_configs[0].password_file == str(secret_path)


def test_print_config_prints_resolved_yaml_and_returns_zero(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(
        tmp_path,
        {"users": [{"username": "you@icloud.com", "directory": "/data"}]},
    )
    import sys as _sys

    from icloudpd.cli import cli as cli_entrypoint

    old_argv = _sys.argv
    _sys.argv = ["icloudpd", "--config", config_path, "--print-config"]
    try:
        exit_code = cli_entrypoint()
    finally:
        _sys.argv = old_argv

    assert exit_code == 0
    captured = capsys.readouterr()
    parsed = _yaml.safe_load(captured.out)
    assert parsed["users"][0]["username"] == "you@icloud.com"
    assert parsed["users"][0]["directory"] == "/data"
    assert parsed["app"]["mfa_provider"] == "console"
