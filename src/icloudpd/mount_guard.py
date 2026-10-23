"""Refuse to touch a library directory whose network mount has dropped.

When a library lives on a network filesystem and the mount drops, the
directory becomes an empty local folder and downloads would silently fill the
host's own disk. Libraries opt in by carrying a `.mounted` marker file at their
root; this module checks for it before a user's run.

Notifications fire on transitions only (first failure, first recovery) so a
long outage in watch mode does not send an alert every cycle. A transition
counts only once its notification was delivered; a failed send is retried on
the next cycle. The state is in memory, so a process restart during an outage
alerts once more.
"""

from __future__ import annotations

import logging
import os

from icloudpd import notifications

MARKER_FILENAME = ".mounted"

# Usernames whose library is currently known to be missing its marker.
_missing: set[str] = set()


def reset() -> None:
    """Clear in-memory transition state (for tests)."""
    _missing.clear()


def check(
    logger: logging.Logger,
    username: str,
    directory: str,
    notification_script: str | None,
) -> bool:
    """Return True if the marker is present and the run may proceed.

    Read-only: never creates anything under `directory`.
    """
    if os.path.isfile(os.path.join(directory, MARKER_FILENAME)):
        if username in _missing:
            message = f"{username}'s library at {directory} is mounted again; resuming."
            logger.info(message)
            delivered = notifications.notify(
                logger,
                notification_script,
                notifications.build_event(
                    event_type="library_mount_restored",
                    username=username,
                    message=message,
                    data={"directory": directory},
                ),
            )
            # Keep the outage on record until the recovery alert is delivered,
            # so a failed send is retried next cycle.
            if delivered:
                _missing.discard(username)
        return True

    message = (
        f"{username}'s library at {directory} is not mounted "
        f"({MARKER_FILENAME} marker missing); skipping this run."
    )
    logger.error(message)
    if username not in _missing:
        delivered = notifications.notify(
            logger,
            notification_script,
            notifications.build_event(
                event_type="library_mount_missing",
                username=username,
                message=message,
                data={"directory": directory},
            ),
        )
        # Only remember the outage once the alert got out; otherwise retry next cycle.
        if delivered:
            _missing.add(username)
    return False
