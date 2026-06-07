from __future__ import annotations

from typing import Any

_POOL_INJECTED_KEYS: frozenset[str] = frozenset(
    {"loop", "connection_class", "record_class"}
)


def discard_pool_injected_connect_kwargs(kwargs: dict[str, Any]) -> None:
    """Remove pool-managed keys from *kwargs* before calling a non-asyncpg API.

    Mutates *kwargs* in place. Safe to call when the next callee is Cloud SQL
    """
    for key in _POOL_INJECTED_KEYS:
        kwargs.pop(key, None)
