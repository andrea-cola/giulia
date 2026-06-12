"""Redis authentication provider protocol and built-in implementations.

Providers
---------
- ``GcpIamRedisAuthProvider``  — GCP IAM tokens for Memorystore (default)
- ``NoAuthRedisProvider``      — no authentication (local Redis, open clusters)
- ``PasswordRedisAuthProvider``— static username/password (requirepass, ElastiCache)
"""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable


@runtime_checkable
class RedisAuthProvider(Protocol):
    """Structural protocol for supplying Redis credentials.

    ``get_credentials()`` is called before the initial connection.
    ``refresh_token()`` is called by the worker when an
    ``AuthenticationError`` is caught mid-run, allowing short-lived tokens
    (e.g. IAM access tokens) to be refreshed transparently.
    """

    def get_credentials(self) -> tuple[str, str] | None:
        """Return *(username, password)* or ``None`` for unauthenticated connections."""
        ...

    async def refresh_token(self) -> tuple[str, str]:
        """Return a fresh *(username, password)* after an authentication failure.

        For static credentials this may simply return the same values.
        Raises ``RuntimeError`` if credentials cannot be refreshed.
        """
        ...


class GcpIamRedisAuthProvider:
    """Authenticate to GCP Memorystore using ADC IAM access tokens.

    Requires ``google-auth``; the credentials are fetched via
    ``google.auth.default()`` and refreshed automatically when the token
    expires.

    *username* defaults to ``"default"``, which is the Memorystore
    IAM auth requirement.
    """

    def __init__(self, username: str = "default") -> None:
        self._username = username
        self._credentials: object = None

    def _get_token(self) -> str:
        import google.auth  # type: ignore[import-untyped]
        import google.auth.transport.requests  # type: ignore[import-untyped]

        if self._credentials is None:
            self._credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        request = google.auth.transport.requests.Request()
        self._credentials.refresh(request)  # type: ignore[union-attr]
        token: str = self._credentials.token  # type: ignore[union-attr]
        if not token:
            raise RuntimeError(
                "GCP IAM access token for Memorystore is empty after refresh"
            )
        return token

    def get_credentials(self) -> tuple[str, str]:
        return self._username, self._get_token()

    async def refresh_token(self) -> tuple[str, str]:
        token = await asyncio.to_thread(self._get_token)
        return self._username, token


class NoAuthRedisProvider:
    """No-op provider for Redis instances that do not require authentication.

    Suitable for local development, open Redis clusters, or any setup that
    does not use ``requirepass`` or IAM auth.
    """

    def get_credentials(self) -> None:
        return None

    async def refresh_token(self) -> tuple[str, str]:
        return "", ""


class PasswordRedisAuthProvider:
    """Static username/password credentials for Redis.

    Suitable for ``requirepass``-enabled Redis, AWS ElastiCache with auth
    tokens, or any password-protected Redis instance.

    Example::

        provider = PasswordRedisAuthProvider(password="my-secret")
        provider = PasswordRedisAuthProvider(username="alice", password="my-secret")
    """

    def __init__(self, password: str, username: str = "default") -> None:
        self._username = username
        self._password = password

    def get_credentials(self) -> tuple[str, str]:
        return self._username, self._password

    async def refresh_token(self) -> tuple[str, str]:
        return self._username, self._password
