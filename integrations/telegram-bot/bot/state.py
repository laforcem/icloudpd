from __future__ import annotations

from threading import Lock


class ChatState:
    """Tracks which chats are currently expected to send a 2FA code next."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._awaiting_code: set[int] = set()

    def start_awaiting_code(self, chat_id: int) -> None:
        with self._lock:
            self._awaiting_code.add(chat_id)

    def stop_awaiting_code(self, chat_id: int) -> None:
        with self._lock:
            self._awaiting_code.discard(chat_id)

    def is_awaiting_code(self, chat_id: int) -> bool:
        with self._lock:
            return chat_id in self._awaiting_code
