#!/usr/bin/env python3
"""Forwards a notify() JSON event on stdin to the Telegram bot's /notify endpoint.

Never raises. Exits non-zero when the bot is unreachable or rejects the event,
so icloudpd can tell the alert was not delivered (notify() just logs a warning
and carries on; see src/icloudpd/notifications.py). Must return quickly -
notify() enforces a ~10s subprocess timeout.
"""

import os
import sys

import requests

NOTIFY_URL = os.environ.get("TELEGRAM_BOT_NOTIFY_URL", "http://icloudpd-telegram-bot:8090/notify")


def main() -> int:
    payload = sys.stdin.read()
    try:
        response = requests.post(
            NOTIFY_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
    except requests.RequestException:
        return 1
    return 0 if response.ok else 1


if __name__ == "__main__":
    sys.exit(main())
