import pathlib

import pytest

from bot.config import BotConfigError, load_config


def test_load_config_parses_secret_files(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_path = tmp_path / "token.txt"
    token_path.write_text("123:abc\n")
    chat_ids_path = tmp_path / "chat_ids.txt"
    chat_ids_path.write_text("488165044, 999\n")

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(token_path))
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS_FILE", str(chat_ids_path))
    monkeypatch.setenv("ICLOUDPD_BASE_URL", "http://icloudpd:8080")

    config = load_config()

    assert config.bot_token == "123:abc"
    assert config.allowed_chat_ids == frozenset({488165044, 999})
    assert config.icloudpd_base_url == "http://icloudpd:8080"
    assert config.notify_listener_port == 8090


def test_load_config_defaults_base_url_and_port(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_path = tmp_path / "token.txt"
    token_path.write_text("123:abc")
    chat_ids_path = tmp_path / "chat_ids.txt"
    chat_ids_path.write_text("488165044")

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(token_path))
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS_FILE", str(chat_ids_path))
    monkeypatch.delenv("ICLOUDPD_BASE_URL", raising=False)
    monkeypatch.delenv("NOTIFY_LISTENER_PORT", raising=False)

    config = load_config()

    assert config.icloudpd_base_url == "http://icloudpd:2011"
    assert config.notify_listener_port == 8090


def test_load_config_requires_bot_token_file(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_ids_path = tmp_path / "chat_ids.txt"
    chat_ids_path.write_text("488165044")

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_FILE", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS_FILE", str(chat_ids_path))

    with pytest.raises(BotConfigError, match="TELEGRAM_BOT_TOKEN_FILE"):
        load_config()


def test_load_config_rejects_raw_bot_token_env_var(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_ids_path = tmp_path / "chat_ids.txt"
    chat_ids_path.write_text("488165044")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS_FILE", str(chat_ids_path))

    with pytest.raises(BotConfigError, match="TELEGRAM_BOT_TOKEN"):
        load_config()


def test_load_config_rejects_raw_chat_ids_env_var(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_path = tmp_path / "token.txt"
    token_path.write_text("123:abc")

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(token_path))
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "488165044")

    with pytest.raises(BotConfigError, match="TELEGRAM_ALLOWED_CHAT_IDS"):
        load_config()


def test_load_config_reports_missing_secret_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", "/nonexistent/token.txt")
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS_FILE", raising=False)

    with pytest.raises(BotConfigError, match="could not be read"):
        load_config()
