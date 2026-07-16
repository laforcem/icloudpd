#!/usr/bin/env python3
"""Forwards a notify() JSON event on stdin to the Telegram bot's /notify endpoint.

Best-effort: any failure here is swallowed so it never affects icloudpd's own
best-effort notify() semantics (see src/icloudpd/notifications.py). Must return
quickly - notify() enforces a ~10s subprocess timeout.
"""

import os
import sys

import requests

NOTIFY_URL = os.environ.get("TELEGRAM_BOT_NOTIFY_URL", "http://telegram-bot:8090/notify")


def main() -> int:
    payload = sys.stdin.read()
    try:
        requests.post(
            NOTIFY_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
    except requests.RequestException:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
