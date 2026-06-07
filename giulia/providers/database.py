"""Database connector protocol and built-in implementations.

Providers
---------
- ``CloudSqlConnector`` — GCP Cloud SQL via IAM auth (default, wraps GiuliaDbClient)
- ``PostgresConnector`` — plain asyncpg DSN, no GCP dependency
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DatabaseConnector(Protocol):
    """Structural protocol for an async PostgreSQL connection pool.

    Matches the public interface of ``GiuliaDbClient`` so existing callers
    need no changes.
    """

    async def open(self) -> None:
        """Open the connection pool. Must be idempotent."""
        ...

    async def close(self) -> None:
        """Drain the pool and release resources. Must be idempotent."""
        ...

    async def fetch(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> list[dict[str, Any]]:
        """Execute *query* and return all rows as a list of dicts."""
        ...

    async def fetchrow(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> dict[str, Any] | None:
        """Execute *query* and return the first row as a dict, or ``None``."""
        ...

    async def fetchval(
        self, query: str, *args: Any, column: int = 0, timeout: float | None = None
    ) -> Any:
        """Execute *query* and return a single scalar value."""
        ...

    async def execute(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> str:
        """Execute a DML statement and return the command tag."""
        ...

    async def executemany(
        self, query: str, args: list[tuple[Any, ...]], timeout: float | None = None
    ) -> None:
        """Execute a parameterised statement for each set of arguments."""
        ...


class CloudSqlConnector:
    """Async connection pool backed by Google Cloud SQL + IAM auth.

    This is a thin facade over ``giulia.sql.GiuliaDbClient`` and is the
    default database provider.  Requires ``cloud-sql-python-connector``
    and ``asyncpg``.

    All constructor arguments mirror ``GiuliaDbClient``; when omitted they
    fall back to the environment variables / ``DatabaseConfig`` defaults.
    """

    def __init__(
        self,
        instance: str | None = None,
        db: str | None = None,
        user: str | None = None,
        min_pool: int | None = None,
        max_pool: int | None = None,
    ) -> None:
        from giulia.config import db_config
        from giulia.sql import GiuliaDbClient

        self._client = GiuliaDbClient(
            instance=instance or db_config.db_instance,
            db=db or db_config.db_name,
            user=user or db_config.db_user,
            min_pool=min_pool if min_pool is not None else db_config.db_min_pool,
            max_pool=max_pool if max_pool is not None else db_config.db_max_pool,
        )

    async def open(self) -> None:
        await self._client.open()

    async def close(self) -> None:
        await self._client.close()

    async def fetch(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> list[dict[str, Any]]:
        return await self._client.fetch(query, *args, timeout=timeout)

    async def fetchrow(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> dict[str, Any] | None:
        return await self._client.fetchrow(query, *args, timeout=timeout)

    async def fetchval(
        self, query: str, *args: Any, column: int = 0, timeout: float | None = None
    ) -> Any:
        return await self._client.fetchval(query, *args, column=column, timeout=timeout)

    async def execute(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> str:
        return await self._client.execute(query, *args, timeout=timeout)

    async def executemany(
        self, query: str, args: list[tuple[Any, ...]], timeout: float | None = None
    ) -> None:
        await self._client.executemany(query, args, timeout=timeout)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        async with self._client.transaction() as conn:
            yield conn

    # Expose the underlying GiuliaDbClient for code that needs ADK session service.
    @property
    def thanos_client(self):
        return self._client


class PostgresConnector:
    """Async connection pool using plain asyncpg — no GCP dependency.

    Suitable for any standard PostgreSQL instance (local, AWS RDS,
    Azure Database for PostgreSQL, self-hosted, etc.).

    Requires ``asyncpg``::

        pip install asyncpg

    Example::

        db = PostgresConnector(dsn="postgresql://user:pw@localhost:5432/mydb")
        # or via keyword args:
        db = PostgresConnector(host="localhost", port=5432, user="u", password="p", database="db")
    """

    def __init__(
        self,
        dsn: str | None = None,
        *,
        host: str | None = None,
        port: int = 5432,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        min_size: int = 1,
        max_size: int = 5,
    ) -> None:
        self._dsn = dsn
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._database = database
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Any = None

    async def open(self) -> None:
        if self._pool is not None:
            return
        try:
            import asyncpg
        except ImportError as exc:
            raise ImportError(
                "asyncpg is required for PostgresConnector. "
                "Install it with: pip install asyncpg"
            ) from exc

        kwargs: dict[str, Any] = dict(min_size=self._min_size, max_size=self._max_size)
        if self._dsn:
            kwargs["dsn"] = self._dsn
        else:
            if self._host:
                kwargs["host"] = self._host
            if self._port:
                kwargs["port"] = self._port
            if self._user:
                kwargs["user"] = self._user
            if self._password:
                kwargs["password"] = self._password
            if self._database:
                kwargs["database"] = self._database

        self._pool = await asyncpg.create_pool(**kwargs)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _assert_open(self) -> None:
        if self._pool is None:
            raise RuntimeError(
                "PostgresConnector is not open. Call await connector.open() first."
            )

    async def fetch(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> list[dict[str, Any]]:
        self._assert_open()
        async with self._pool.acquire() as conn:
            records = await conn.fetch(query, *args, timeout=timeout)
        return [dict(r) for r in records]

    async def fetchrow(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> dict[str, Any] | None:
        self._assert_open()
        async with self._pool.acquire() as conn:
            record = await conn.fetchrow(query, *args, timeout=timeout)
        return dict(record) if record else None

    async def fetchval(
        self, query: str, *args: Any, column: int = 0, timeout: float | None = None
    ) -> Any:
        self._assert_open()
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *args, column=column, timeout=timeout)

    async def execute(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> str:
        self._assert_open()
        async with self._pool.acquire() as conn:
            return await conn.execute(query, *args, timeout=timeout)

    async def executemany(
        self, query: str, args: list[tuple[Any, ...]], timeout: float | None = None
    ) -> None:
        self._assert_open()
        async with self._pool.acquire() as conn:
            await conn.executemany(query, args, timeout=timeout)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        self._assert_open()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                yield conn
