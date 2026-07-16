from bot.messages import (
    code_accepted_success_text,
    code_failed_keyboard,
    code_failed_text,
    code_requested_text,
    connection_lost_text,
    session_expired_text,
    start_2fa_keyboard,
)


def test_session_expired_text_includes_username_and_message() -> None:
    text = session_expired_text("jdoe@icloud.com", "2FA has expired")

    assert "jdoe@icloud.com" in text
    assert "2FA has expired" in text


def test_start_2fa_keyboard_has_one_button() -> None:
    keyboard = start_2fa_keyboard()

    assert keyboard.inline_keyboard[0][0].callback_data == "start_2fa"


def test_code_requested_text_includes_username() -> None:
    assert "jdoe@icloud.com" in code_requested_text("jdoe@icloud.com")


def test_code_accepted_success_text_includes_username() -> None:
    assert "jdoe@icloud.com" in code_accepted_success_text("jdoe@icloud.com")


def test_code_accepted_success_text_handles_unknown_username() -> None:
    text = code_accepted_success_text("")

    assert "✅" in text


def test_connection_lost_text_is_non_empty() -> None:
    assert connection_lost_text()


def test_code_failed_text_includes_error() -> None:
    assert "bad code" in code_failed_text("bad code")


def test_code_failed_keyboard_has_retry_and_exit() -> None:
    keyboard = code_failed_keyboard()
    callback_datas = {button.callback_data for row in keyboard.inline_keyboard for button in row}

    assert callback_datas == {"retry_2fa", "exit_2fa"}
