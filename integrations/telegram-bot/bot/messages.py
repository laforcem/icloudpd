from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def session_expired_text(username: str, message: str) -> str:
    return f"\U0001F510 {username}: {message}"


def start_2fa_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Start 2FA", callback_data="start_2fa")]]
    )


def code_requested_text(username: str) -> str:
    return f"Code requested for {username}. Paste the 6-digit code you received."


def push_not_pending_text() -> str:
    return "Nothing is waiting on a 2FA code right now."


def code_accepted_success_text(username: str) -> str:
    return f"✅ Authenticated for {username}."


def code_failed_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Try again", callback_data="retry_2fa"),
                InlineKeyboardButton(text="Exit", callback_data="exit_2fa"),
            ]
        ]
    )


def code_failed_text(error: str) -> str:
    return f"❌ {error}"


def exited_text() -> str:
    return "Okay. Tap Start 2FA again whenever you're ready."
