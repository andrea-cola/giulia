"""
API key management backed by a Cloud SQL PostgreSQL database.

Connects via the Cloud SQL Python Connector using IAM authentication.

For **local** development, use Cloud SQL Auth Proxy and set ``CLOUD_SQL_PROXY_HOST``.
Do **not** set that variable in production.

Required environment variables:
    DB_INSTANCE – Cloud SQL instance connection name (project:region:instance).
    DB_USER     – IAM database user (e.g. my-sa@my-project.iam).

Optional environment variables:
    DB_IP_TYPE  – ``private`` (default) or ``public``.
    DB_NAME     – Database name. Default: brain
    CLOUD_SQL_PROXY_HOST – Set for local Auth Proxy (e.g. 127.0.0.1).
    CLOUD_SQL_PROXY_PORT – Listen port. Default: 5432
    CLOUD_SQL_PROXY_PASSWORD – Optional; empty with proxy --auto-iam-authn
    CLOUD_SQL_PROXY_SSL – "true" to use TLS to the proxy (rare on localhost).
"""

import os
import time
from typing import Any

import asyncpg
from google.cloud.sql.connector import Connector, IPTypes

from giulia_gateway.logging_config import get_logger

logger = get_logger("api_keys")

# ── Configuration ─────────────────────────────────────────────────────────────


def _require_env(name: str) -> str:
    """Return the value of a required environment variable, or raise."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Required environment variable {name} is not set. "
            f"See giulia_gateway README for configuration."
        )
    return value


_POOL_INJECTED_KEYS: frozenset[str] = frozenset(
    {"loop", "connection_class", "record_class"}
)


def _discard_pool_injected_connect_kwargs(kwargs: dict[str, Any]) -> None:
    """Remove pool-managed keys from *kwargs* before calling a non-asyncpg API."""
    for key in _POOL_INJECTED_KEYS:
        kwargs.pop(key, None)


_DB_NAME = os.environ.get("DB_NAME", "brain")
_IP_TYPE = (
    IPTypes.PRIVATE
    if os.environ.get("DB_IP_TYPE", "private").lower() == "private"
    else IPTypes.PUBLIC
)


def _cloud_sql_proxy_tcp_endpoint() -> tuple[str, int] | None:
    """Return (host, port) when CLOUD_SQL_PROXY_HOST is set; else None."""
    host = os.environ.get("CLOUD_SQL_PROXY_HOST", "").strip()
    if not host:
        return None
    try:
        port = int(os.environ.get("CLOUD_SQL_PROXY_PORT", "5432"))
    except ValueError:
        port = 5432
    return host, port


def _proxy_connect_args() -> tuple[str, int, str, bool] | None:
    """(host, port, password, ssl) when CLOUD_SQL_PROXY_HOST is set; else None."""
    ep = _cloud_sql_proxy_tcp_endpoint()
    if ep is None:
        return None
    host, port = ep
    password = os.environ.get("CLOUD_SQL_PROXY_PASSWORD", "")
    ssl_on = os.environ.get("CLOUD_SQL_PROXY_SSL", "").lower() in (
        "1",
        "true",
        "yes",
    )
    return host, port, password, ssl_on


# ── Connection pool ───────────────────────────────────────────────────────────

CACHE_TTL_SECONDS = 300

_pool: asyncpg.Pool | None = None
_connector: Connector | None = None

_cache: dict[str, float] = {}
_cache_negative: dict[str, float] = {}


async def init_pool() -> None:
    """Create the asyncpg connection pool via the Cloud SQL Python Connector."""
    global _pool, _connector
    if _pool is not None:
        return

    db_user = _require_env("DB_USER")

    proxy_args = _proxy_connect_args()
    if proxy_args is not None:
        phost, pport, pwd, ssl_on = proxy_args
        _connector = None

        async def _getconn_proxy(
            *_args: Any,
            **kwargs: Any,
        ) -> asyncpg.Connection:
            return await asyncpg.connect(
                host=phost,
                port=pport,
                user=db_user,
                password=pwd,
                database=_DB_NAME,
                ssl=ssl_on,
                **kwargs,
            )

        _pool = await asyncpg.create_pool(
            min_size=1,
            max_size=5,
            connection_class=asyncpg.Connection,
            connect=_getconn_proxy,
        )
        logger.info("API-key pool ready (proxy=%s:%s, db=%s)", phost, pport, _DB_NAME)
        return

    db_instance = _require_env("DB_INSTANCE")
    _connector = Connector()

    async def _getconn(*_args: Any, **kwargs: Any) -> asyncpg.Connection:
        _discard_pool_injected_connect_kwargs(kwargs)
        if kwargs:
            logger.warning(
                "api_keys pool: ignoring unexpected asyncpg connect kwargs: %s",
                sorted(kwargs),
            )
        return await _connector.connect_async(  # type: ignore[union-attr]
            db_instance,
            "asyncpg",
            user=db_user,
            db=_DB_NAME,
            enable_iam_auth=True,
            ip_type=_IP_TYPE,
        )

    _pool = await asyncpg.create_pool(
        min_size=1,
        max_size=5,
        connection_class=asyncpg.Connection,
        connect=_getconn,
    )
    logger.info(
        "API-key pool ready (%s, ip_type=%s, db=%s)", db_instance, _IP_TYPE, _DB_NAME
    )


async def close_pool() -> None:
    """Drain the connection pool and close the Cloud SQL connector."""
    global _pool, _connector
    if _pool:
        await _pool.close()
        _pool = None
    if _connector:
        await _connector.close_async()
        _connector = None
    logger.info("API-key pool closed")


# ── Key verification ──────────────────────────────────────────────────────────


async def verify_key(key: str) -> bool:
    """Return True if *key* exists in the api_keys table and is not revoked.

    Results are cached for CACHE_TTL_SECONDS to reduce DB round-trips.
    """
    if not key:
        return False

    now = time.monotonic()

    if key in _cache and (now - _cache[key]) < CACHE_TTL_SECONDS:
        return True
    if key in _cache_negative and (now - _cache_negative[key]) < CACHE_TTL_SECONDS:
        return False

    if _pool is None:
        logger.error("API-key pool not initialised — rejecting key")
        return False

    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM api_keys WHERE key = $1 AND revoked = FALSE",
                key,
            )
        if row:
            _cache[key] = now
            _cache_negative.pop(key, None)
            return True

        _cache_negative[key] = now
        _cache.pop(key, None)
        return False
    except Exception:
        logger.exception("Failed to verify API key against Cloud SQL")
        return key in _cache
