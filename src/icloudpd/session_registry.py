"""Process-wide registry of live iCloud sessions, one slot per account.

Scans publish the service they authenticated; the control channel reads it. Every
HTTP request a published service makes holds the account's RLock, so a control
request waits for at most one in-flight scan request, never a whole scan. A login holds
the lock throughout, 2FA wait included, so control-side callers acquire it with a
timeout (`lock_timeout`) and give up rather than tie up a worker thread.
"""

import threading
from typing import Dict

from pyicloud_ipd.base import PyiCloudService
from pyicloud_ipd.exceptions import PyiCloud2SARequiredException

REFRESH_INTERVAL_SECONDS = 600.0
LOCK_TIMEOUT_SECONDS = 5.0


class SessionRegistry:
    def __init__(self) -> None:
        self.lock_timeout = LOCK_TIMEOUT_SECONDS
        self._guard = threading.Lock()
        self._locks: Dict[str, threading.RLock] = {}
        self._services: Dict[str, PyiCloudService] = {}
        self._last_refresh: Dict[str, float] = {}

    def lock(self, username: str) -> threading.RLock:
        """The account's lock; created on first use, the same object forever."""
        with self._guard:
            lock = self._locks.get(username)
            if lock is None:
                lock = threading.RLock()
                self._locks[username] = lock
            return lock

    def publish(self, username: str, service: PyiCloudService | None) -> None:
        """Store `service` in the account's slot, or clear the slot when None."""
        lock = self.lock(username)
        with lock:
            if service is None:
                with self._guard:
                    self._services.pop(username, None)
                return
            service.request_lock = lock
            with self._guard:
                self._services[username] = service

    def get(self, username: str) -> PyiCloudService | None:
        with self._guard:
            return self._services.get(username)

    def refresh(self, username: str, now: float) -> PyiCloudService | None:
        """Token-only revalidation of the slot's session; never prompts for a password or 2FA.

        Returns None without calling Apple when the slot is empty, the last attempt for
        this account was less than REFRESH_INTERVAL_SECONDS before `now`, or the account's
        lock stays held elsewhere (a login, perhaps waiting for 2FA) for `lock_timeout`.
        """
        lock = self.lock(username)
        if not lock.acquire(timeout=self.lock_timeout):
            return None
        try:
            service = self.get(username)
            if service is None:
                return None
            with self._guard:
                last = self._last_refresh.get(username)
                if last is not None and now - last < REFRESH_INTERVAL_SECONDS:
                    return None
                self._last_refresh[username] = now
            try:
                revalidated = service.revalidate_token()
            except PyiCloud2SARequiredException:
                revalidated = False  # needs interactive auth: give up, leave the slot empty
            if revalidated:
                return service
            self.publish(username, None)
            return None
        finally:
            lock.release()
