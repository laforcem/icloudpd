"""General event notification mechanism.

Delivers structured events (2FA/session expiry, deletion-sync summaries,
etc.) to a single user-configured script as JSON on stdin. This is the
only built-in transport: icloudpd never talks to email/Telegram/Slack/etc.
directly, so it never has to maintain N integrations against N external
APIs. `event_type` is deliberately a plain string, not an enum - adding a
new event type is just a new consumer picking a new string, with no
changes required here.

All operations here are best-effort: failures are logged and swallowed
rather than raised, because a notification failing must never block or
fail a download/deletion-sync run.
"""

from __future__ import annotations

import datetime
import json
import logging
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class NotificationEvent:
    event_type: str
    timestamp: str
    username: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)


def _now_utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def build_event(
    event_type: str,
    username: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> NotificationEvent:
    return NotificationEvent(
        event_type=event_type,
        timestamp=_now_utc_iso(),
        username=username,
        message=message,
        data=data if data is not None else {},
    )


def notify(
    logger: logging.Logger,
    script_path: str | None,
    event: NotificationEvent,
    timeout_s: float = 10.0,
) -> None:
    if script_path is None:
        return
    payload = json.dumps(asdict(event))
    try:
        result = subprocess.run(
            [script_path],
            input=payload,
            timeout=timeout_s,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning(
                "Notification script %s exited with code %d: %s",
                script_path,
                result.returncode,
                result.stderr,
            )
    except OSError as ex:
        logger.warning("Could not run notification script %s: %s", script_path, ex)
    except subprocess.TimeoutExpired:
        logger.warning(
            "Notification script %s timed out after %.1fs", script_path, timeout_s
        )
