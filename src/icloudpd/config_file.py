"""Loading, validating, and coercing icloudpd's YAML config file.

The file has three top-level sections:
  - `app`: process-wide settings (maps onto GlobalConfig).
  - `all_users`: per-account defaults, applied to every entry in `users`
    unless that entry overrides a given key.
  - `users`: a list of per-account blocks (maps onto UserConfig).

Secrets are never inline: any `*_file` key names a path to a file
containing the value, read once by the caller. A literal `password:` key
is rejected outright — `password_file` is the only supported form.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

import yaml

from icloudpd.config_defaults import GLOBAL_OPTION_DEFAULTS, USER_OPTION_DEFAULTS
from icloudpd.string_helpers import parse_timestamp_or_timedelta

KNOWN_TOP_LEVEL_SECTIONS = {"app", "all_users", "users"}

# Fields whose raw YAML value needs the same conversion argparse's `type=`
# used to apply to a CLI string, before being merged with CLI/default values.
_LOWERCASE_FIELDS = {
    "log_level",
    "mfa_provider",
    "live_photo_size",
    "live_photo_mov_filename_policy",
    "align_raw",
    "file_match_policy",
}

# Keys allowed under `app` (GlobalConfig fields), and under `all_users`/each
# `users[]` entry (UserConfig fields, plus the two fields that only exist in
# the config file's user shape).
_ALLOWED_APP_KEYS = set(GLOBAL_OPTION_DEFAULTS.keys())
_ALLOWED_USER_KEYS = set(USER_OPTION_DEFAULTS.keys()) | {"username", "password_file"}

# Fields that are legitimately typed as `bool` on GlobalConfig/UserConfig
# (see src/icloudpd/config.py). Any *other* field that comes back from YAML
# as a Python bool is almost certainly the "Norway problem": an unquoted
# yes/no/on/off/true/false value that YAML 1.1 silently coerced to a bool
# instead of the string the user meant.
_GLOBAL_BOOL_FIELDS = {"use_os_locale", "only_print_filenames", "no_progress_bar"}
_USER_BOOL_FIELDS = {
    "auth_only",
    "list_albums",
    "list_libraries",
    "skip_videos",
    "skip_live_photos",
    "xmp_sidecar",
    "force_size",
    "auto_delete",
    "set_exif_datetime",
    "delete_after_download",
    "dry_run",
    "keep_unicode_in_filenames",
    "skip_photos",
    "notification_forwarder",
}


class ConfigFileError(ValueError):
    """Raised for any structural problem in the config file (fails loudly at startup)."""


@dataclass
class RawConfigFile:
    app: Dict[str, Any]
    all_users: Dict[str, Any]
    users: List[Dict[str, Any]]


def _coerce_scalar_fields(raw: Dict[str, Any]) -> Dict[str, Any]:
    coerced = dict(raw)
    for field in _LOWERCASE_FIELDS:
        if field in coerced and isinstance(coerced[field], str):
            coerced[field] = coerced[field].lower()
    if "sizes" in coerced and isinstance(coerced["sizes"], list):
        coerced["sizes"] = [
            v.lower() if isinstance(v, str) else v for v in coerced["sizes"]
        ]
    if "password_providers" in coerced and isinstance(coerced["password_providers"], list):
        coerced["password_providers"] = [
            v.lower() if isinstance(v, str) else v for v in coerced["password_providers"]
        ]
    for field in ("skip_created_before", "skip_created_after"):
        if field in coerced and coerced[field] is not None:
            value = parse_timestamp_or_timedelta(str(coerced[field]))
            if value is None:
                raise ConfigFileError(
                    f"`{field}` did not parse as an ISO timestamp or interval: {coerced[field]!r}"
                )
            coerced[field] = value
    return coerced


def _validate_user_entry(entry: Dict[str, Any], index: int) -> None:
    if "password" in entry:
        raise ConfigFileError(
            f"users[{index}]: literal `password` is not supported in the config file — "
            "use `password_file` (a path to a file containing the password) instead. "
            "Secrets are never written directly into this file."
        )
    if "username" not in entry:
        raise ConfigFileError(f"users[{index}]: `username` is required for every account")


def _validate_known_keys(
    location: str, entry: Dict[str, Any], allowed: set[str]
) -> None:
    unknown = sorted(set(entry.keys()) - allowed)
    if unknown:
        raise ConfigFileError(
            f"{location}: unknown key(s) {unknown!r}; check for typos. "
            f"Recognized keys: {sorted(allowed)!r}"
        )


def _validate_bool_mistyping(location: str, entry: Dict[str, Any], bool_fields: set[str]) -> None:
    for field, value in entry.items():
        if isinstance(value, bool) and field not in bool_fields:
            raise ConfigFileError(
                f"{location}: `{field}` was parsed as the YAML boolean {value!r}, but this "
                "field expects a string/other value, not true/false. This is usually the "
                "YAML \"Norway problem\": unquoted words like yes/no/on/off/true/false are "
                f"parsed as booleans. Quote the value instead, e.g. `{field}: \"{'yes' if value else 'no'}\"`."
            )


def load_config_file(path: str) -> RawConfigFile:
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigFileError(f"{path}: failed to parse YAML: {e}") from e

    if not isinstance(raw, dict):
        raise ConfigFileError(f"{path}: top level of the config file must be a mapping")

    unknown_sections = set(raw.keys()) - KNOWN_TOP_LEVEL_SECTIONS
    if unknown_sections:
        raise ConfigFileError(
            f"{path}: unknown top-level section(s) {sorted(unknown_sections)!r}; "
            f"only {sorted(KNOWN_TOP_LEVEL_SECTIONS)!r} are supported"
        )

    app = _coerce_scalar_fields(raw.get("app") or {})
    _validate_known_keys("app", app, _ALLOWED_APP_KEYS)
    _validate_bool_mistyping("app", app, _GLOBAL_BOOL_FIELDS)

    all_users = _coerce_scalar_fields(raw.get("all_users") or {})
    _validate_known_keys("all_users", all_users, _ALLOWED_USER_KEYS)
    _validate_bool_mistyping("all_users", all_users, _USER_BOOL_FIELDS)

    users: List[Dict[str, Any]] = []
    for index, entry in enumerate(raw.get("users") or []):
        _validate_user_entry(entry, index)
        coerced_entry = _coerce_scalar_fields(entry)
        _validate_known_keys(f"users[{index}]", coerced_entry, _ALLOWED_USER_KEYS)
        _validate_bool_mistyping(f"users[{index}]", coerced_entry, _USER_BOOL_FIELDS)
        users.append(coerced_entry)

    return RawConfigFile(app=app, all_users=all_users, users=users)


def merge_user_dict(all_users: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
    """A user entry's own keys override the shared `all_users` defaults, field by field."""
    return {**all_users, **user}


def dump_resolved_config(app: Dict[str, Any], users: Sequence[Dict[str, Any]]) -> str:
    """Serialize the fully-resolved configuration for `--print-config`."""
    return yaml.safe_dump({"app": app, "users": list(users)}, sort_keys=False)
