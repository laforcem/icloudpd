"""Single source of truth for icloudpd's built-in option defaults.

These used to be baked into argparse's `add_argument(default=...)` calls.
They now live here so argparse can use `default=None` everywhere (making
"not passed on the CLI" distinguishable from "passed, matches the default"),
with these values applied as the final fallback in `map_to_config` /
`map_to_global_config`.
"""

from typing import Any, Dict

# Path baked into the icloudpd image (see Dockerfile) for the generic
# stdin-JSON-to-URL notification forwarder. `notification_forwarder: true`
# in a user's config resolves to this path instead of requiring it spelled
# out (and kept in sync) in every deployment.
BUILTIN_NOTIFICATION_FORWARDER_PATH = "/usr/local/bin/notification_script.py"

GLOBAL_OPTION_DEFAULTS: Dict[str, Any] = {
    "use_os_locale": False,
    "only_print_filenames": False,
    "log_level": "debug",
    "no_progress_bar": False,
    "threads_num": 1,
    "domain": "com",
    "watch_with_interval": None,
    "password_providers": ["parameter", "keyring", "console"],
    "mfa_provider": "console",
    "webui_port": 2011,
}

USER_OPTION_DEFAULTS: Dict[str, Any] = {
    "directory": None,
    "auth_only": False,
    "cookie_directory": "~/.pyicloud",
    "sizes": ["original"],
    "live_photo_size": "original",
    "recent": None,
    "until_found": None,
    "albums": [],
    "list_albums": False,
    "library": "PrimarySync",
    "list_libraries": False,
    "skip_videos": False,
    "skip_live_photos": False,
    "xmp_sidecar": False,
    "force_size": False,
    "auto_delete": False,
    "folder_structure": "{:%Y/%m/%d}",
    "set_exif_datetime": False,
    "notification_script": None,
    "notification_forwarder": False,
    "session_expiry_warning_days": 7,
    "session_expiry_notification_interval_hours": 24,
    "delete_after_download": False,
    "keep_icloud_recent_days": None,
    "dry_run": False,
    "keep_unicode_in_filenames": False,
    "live_photo_mov_filename_policy": "suffix",
    "align_raw": "as-is",
    "file_match_policy": "name-size-dedup-with-suffix",
    "skip_created_before": None,
    "skip_created_after": None,
    "skip_photos": False,
}
