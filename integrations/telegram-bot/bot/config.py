from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BotConfig:
    bot_token: str
    allowed_chat_ids: frozenset[int]
    icloudpd_base_url: str
    notify_listener_port: int = 8090


def load_config() -> BotConfig:
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    raw_chat_ids = os.environ["TELEGRAM_ALLOWED_CHAT_IDS"]
    allowed_chat_ids = frozenset(
        int(chat_id.strip()) for chat_id in raw_chat_ids.split(",") if chat_id.strip()
    )
    icloudpd_base_url = os.environ.get("ICLOUDPD_BASE_URL", "http://icloudpd:2011")
    notify_listener_port = int(os.environ.get("NOTIFY_LISTENER_PORT", "8090"))
    return BotConfig(
        bot_token=bot_token,
        allowed_chat_ids=allowed_chat_ids,
        icloudpd_base_url=icloudpd_base_url,
        notify_listener_port=notify_listener_port,
    )
