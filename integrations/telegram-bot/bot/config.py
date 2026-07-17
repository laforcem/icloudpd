from __future__ import annotations

import os
from dataclasses import dataclass


class BotConfigError(ValueError):
    """Raised for a misconfigured environment (fails loudly at startup)."""


@dataclass(frozen=True)
class BotConfig:
    bot_token: str
    allowed_chat_ids: frozenset[int]
    icloudpd_base_url: str
    notify_listener_port: int = 8090
    # Browser-reachable WebUI URL (e.g. http://vm101.lan:2011), distinct from
    # icloudpd_base_url which is the container-internal address this bot
    # talks to over the Docker network. Not auto-detected -- a container has
    # no reliable way to know its own LAN-facing address (NAT, port mapping,
    # which interface). Optional: only used to add a deep-link button when a
    # session refresh needs a human at the password prompt; omitted entirely
    # if unset.
    webui_external_url: str | None = None


def _read_secret_file(file_env_var: str, raw_env_var: str) -> str:
    if raw_env_var in os.environ:
        raise BotConfigError(
            f"{raw_env_var} is not supported — secrets are never passed as raw "
            f"environment variables. Set {file_env_var} to a path containing the "
            "value instead."
        )
    path = os.environ.get(file_env_var)
    if not path:
        raise BotConfigError(f"{file_env_var} is required (path to a file containing the value).")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError as e:
        raise BotConfigError(f"{file_env_var} {path!r} could not be read: {e}") from e


def load_config() -> BotConfig:
    bot_token = _read_secret_file("TELEGRAM_BOT_TOKEN_FILE", "TELEGRAM_BOT_TOKEN")
    raw_chat_ids = _read_secret_file(
        "TELEGRAM_ALLOWED_CHAT_IDS_FILE", "TELEGRAM_ALLOWED_CHAT_IDS"
    )
    allowed_chat_ids = frozenset(
        int(chat_id.strip()) for chat_id in raw_chat_ids.split(",") if chat_id.strip()
    )
    icloudpd_base_url = os.environ.get("ICLOUDPD_BASE_URL", "http://icloudpd:2011")
    notify_listener_port = int(os.environ.get("NOTIFY_LISTENER_PORT", "8090"))
    webui_external_url = os.environ.get("ICLOUDPD_WEBUI_EXTERNAL_URL") or None
    return BotConfig(
        bot_token=bot_token,
        allowed_chat_ids=allowed_chat_ids,
        icloudpd_base_url=icloudpd_base_url,
        notify_listener_port=notify_listener_port,
        webui_external_url=webui_external_url,
    )
