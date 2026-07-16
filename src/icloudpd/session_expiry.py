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
from typing import Iterable, Protocol

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
