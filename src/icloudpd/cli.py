import argparse
import copy
import datetime
import os
import pathlib
import sys
from itertools import dropwhile
from operator import eq, not_
from typing import Any, Callable, Dict, Iterable, List, Sequence, Tuple

from tzlocal import get_localzone

import foundation
from foundation.core import chain_from_iterable, compose, map_, partial_1_1, skip
from foundation.string_utils import lower
from icloudpd.base import ensure_tzinfo, run_with_configs
from icloudpd.config import GlobalConfig, UserConfig
from icloudpd.config_defaults import GLOBAL_OPTION_DEFAULTS, USER_OPTION_DEFAULTS
from icloudpd.config_file import (
    ConfigFileError,
    dump_resolved_config,
    load_config_file,
    merge_user_dict,
)
from icloudpd.log_level import LogLevel
from icloudpd.mfa_provider import MFAProvider
from icloudpd.password_provider import PasswordProvider
from icloudpd.string_helpers import parse_timestamp_or_timedelta, splitlines
from pyicloud_ipd.file_match import FileMatchPolicy
from pyicloud_ipd.live_photo_mov_filename_policy import LivePhotoMovFilenamePolicy
from pyicloud_ipd.raw_policy import RawTreatmentPolicy
from pyicloud_ipd.version_size import AssetVersionSize, LivePhotoVersionSize


def map_align_raw_to_enum(align_raw_str: str) -> RawTreatmentPolicy:
    """Map user-friendly CLI strings to RawTreatmentPolicy enum values."""
    mapping = {
        "as-is": RawTreatmentPolicy.AS_IS,
        "original": RawTreatmentPolicy.AS_ORIGINAL,
        "alternative": RawTreatmentPolicy.AS_ALTERNATIVE,
    }
    return mapping[align_raw_str]


def add_options_for_user(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    cloned = copy.deepcopy(parser)
    cloned.add_argument(
        "-d",
        "--directory",
        metavar="DIRECTORY",
        help="Local directory to use for downloads",
    )
    cloned.add_argument(
        "--auth-only",
        action="store_true",
        default=None,
        help="Create/update cookie and session tokens only.",
    )
    cloned.add_argument(
        "--cookie-directory",
        help="Directory to store cookies for authentication. Default: ~/.pyicloud",
        default=None,
    )
    cloned.add_argument(
        "--size",
        help="Image size to download. `medium` and `thumb` will always be added as suffixes to filenames, `adjusted` and `alternative` only if conflicting, `original` never. If `adjusted` or `alternative` is specified and missing, then `original` is used. Default: original",
        choices=["original", "medium", "thumb", "adjusted", "alternative"],
        default=None,
        action="append",
        dest="sizes",
        type=lower,
    )
    cloned.add_argument(
        "--live-photo-size",
        help="Live Photo video size to download. Default: original",
        choices=["original", "medium", "thumb"],
        default=None,
        action="store",
        type=lower,
    )
    cloned.add_argument(
        "--recent",
        help="Number of recent photos to download (default: download all photos)",
        type=int,
        default=None,
    )
    cloned.add_argument(
        "--until-found",
        help="Download the most recently added photos until we find X number of "
        "previously downloaded consecutive photos (default: download all photos)",
        type=int,
        default=None,
    )
    cloned.add_argument(
        "-a",
        "--album",
        help="Album(s) to download, or the whole collection if not specified",
        action="append",
        default=None,
        dest="albums",
    )
    cloned.add_argument(
        "-l",
        "--list-albums",
        help="List the available albums",
        action="store_true",
        default=None,
    )
    cloned.add_argument(
        "--library",
        help="Library to download. Default: PrimarySync",
        default=None,
    )
    cloned.add_argument(
        "--list-libraries",
        help="List the available libraries",
        action="store_true",
        default=None,
    )
    cloned.add_argument(
        "--skip-videos",
        help="Don't download any videos (default: download all photos and videos)",
        action="store_true",
        default=None,
    )
    cloned.add_argument(
        "--skip-live-photos",
        help="Don't download any live photos (default: download live photos)",
        action="store_true",
        default=None,
    )
    cloned.add_argument(
        "--xmp-sidecar",
        help="Export additional data as XMP sidecar files (default: don't export)",
        action="store_true",
        default=None,
    )
    cloned.add_argument(
        "--force-size",
        help="Only download the requested size (`adjusted` and `alternative` will not be forced). Default: download original if size is not available",
        action="store_true",
        default=None,
    )
    cloned.add_argument(
        "--auto-delete",
        help='Scan the "Recently Deleted" folder and delete any files found there. '
        + "(If you restore the photo in iCloud, it will be downloaded again.)",
        action="store_true",
        default=None,
    )
    cloned.add_argument(
        "--folder-structure",
        help="Folder structure. If set to `none`, all photos will be placed into the download directory. Default: {:%%Y/%%m/%%d}",
        default=None,
        type=validate_folder_structure,
    )
    cloned.add_argument(
        "--set-exif-datetime",
        help="Write the DateTimeOriginal EXIF tag from file creation date, if it doesn't exist.",
        action="store_true",
        default=None,
    )

    cloned.add_argument(
        "--notification-script",
        type=pathlib.Path,
        help="Path to external script to run when a notification event occurs "
        "(e.g. two-step authentication expiring). Invoked with a JSON payload "
        "describing the event on stdin.",
        default=None,
    )
    cloned.add_argument(
        "--session-expiry-warning-days",
        type=int,
        help="Start warning this many days before the iCloud session's auth cookies expire. "
        "Set to 0 to disable the proactive warning (the reactive session_expired event, "
        "fired when a run actually hits the 2FA/2SA challenge, is unaffected). "
        "Default: 7",
        default=None,
    )
    cloned.add_argument(
        "--session-expiry-notification-interval-hours",
        type=int,
        help="Minimum hours between repeated session-expiry warnings while inside the "
        "warning window. Default: 24",
        default=None,
    )
    deprecated_kwargs: dict[str, Any] = {}
    if sys.version_info >= (3, 13):
        deprecated_kwargs["deprecated"] = True
    cloned.add_argument(
        "--delete-after-download",
        help="Delete the photo/video after downloading it."
        + ' The deleted items will appear in "Recently Deleted".'
        + " Therefore, should not be combined with --auto-delete option.",
        action="store_true",
        default=None,
        **deprecated_kwargs,
    )
    cloned.add_argument(
        "--keep-icloud-recent-days",
        help="Keep photos newer than this many days in iCloud. Delete the rest. "
        + "If set to 0, all photos will be deleted from iCloud.",
        type=int,
        default=None,
    )
    cloned.add_argument(
        "--dry-run",
        help="Do not modify the local system or iCloud",
        action="store_true",
        default=None,
    )
    cloned.add_argument(
        "--keep-unicode-in-filenames",
        help="Keep Unicode characters in filenames, or remove all non-ASCII characters",
        action="store_true",
        default=None,
    )
    cloned.add_argument(
        "--live-photo-mov-filename-policy",
        help="How to produce filenames for the video portion of live photos: `suffix` will add _HEVC suffix and `original` will keep the filename as is. Default: suffix",
        choices=["suffix", "original"],
        default=None,
        type=lower,
    )
    cloned.add_argument(
        "--align-raw",
        help="For photo assets with RAW and JPEG, always treat RAW in the specified size: `original` (RAW+JPEG), `alternative` (JPEG+RAW), or unchanged (as-is). This matters when choosing sizes to download. Default: as-is",
        choices=["as-is", "original", "alternative"],
        default=None,
        type=lower,
    )
    cloned.add_argument(
        "--file-match-policy",
        help="Policy to identify existing files and de-duplicate. `name-size-dedup-with-suffix` appends file size to de-duplicate. `name-id7` adds asset ID from iCloud to all filenames and does not de-duplicate. Default: name-size-dedup-with-suffix",
        choices=["name-size-dedup-with-suffix", "name-id7"],
        default=None,
        type=lower,
    )
    cloned.add_argument(
        "--skip-created-before",
        help="Do not process assets created before the specified timestamp in ISO format (2025-01-02) or interval backwards from now (20d = 20 days ago)",
        default=None,
        type=parse_timestamp_or_timedelta_tz_error,
    )
    cloned.add_argument(
        "--skip-created-after",
        help="Do not process assets created after the specified timestamp in ISO format (2025-01-02) or interval backwards from now (20d = 20 days ago)",
        default=None,
        type=parse_timestamp_or_timedelta_tz_error,
    )
    cloned.add_argument(
        "--skip-photos",
        help="Don't download any photos (default: download all photos and videos)",
        action="store_true",
        default=None,
    )
    return cloned


def add_user_option(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    cloned = copy.deepcopy(parser)
    cloned.add_argument(
        "-u",
        "--username",
        help="Apple ID email address. Starts a new configuration group.",
        type=lower,
    )
    cloned.add_argument(
        "-p",
        "--password",
        help="iCloud password for the account if `--password-provider` specifies `parameter`",
        default=None,
        type=str,
    )
    cloned.add_argument(
        "--password-file",
        help="Path to a file containing the iCloud password for the account "
        "(alternative to `--password` that keeps the value out of argv/process listing) "
        "if `--password-provider` specifies `parameter`",
        default=None,
        type=str,
    )
    return cloned


def parse_mfa_provider(provider: str) -> MFAProvider:
    provider_map = {
        "console": MFAProvider.CONSOLE,
        "webui": MFAProvider.WEBUI,
    }

    normalized_provider = lower(provider)
    if normalized_provider in provider_map:
        return provider_map[normalized_provider]
    else:
        raise ValueError(f"Only `console` and `webui` are supported, but `{provider}` was provided")


DEFAULT_CONFIG_PATH = "/etc/icloudpd/config.yaml"


def add_global_options(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    cloned = copy.deepcopy(parser)
    group = cloned.add_mutually_exclusive_group()
    group.add_argument("--help", "-h", action="store_true", help="Show this information")
    group.add_argument(
        "--version", help="Show the version, commit hash, and timestamp", action="store_true"
    )
    cloned.add_argument(
        "--use-os-locale",
        help="Use the locale of the host OS to format dates",
        action="store_true",
        default=None,
    )
    cloned.add_argument(
        "--only-print-filenames",
        help="Only print the filenames of all files that will be downloaded "
        "(not including files that are already downloaded). "
        + "(Does not download or delete any files.)",
        action="store_true",
        default=None,
    )
    cloned.add_argument(
        "--log-level",
        help="Log level. Default: debug",
        choices=["debug", "info", "error"],
        default=None,
        type=lower,
    )
    cloned.add_argument(
        "--no-progress-bar",
        help="Disable the one-line progress bar and print log messages on separate lines "
        "(progress bar is disabled by default if there is no TTY attached)",
        action="store_true",
        default=None,
    )
    deprecated_kwargs: dict[str, Any] = {}
    if sys.version_info >= (3, 13):
        deprecated_kwargs["deprecated"] = True
    cloned.add_argument(
        "--threads-num",
        help="Number of CPU threads - deprecated & always 1. To be removed in a future version",
        type=int,
        default=None,
        **deprecated_kwargs,
    )
    cloned.add_argument(
        "--domain",
        help="Which iCloud root domain to use. Use 'cn' for mainland China. Default: com",
        choices=["com", "cn"],
        default=None,
    )
    cloned.add_argument(
        "--watch-with-interval",
        help="Run downloading in an infinite cycle, waiting the specified seconds between runs",
        type=int,
        default=None,
    )
    cloned.add_argument(
        "--password-provider",
        dest="password_providers",
        help="Specify password providers to check in the given order. Default: [`parameter`, `keyring`, `console`]",
        choices=["console", "keyring", "parameter", "webui"],
        default=None,
        action="append",
        type=lower,
    )
    cloned.add_argument(
        "--mfa-provider",
        help="Specify where to get the MFA code from",
        choices=["console", "webui"],
        default=None,
        type=lower,
    )
    cloned.add_argument(
        "--webui-port",
        help="Port for the WebUI server (used for `webui` password/MFA providers). Default: 2011",
        type=int,
        default=None,
    )
    cloned.add_argument(
        "--config",
        dest="config_path",
        help=f"Path to a YAML config file. Default: use {DEFAULT_CONFIG_PATH} if it exists, "
        "otherwise pure CLI arguments.",
        default=None,
        type=str,
    )
    cloned.add_argument(
        "--print-config",
        help="Print the fully resolved configuration (CLI args + config file + "
        "built-in defaults, merged) as YAML, then exit.",
        action="store_true",
        default=False,
    )
    return cloned


def log_level(inp: str) -> LogLevel:
    if inp == "debug":
        return LogLevel.DEBUG
    elif inp == "info":
        return LogLevel.INFO
    elif inp == "error":
        return LogLevel.ERROR
    else:
        raise argparse.ArgumentTypeError(f"Unsupported log level {inp}")


def parse_timestamp_or_timedelta_tz_error(
    formatted: str | None,
) -> datetime.datetime | datetime.timedelta | None:
    """Convert ISO dates to datetime with tz and interval in days to time interval. Raise exception in case of error."""
    if formatted is None:
        return None
    result = parse_timestamp_or_timedelta(formatted)
    if result is None:
        raise argparse.ArgumentTypeError("Not an ISO timestamp or time interval in days")
    if isinstance(result, datetime.datetime):
        return ensure_tzinfo(get_localzone(), result)
    return result


def format_help_for_parser_(parser: argparse.ArgumentParser) -> str:
    return parser.format_help()


def format_help() -> str:
    # create fake parser and return it's help
    pre_options_predicate: Callable[[str], bool] = compose(not_, partial_1_1(eq, "options:"))
    skip_to_options_header: Callable[[Iterable[str]], Iterable[str]] = partial_1_1(
        dropwhile, pre_options_predicate
    )
    skip_to_options = compose(partial_1_1(skip, 1), skip_to_options_header)

    help_in_lines = compose(splitlines, format_help_for_parser_)

    extract_option_lines = compose(skip_to_options, help_in_lines)

    dummy_parser = argparse.ArgumentParser(exit_on_error=False, add_help=False, allow_abbrev=False)

    global_help = compose(extract_option_lines, add_global_options)(dummy_parser)

    default_help = compose(extract_option_lines, add_options_for_user)(dummy_parser)

    user_help = compose(extract_option_lines, add_user_option)(dummy_parser)

    all_help = chain_from_iterable(
        [
            ["usage: icloudpd [GLOBAL] [COMMON] [<USER> [COMMON] <USER> [COMMON] ...]", ""],
            ["GLOBAL options. Applied for all user settings."],
            global_help,
            [
                "",
                "COMMON options. If specified before the first username, then used as defaults for settings for all users.",
            ],
            default_help,
            ["", "USER options. Can be specified for setting user configuration only."],
            user_help,
        ]
    )

    return "\n".join(all_help)


def map_to_config(user_ns: argparse.Namespace) -> UserConfig:
    def get(field: str) -> Any:
        value = getattr(user_ns, field, None)
        return value if value is not None else USER_OPTION_DEFAULTS[field]

    return UserConfig(
        username=user_ns.username,
        password=getattr(user_ns, "password", None),
        password_file=getattr(user_ns, "password_file", None),
        directory=get("directory"),
        auth_only=get("auth_only"),
        cookie_directory=get("cookie_directory"),
        sizes=list(map_(AssetVersionSize, foundation.unique_sequence(get("sizes")))),
        live_photo_size=LivePhotoVersionSize(get("live_photo_size")),
        recent=get("recent"),
        until_found=get("until_found"),
        albums=get("albums"),
        list_albums=get("list_albums"),
        library=get("library"),
        list_libraries=get("list_libraries"),
        skip_videos=get("skip_videos"),
        skip_live_photos=get("skip_live_photos"),
        xmp_sidecar=get("xmp_sidecar"),
        force_size=get("force_size"),
        auto_delete=get("auto_delete"),
        folder_structure=get("folder_structure"),
        set_exif_datetime=get("set_exif_datetime"),
        notification_script=get("notification_script"),
        session_expiry_warning_days=get("session_expiry_warning_days"),
        session_expiry_notification_interval_hours=get(
            "session_expiry_notification_interval_hours"
        ),
        delete_after_download=get("delete_after_download"),
        keep_icloud_recent_days=get("keep_icloud_recent_days"),
        dry_run=get("dry_run"),
        keep_unicode_in_filenames=get("keep_unicode_in_filenames"),
        live_photo_mov_filename_policy=LivePhotoMovFilenamePolicy(
            get("live_photo_mov_filename_policy")
        ),
        align_raw=map_align_raw_to_enum(get("align_raw")),
        file_match_policy=FileMatchPolicy(get("file_match_policy")),
        skip_created_before=get("skip_created_before"),
        skip_created_after=get("skip_created_after"),
        skip_photos=get("skip_photos"),
    )


def map_to_global_config(global_ns: argparse.Namespace) -> GlobalConfig:
    def get(field: str) -> Any:
        value = getattr(global_ns, field, None)
        return value if value is not None else GLOBAL_OPTION_DEFAULTS[field]

    return GlobalConfig(
        help=global_ns.help,
        version=global_ns.version,
        use_os_locale=get("use_os_locale"),
        only_print_filenames=get("only_print_filenames"),
        log_level=log_level(get("log_level")),
        no_progress_bar=get("no_progress_bar"),
        threads_num=get("threads_num"),
        domain=get("domain"),
        watch_with_interval=get("watch_with_interval"),
        password_providers=list(
            map_(PasswordProvider, foundation.unique_sequence(get("password_providers")))
        ),
        mfa_provider=MFAProvider(get("mfa_provider")),
        webui_port=get("webui_port"),
    )


def parse(args: Sequence[str]) -> Tuple[GlobalConfig, Sequence[UserConfig]]:
    # default --help, unless a config file will be found at the default path
    if len(args) == 0 and not os.path.isfile(DEFAULT_CONFIG_PATH):
        args = ["--help"]
    else:
        pass

    # Extract global options first from anywhere in the args using parse_known_args
    global_parser: argparse.ArgumentParser = add_global_options(
        argparse.ArgumentParser(exit_on_error=False, add_help=False, allow_abbrev=False)
    )
    global_ns, non_global_args = global_parser.parse_known_args(args)

    config_path = global_ns.config_path or (
        DEFAULT_CONFIG_PATH if os.path.isfile(DEFAULT_CONFIG_PATH) else None
    )

    # Now split the remaining non-global args by username boundaries
    splitted_args = foundation.split_with_alternatives(["-u", "--username"], non_global_args)
    default_args = splitted_args[0]
    cli_specifies_users = len(splitted_args) > 1

    default_parser: argparse.ArgumentParser = add_options_for_user(
        argparse.ArgumentParser(exit_on_error=False, add_help=False, allow_abbrev=False)
    )

    default_ns = default_parser.parse_args(default_args)

    if config_path is not None:
        if cli_specifies_users:
            raise argparse.ArgumentError(
                None,
                "--config (or a config file found at the default path) cannot be combined "
                "with -u/--username CLI arguments — define accounts in the config file's "
                "`users:` list instead.",
            )
        raw_config = load_config_file(config_path)

        # CLI values given alongside --config act as a uniform override for every account,
        # since there's no per-account CLI targeting available in config-file mode.
        global_overrides = {
            field: getattr(global_ns, field, None) for field in GLOBAL_OPTION_DEFAULTS
        }
        merged_global_raw = {
            field: (
                global_overrides[field]
                if global_overrides[field] is not None
                else raw_config.app.get(field)
            )
            for field in GLOBAL_OPTION_DEFAULTS
        }
        for field, value in merged_global_raw.items():
            setattr(global_ns, field, value)

        cli_user_overrides = {
            field: getattr(default_ns, field, None) for field in USER_OPTION_DEFAULTS
        }

        user_nses = []
        for user_entry in raw_config.users:
            merged_user_dict = merge_user_dict(raw_config.all_users, user_entry)
            user_ns = argparse.Namespace()
            user_ns.username = merged_user_dict["username"]
            user_ns.password = None
            user_ns.password_file = merged_user_dict.get("password_file")
            for field in USER_OPTION_DEFAULTS:
                cli_value = cli_user_overrides[field]
                file_value = merged_user_dict.get(field)
                setattr(user_ns, field, cli_value if cli_value is not None else file_value)
            user_nses.append(map_to_config(user_ns))

        return (map_to_global_config(global_ns), user_nses)

    user_parser: argparse.ArgumentParser = add_user_option(
        add_options_for_user(
            argparse.ArgumentParser(exit_on_error=False, add_help=False, allow_abbrev=False)
        )
    )
    user_nses = [
        map_to_config(user_parser.parse_args(user_args, copy.deepcopy(default_ns)))
        for user_args in splitted_args[1:]
    ]

    return (map_to_global_config(global_ns), user_nses)


def _resolved_config_as_dicts(
    global_config: GlobalConfig, user_configs: Sequence[UserConfig]
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    app: Dict[str, Any] = {
        "log_level": global_config.log_level.value,
        "mfa_provider": global_config.mfa_provider.value,
        "watch_with_interval": global_config.watch_with_interval,
        "domain": global_config.domain,
        "webui_port": global_config.webui_port,
        "no_progress_bar": global_config.no_progress_bar,
        "only_print_filenames": global_config.only_print_filenames,
        "use_os_locale": global_config.use_os_locale,
        "threads_num": global_config.threads_num,
        "password_providers": [p.value for p in global_config.password_providers],
    }
    users: List[Dict[str, Any]] = []
    for user_config in user_configs:
        users.append(
            {
                "username": user_config.username,
                "directory": user_config.directory,
                "sizes": [s.value for s in user_config.sizes],
                "skip_videos": user_config.skip_videos,
                "skip_photos": user_config.skip_photos,
                "skip_live_photos": user_config.skip_live_photos,
                "folder_structure": user_config.folder_structure,
                "dry_run": user_config.dry_run,
                "password_file": user_config.password_file,
            }
        )
    return app, users


def cli() -> int:
    try:
        global_ns, user_nses = parse(sys.argv[1:])
    except (argparse.ArgumentError, ConfigFileError) as error:
        print(error)
        return 2
    if "--print-config" in sys.argv:
        app, users = _resolved_config_as_dicts(global_ns, user_nses)
        print(dump_resolved_config(app, users), end="")
        return 0
    if global_ns.use_os_locale:
        from locale import LC_ALL, setlocale

        setlocale(LC_ALL, "")
    else:
        pass
    if global_ns.help:
        print(format_help())
        return 0
    elif global_ns.version:
        print(foundation.version_info_formatted())
        return 0
    else:
        # check param compatibility
        if [user_ns for user_ns in user_nses if user_ns.skip_videos and user_ns.skip_photos]:
            print(
                "Only one of --skip-videos and --skip-photos can be used at a time for each configuration"
            )
            return 2

        # check required directory param only if not list albums
        elif [
            user_ns
            for user_ns in user_nses
            if not user_ns.list_albums
            and not user_ns.list_libraries
            and not user_ns.directory
            and not user_ns.auth_only
        ]:
            print(
                "--auth-only, --directory, --list-libraries, or --list-albums are required for each configuration"
            )
            return 2

        elif [
            user_ns
            for user_ns in user_nses
            if user_ns.auto_delete and user_ns.delete_after_download
        ]:
            print(
                "--auto-delete and --delete-after-download are mutually exclusive per configuration"
            )
            return 2

        elif [
            user_ns
            for user_ns in user_nses
            if user_ns.keep_icloud_recent_days and user_ns.delete_after_download
        ]:
            print(
                "--keep-icloud-recent-days and --delete-after-download should not be used together in one configuration"
            )
            return 2

        elif global_ns.watch_with_interval and (
            [
                user_ns
                for user_ns in user_nses
                if user_ns.list_albums or user_ns.auth_only or user_ns.list_libraries
            ]
            or global_ns.only_print_filenames
        ):
            print(
                "--watch-with-interval is not compatible with --list-albums, --list-libraries, --only-print-filenames, and --auth-only"
            )
            return 2
        else:
            return run_with_configs(global_ns, user_nses)


def validate_folder_structure(folder_structure: str) -> str:
    if lower(folder_structure) == "none":
        return "none"
    else:
        try:
            folder_structure.format(datetime.datetime.now())
            return folder_structure
        except:  # noqa E722
            raise argparse.ArgumentTypeError(
                f"Format {folder_structure} specified in --folder-structure is incorrect"
            ) from None
