from __future__ import annotations

import asyncio


class MfaResultWaiter:
    """Bridges the server-pushed 'mfa_result' notify event to whichever
    handle_message call is currently waiting on it.

    icloudpd runs one account's MFA flow at a time (a single global
    StatusExchange), so a single pending slot is enough - there's no
    concurrent-flow case to disambiguate with correlation IDs.
    """

    def __init__(self) -> None:
        self._pending: asyncio.Future[tuple[bool, str | None, str | None]] | None = None

    def start(self) -> asyncio.Future[tuple[bool, str | None, str | None]]:
        future: asyncio.Future[tuple[bool, str | None, str | None]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending = future
        return future

    def resolve(self, success: bool, error: str | None, username: str | None) -> None:
        pending = self._pending
        if pending is not None and not pending.done():
            pending.set_result((success, error, username))
