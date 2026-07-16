"""Proactive warning before an iCloud session's auth cookies actually expire.

Apple's login cookies (X-APPLE-WEBAUTH-USER, X_APPLE_WEB_KB-<hash>) carry
their own Expires timestamp. This module reads the soonest of the two off
the live session's cookie jar and, once remaining time drops under a
configurable threshold, fires a session_expiring_soon notification event
at most once per a configurable interval.

All operations here are best-effort: failures are logged and swallowed
rather than raised, matching notifications.py and manifest.py - this
check running (or failing to run) must never block or fail a download.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from typing import Iterable, Protocol

from pyicloud_ipd.base import sanitize_apple_id

_EVENT_TYPE = "session_expiring_soon"
_EXACT_COOKIE_NAMES = ("X-APPLE-WEBAUTH-USER",)
_COOKIE_PREFIX = "X_APPLE_WEB_KB-"


class _CookieLike(Protocol):
    name: str
    expires: float | None


def _is_relevant_cookie(name: str) -> bool:
    return name in _EXACT_COOKIE_NAMES or name.startswith(_COOKIE_PREFIX)


def earliest_relevant_expiry(cookies: Iterable[_CookieLike]) -> datetime.datetime | None:
    """Earliest Expires timestamp across the cookies that govern session validity.

    Returns None if neither relevant cookie is present, or neither carries
    expiry data - callers should skip the check silently in that case.
    """
    expiries = [
        cookie.expires
        for cookie in cookies
        if _is_relevant_cookie(cookie.name) and cookie.expires is not None
    ]
    if not expiries:
        return None
    return datetime.datetime.fromtimestamp(min(expiries), tz=datetime.timezone.utc)


def state_file_path(cookie_directory: str, username: str) -> str:
    normalized_dir = os.path.expanduser(os.path.normpath(cookie_directory))
    return os.path.join(normalized_dir, sanitize_apple_id(username) + ".notify_state.json")


def _load_last_warned(logger: logging.Logger, path: str) -> datetime.datetime | None:
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as ex:
        logger.warning("Could not read notification state %s: %s", path, ex)
        return None

    raw = state.get(_EVENT_TYPE, {}).get("last_warned_utc")
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(raw)
    except ValueError as ex:
        logger.warning("Could not parse notification state %s: %s", path, ex)
        return None


def _save_last_warned(logger: logging.Logger, path: str, when: datetime.datetime) -> None:
    state: dict[str, dict[str, str]] = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, json.JSONDecodeError):
            state = {}

    state[_EVENT_TYPE] = {"last_warned_utc": when.isoformat()}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError as ex:
        logger.warning("Could not write notification state %s: %s", path, ex)
