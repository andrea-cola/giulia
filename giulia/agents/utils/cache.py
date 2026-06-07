from __future__ import annotations

import time
from threading import Lock
from typing import Any


class TTLCache:
    """
    In-memory TTL cache for AgentAddr records.
    Falls back to stale entries if the index is unreachable (resilience).
    """

    def __init__(self):
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = Lock()

    def get(self, key: str, allow_stale: bool = False) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() < expires_at:
                return value
            if allow_stale:
                return value
            # Don't delete -- stale entries are kept for allow_stale fallback.
            # Use cleanup() to purge expired entries explicitly.
            return None

    def set(self, key: str, value: Any, ttl: int) -> None:
        with self._lock:
            self._store[key] = (value, time.monotonic() + ttl)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def cleanup(self) -> int:
        """Remove all expired entries. Returns count of removed entries."""
        now = time.monotonic()
        removed = 0
        with self._lock:
            expired_keys = [k for k, (_, exp) in self._store.items() if now >= exp]
            for k in expired_keys:
                del self._store[k]
                removed += 1
        return removed


_agent_cache = TTLCache()


def get_agent_cache() -> TTLCache:
    return _agent_cache
