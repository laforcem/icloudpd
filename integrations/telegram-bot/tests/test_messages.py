from bot.messages import (
    code_accepted_success_text,
    code_failed_keyboard,
    code_failed_text,
    code_requested_text,
    connection_lost_text,
    force_reauth_keyboard,
    force_reauth_not_found_text,
    force_reauth_requested_text,
    manual_password_entry_text,
    session_expired_text,
    session_expiring_soon_text,
    start_2fa_keyboard,
    webui_link_keyboard,
)


def test_session_expiring_soon_text_includes_username_and_message() -> None:
    text = session_expiring_soon_text("jdoe@icloud.com", "session expires in 3.0 day(s)")

    assert "jdoe@icloud.com" in text
    assert "3.0 day(s)" in text


def test_force_reauth_keyboard_embeds_username_in_callback_data() -> None:
    keyboard = force_reauth_keyboard("jdoe@icloud.com")

    assert keyboard.inline_keyboard[0][0].callback_data == "force_reauth:jdoe@icloud.com"


def test_force_reauth_requested_text_includes_username() -> None:
    assert "jdoe@icloud.com" in force_reauth_requested_text("jdoe@icloud.com")


def test_force_reauth_not_found_text_is_non_empty() -> None:
    assert force_reauth_not_found_text()


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


def test_manual_password_entry_text_includes_username_and_message() -> None:
    text = manual_password_entry_text("jdoe@icloud.com", "session expires in 3.0 day(s)")

    assert "jdoe@icloud.com" in text
    assert "3.0 day(s)" in text
    assert "Re-enter your password in the web app" in text


def test_webui_link_keyboard_embeds_url() -> None:
    keyboard = webui_link_keyboard("http://vm101.lan:2011")

    assert keyboard.inline_keyboard[0][0].text == "Open WebUI"
    assert keyboard.inline_keyboard[0][0].url == "http://vm101.lan:2011"
