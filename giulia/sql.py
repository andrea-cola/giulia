"""Cloud SQL client for private-IP connections via the Cloud SQL Python Connector.

Provides ``GiuliaDbClient`` — an async context manager that maintains a pool of
IAM-authenticated connections to the Thanos Cloud SQL instance. Both sync
(SQLAlchemy / SQLModel) and async (asyncpg) interfaces are available so the
class can be used from FastAPI route handlers, background tasks, or agents.

Usage — async (asyncpg, preferred for agents and async FastAPI routes):

    async with GiuliaDbClient() as db:
        rows = await db.fetch("SELECT id, name FROM items WHERE active = $1", True)
        row  = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
        await db.execute("UPDATE items SET name = $1 WHERE id = $2", name, item_id)

Usage — as a long-lived singleton (e.g. FastAPI lifespan):

    client = GiuliaDbClient()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await client.open()
        yield
        await client.close()

    @app.get("/items")
    async def list_items():
        return await client.fetch("SELECT * FROM items")

Usage — sync (SQLAlchemy / SQLModel sessions, for existing sync FastAPI apps):

    with GiuliaDbClient.sync_session() as session:
        items = session.exec(select(Item)).all()

Environment variables (all optional — sensible defaults):

    DB_INSTANCE   Cloud SQL instance connection name
    DB_NAME       Database name.  Default: brain
    DB_USER       IAM database user — MUST match the Google principal issuing IAM
                  tokens for Cloud SQL (e.g. the Workload Identity GCP SA).
    DB_IP_TYPE    "private" (default, in-cluster) or "public"
    DB_MIN_POOL   Minimum async pool size.  Default: 1
    DB_MAX_POOL   Maximum async pool size.  Default: 5

Google ADK — persistent sessions on the same Cloud SQL instance:

    from giulia.sql import create_cloud_sql_adk_session_service
    from google.adk.runners import Runner

    session_service = create_cloud_sql_adk_session_service()
    runner = Runner(..., session_service=session_service)
    # On shutdown: await session_service.close()
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from google.cloud.sql.connector import Connector

from giulia.asyncpg_pool_connect import discard_pool_injected_connect_kwargs
from giulia.config import db_config as _db_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration (read once at import time, mirrors gateway/api_keys.py)
# ---------------------------------------------------------------------------

_INSTANCE = _db_config.db_instance
_DB_NAME = _db_config.db_name
# Fallback IAM username only when DB_USER is unset (local).
_DB_USER = _db_config.db_user
_DB_DRIVER = os.environ.get("DB_DRIVER", "asyncpg")
_MIN_POOL = _db_config.db_min_pool
_MAX_POOL = _db_config.db_max_pool


# def _connect_timeout_s() -> int:
#     """Cloud SQL connector / asyncpg connect timeout (seconds)."""
#     try:
#         return max(10, int(os.environ.get("DB_CONNECT_TIMEOUT", "120")))
#     except ValueError:
#         return 120


def _ip_type():
    """Return the correct IPTypes value based on DB_IP_TYPE env var."""
    from google.cloud.sql.connector import IPTypes

    return (
        IPTypes.PRIVATE
        if _db_config.db_ip_type.lower() == "private"
        else IPTypes.PUBLIC
    )


# ---------------------------------------------------------------------------
# Shared instance for easy access
# ---------------------------------------------------------------------------

_shared_client: GiuliaDbClient | None = None


def get_thanos_client() -> GiuliaDbClient:
    """Return a shared GiuliaDbClient instance (Cloud SQL / GCP).

    .. deprecated::
        Prefer ``get_db_client()`` which honours the active
        ``DatabaseConnector`` provider set via ``giulia.configure(database=...)``.
        This function always returns a ``GiuliaDbClient`` regardless of the
        configured provider and is kept for backward compatibility.
    """
    global _shared_client
    if _shared_client is None:
        _shared_client = GiuliaDbClient()
    return _shared_client


def get_db_client():
    """Return the active database client as configured by the provider registry.

    When no provider has been set via ``giulia.configure(database=...)``, this
    falls back to the default ``CloudSqlConnector`` (backed by ``GiuliaDbClient``).

    Returns an object satisfying the ``DatabaseConnector`` protocol.
    """
    from giulia.providers.registry import get_database

    return get_database()


class GiuliaDbClient:
    """Async connection pool to the Thanos Cloud SQL instance.

    Lifecycle
    ---------
    Use as an async context manager for one-off use::

        async with GiuliaDbClient() as db:
            rows = await db.fetch("SELECT 1")

    Or manage the lifecycle manually for long-lived singletons::

        client = GiuliaDbClient()
        await client.open()
        ...
        await client.close()

    Sync access
    -----------
    For synchronous code (e.g. SQLModel / FastAPI sync routes) use the class
    method ``sync_session()`` which yields a SQLAlchemy / SQLModel Session::

        with GiuliaDbClient.sync_session() as session:
            results = session.exec(select(Item)).all()
    """

    def __init__(
        self,
        instance: str = _INSTANCE,
        db: str = _DB_NAME,
        user: str = _DB_USER,
        min_pool: int = _MIN_POOL,
        max_pool: int = _MAX_POOL,
    ) -> None:
        self._instance = instance
        self._db = db
        self._user = user
        self._min_pool = min_pool
        self._max_pool = max_pool

        self._connector: Any = None
        self._pool: Any = None

    # ------------------------------------------------------------------
    # Pool lifecycle
    # ------------------------------------------------------------------

    async def open(self) -> None:
        """Open the connection pool. Idempotent."""
        if self._pool is not None:
            return

        import asyncpg

        self._connector = Connector(loop=asyncio.get_running_loop())
        ip_type = _ip_type()

        async def _getconn_connector(
            *_args: Any,
            **kwargs: Any,
        ) -> asyncpg.Connection:
            discard_pool_injected_connect_kwargs(kwargs)
            if kwargs:
                logger.warning(
                    "GiuliaDbClient: ignoring unexpected asyncpg pool connect kwargs: %s",
                    sorted(kwargs),
                )
            return await self._connector.connect_async(
                self._instance,
                "asyncpg",
                user=self._user,
                db=self._db,
                enable_iam_auth=True,
                ip_type=ip_type,
                # timeout=_connect_timeout_s(),
            )

        self._pool = await asyncpg.create_pool(
            min_size=self._min_pool,
            max_size=self._max_pool,
            connection_class=asyncpg.Connection,
            connect=_getconn_connector,
        )
        logger.info(
            "GiuliaDbClient pool ready (instance=%s db=%s ip_type=%s pool=%d-%d)",
            self._instance,
            self._db,
            ip_type,
            self._min_pool,
            self._max_pool,
        )

    async def close(self) -> None:
        """Drain the pool and close the connector. Idempotent."""
        if self._pool:
            await self._pool.close()
            self._pool = None
        if self._connector:
            await self._connector.close_async()
            self._connector = None
        logger.info("GiuliaDbClient pool closed")

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> GiuliaDbClient:
        await self.open()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Query helpers (async / asyncpg)
    # ------------------------------------------------------------------

    def _assert_open(self) -> None:
        if self._pool is None:
            raise RuntimeError(
                "GiuliaDbClient is not open. "
                "Use 'async with GiuliaDbClient() as db:' or call await db.open() first."
            )

    async def fetch(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> list[dict[str, Any]]:
        """Execute *query* and return all rows as a list of dicts.

        Example::

            rows = await db.fetch(
                "SELECT id, name FROM items WHERE active = $1", True
            )
        """
        self._assert_open()
        async with self._pool.acquire() as conn:
            records = await conn.fetch(query, *args, timeout=timeout)
        return [dict(r) for r in records]

    async def fetchrow(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> dict[str, Any] | None:
        """Execute *query* and return the first row as a dict, or ``None``.

        Example::

            item = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
        """
        self._assert_open()
        async with self._pool.acquire() as conn:
            record = await conn.fetchrow(query, *args, timeout=timeout)
        return dict(record) if record else None

    async def fetchval(
        self, query: str, *args: Any, column: int = 0, timeout: float | None = None
    ) -> Any:
        """Execute *query* and return a single scalar value.

        Example::

            count = await db.fetchval("SELECT COUNT(*) FROM items WHERE active = $1", True)
        """
        self._assert_open()
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *args, column=column, timeout=timeout)

    async def execute(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> str:
        """Execute a DML statement (INSERT / UPDATE / DELETE).

        Returns the command tag string (e.g. ``"UPDATE 3"``).

        Example::

            tag = await db.execute(
                "UPDATE items SET name = $1 WHERE id = $2", new_name, item_id
            )
        """
        self._assert_open()
        async with self._pool.acquire() as conn:
            return await conn.execute(query, *args, timeout=timeout)

    async def executemany(
        self, query: str, args: list[tuple[Any, ...]], timeout: float | None = None
    ) -> None:
        """Execute a parameterised statement for each set of arguments in *args*.

        Useful for bulk inserts / updates.

        Example::

            await db.executemany(
                "INSERT INTO items (name, active) VALUES ($1, $2)",
                [("alpha", True), ("beta", False)],
            )
        """
        self._assert_open()
        async with self._pool.acquire() as conn:
            await conn.executemany(query, args, timeout=timeout)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        """Async context manager that wraps statements in a transaction.

        Commits on exit; rolls back on exception.

        Example::

            async with db.transaction():
                await db.execute("INSERT INTO audit (msg) VALUES ($1)", "start")
                await db.execute("UPDATE items SET active = $1 WHERE id = $2", False, 1)
        """
        self._assert_open()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Temporarily bind pool operations to this connection so that
                # calls to fetch/execute within the block use the same tx.
                saved = self._pool
                self._pool = _SingleConnectionPool(conn)  # type: ignore[assignment]
                try:
                    yield conn
                finally:
                    self._pool = saved

    # ------------------------------------------------------------------
    # Sync interface (SQLAlchemy / SQLModel)
    # ------------------------------------------------------------------

    @classmethod
    @contextmanager
    def sync_session(
        cls,
        instance: str = _INSTANCE,
        db: str = _DB_NAME,
        user: str = _DB_USER,
    ) -> Iterator[Any]:
        """Yield a synchronous SQLAlchemy / SQLModel Session.

        Uses pg8000 as the sync driver (no asyncpg dependency needed).

        Example::

            from sqlmodel import select
            from myapp.models import Item

            with GiuliaDbClient.sync_session() as session:
                items = session.exec(select(Item).where(Item.active == True)).all()
        """
        from google.cloud.sql.connector import Connector  # noqa: F811
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        ip_type = _ip_type()
        connector = Connector()

        _ip = ip_type  # capture for closure

        def _getconn():
            return connector.connect(
                instance,
                "pg8000",
                user=user,
                db=db,
                enable_iam_auth=True,
                ip_type=_ip,
            )

        engine = create_engine(
            "postgresql+pg8000://", creator=_getconn, pool_pre_ping=True
        )

        try:
            # Support both plain SQLAlchemy Session and SQLModel Session
            try:
                from sqlmodel import Session  # type: ignore[assignment]
            except ImportError:
                from sqlalchemy.orm import Session  # type: ignore[assignment]

            SessionLocal = sessionmaker(
                bind=engine,
                class_=Session,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
            )
            session = SessionLocal()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        finally:
            engine.dispose()
            if connector is not None:
                connector.close()

    # ------------------------------------------------------------------
    # FastAPI dependency helpers
    # ------------------------------------------------------------------

    def as_dependency(self):
        """Return an async FastAPI dependency that yields this client.

        Attach a single shared ``GiuliaDbClient`` instance to the app lifespan,
        then inject it into route handlers::

            db = GiuliaDbClient()

            @asynccontextmanager
            async def lifespan(app: FastAPI):
                await db.open()
                yield
                await db.close()

            app = FastAPI(lifespan=lifespan)

            @app.get("/items")
            async def list_items(client: GiuliaDbClient = Depends(db.as_dependency())):
                return await client.fetch("SELECT * FROM items")
        """

        async def _dep():
            self._assert_open()
            yield self

        return _dep


# ---------------------------------------------------------------------------
# Google ADK: Cloud SQL–backed DatabaseSessionService
# ---------------------------------------------------------------------------


def create_cloud_sql_adk_session_service(
    *,
    instance: str = _INSTANCE,
    db: str = _DB_NAME,
    user: str = _DB_USER,
    **engine_kwargs: Any,
) -> Any:
    """Build an ADK ``DatabaseSessionService`` backed by Cloud SQL."""
    from google.adk.sessions.database_session_service import DatabaseSessionService

    ip_type = _ip_type()
    _connector_lock = asyncio.Lock()
    _connector_holder: dict[str, Any] = {"connector": None}
    _connect_log_once_conn: dict[str, bool] = {"done": False}

    async def _async_creator() -> Any:
        if not _connect_log_once_conn["done"]:
            _connect_log_once_conn["done"] = True
            it = getattr(ip_type, "name", str(ip_type))
            logger.info(
                "Cloud SQL (ADK session): instance=%s ip_type=%s",
                instance,
                it,
            )
        if _connector_holder["connector"] is None:
            async with _connector_lock:
                if _connector_holder["connector"] is None:
                    _connector_holder["connector"] = Connector(
                        loop=asyncio.get_running_loop(),
                    )
        connector = _connector_holder["connector"]
        return await connector.connect_async(
            instance,
            "asyncpg",
            user=user,
            db=db,
            enable_iam_auth=True,
            ip_type=ip_type,
        )

    class _CloudSqlDatabaseSessionService(DatabaseSessionService):
        async def close(self) -> None:
            await super().close()
            connector = _connector_holder["connector"]
            if connector is not None:
                await connector.close_async()
                _connector_holder["connector"] = None

    return _CloudSqlDatabaseSessionService(
        "postgresql+asyncpg://",
        async_creator=_async_creator,
        pool_pre_ping=True,
        **engine_kwargs,
    )


# ---------------------------------------------------------------------------
# Internal helper: wrap a single connection to look like a pool
# (used inside transaction() to ensure all calls share the same connection)
# ---------------------------------------------------------------------------


class _SingleConnectionPool:
    """Minimal pool-like object backed by a single asyncpg connection."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def acquire(self):
        return _BorrowedConnection(self._conn)

    async def close(self) -> None:
        pass


class _BorrowedConnection:
    def __init__(self, conn) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_: Any) -> None:
        pass
