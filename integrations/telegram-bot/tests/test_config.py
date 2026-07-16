import pytest

from bot.config import load_config


def test_load_config_parses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "488165044, 999")
    monkeypatch.setenv("ICLOUDPD_BASE_URL", "http://icloudpd:8080")

    config = load_config()

    assert config.bot_token == "123:abc"
    assert config.allowed_chat_ids == frozenset({488165044, 999})
    assert config.icloudpd_base_url == "http://icloudpd:8080"
    assert config.notify_listener_port == 8090


def test_load_config_defaults_base_url_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "488165044")
    monkeypatch.delenv("ICLOUDPD_BASE_URL", raising=False)
    monkeypatch.delenv("NOTIFY_LISTENER_PORT", raising=False)

    config = load_config()

    assert config.icloudpd_base_url == "http://icloudpd:8080"
    assert config.notify_listener_port == 8090


def test_load_config_requires_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "488165044")

    with pytest.raises(KeyError):
        load_config()
