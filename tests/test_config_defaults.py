import dataclasses

from icloudpd.config import GlobalConfig, UserConfig
from icloudpd.config_defaults import GLOBAL_OPTION_DEFAULTS, USER_OPTION_DEFAULTS


def test_global_option_defaults_cover_every_configurable_global_field() -> None:
    # help/version are pure CLI meta-flags, never config-file-settable
    configurable_fields = {
        f.name for f in dataclasses.fields(GlobalConfig) if f.name not in ("help", "version")
    }
    assert set(GLOBAL_OPTION_DEFAULTS.keys()) == configurable_fields


def test_user_option_defaults_cover_every_configurable_user_field() -> None:
    # username is required per-account identity, never defaulted;
    # password/password_file are secrets, handled separately (never a "default")
    configurable_fields = {
        f.name
        for f in dataclasses.fields(UserConfig)
        if f.name not in ("username", "password", "password_file")
    }
    assert set(USER_OPTION_DEFAULTS.keys()) == configurable_fields
