"""Memorystore Redis client and stream helpers for inbound delegation."""

from __future__ import annotations

import asyncio
import os
import socket
from typing import Any

from giulia.agents.core import config
from giulia.agents.utils import urn_to_slug
from giulia.logging import logger

MEMORYSTORE_HOST = config.memorystore_host.strip()
MEMORYSTORE_PORT = config.memorystore_port
# Memorystore IAM auth requires username "default" + access token as password.
MEMORYSTORE_IAM_USERNAME = config.memorystore_iam_username.strip()

DELEGATION_CONSUMER_GROUP = "delegation-workers"
DELEGATION_STREAM_PREFIX = "delegation:stream"

REDIS_AUTH_RETRY_ATTEMPTS = 3
REDIS_AUTH_RETRY_BASE_DELAY_S = 2

_pool: Any = None
_pool_lock = asyncio.Lock()


def memorystore_configured() -> bool:
    return bool(MEMORYSTORE_HOST)


def _make_redis_credential_provider() -> Any | None:
    """Build a redis-py CredentialProvider from the active RedisAuthProvider.

    Returns ``None`` when the active provider signals no authentication is
    needed (``get_credentials()`` returns ``None``).
    """
    from redis.credentials import CredentialProvider

    from giulia.providers.registry import get_redis_auth

    auth_provider = get_redis_auth()
    initial = auth_provider.get_credentials()
    if initial is None:
        return None

    class _Provider(CredentialProvider):
        def get_credentials(self) -> tuple[str, str]:
            creds = auth_provider.get_credentials()
            if creds is None:
                return "", ""
            return creds

        async def get_credentials_async(self) -> tuple[str, str]:
            creds = await auth_provider.refresh_token()
            return creds

    return _Provider()


async def _create_delegation_redis_pool() -> Any:
    from redis.asyncio.cluster import RedisCluster

    credential_provider = _make_redis_credential_provider()
    use_ssl = credential_provider is not None and MEMORYSTORE_HOST not in (
        "localhost",
        "127.0.0.1",
    )

    if credential_provider is not None:
        pool = RedisCluster(
            host=MEMORYSTORE_HOST,
            port=MEMORYSTORE_PORT,
            credential_provider=credential_provider,
            ssl=use_ssl,
            ssl_cert_reqs=None,
            decode_responses=True,
            require_full_coverage=False,
        )
    else:
        pool = RedisCluster(
            host=MEMORYSTORE_HOST,
            port=MEMORYSTORE_PORT,
            decode_responses=True,
            require_full_coverage=False,
        )
    await pool.initialize()
    return pool


async def get_delegation_redis(*, force_new: bool = False) -> Any:
    """Shared Redis cluster client for delegation streams."""
    global _pool
    async with _pool_lock:
        if _pool is not None and not force_new:
            return _pool
        old_pool = _pool if force_new else None
        if force_new:
            _pool = None

    if old_pool is not None:
        await old_pool.aclose()

    new_pool = await _create_delegation_redis_pool()
    async with _pool_lock:
        if _pool is None:
            _pool = new_pool
        elif _pool is not new_pool:
            await new_pool.aclose()
        return _pool


async def warm_up_delegation_redis() -> None:
    """Initialize cluster topology and verify IAM auth before first delegation."""
    if not memorystore_configured():
        return

    from redis.exceptions import AuthenticationError, ConnectionError

    last_exc: Exception | None = None
    for attempt in range(REDIS_AUTH_RETRY_ATTEMPTS):
        try:
            if attempt > 0:
                await close_delegation_redis()
            redis = await get_delegation_redis(force_new=attempt > 0)
            await redis.ping()
            logger.info(
                "delegation Redis cluster warmed up (host={})", MEMORYSTORE_HOST
            )
            return
        except (AuthenticationError, ConnectionError) as exc:
            last_exc = exc
            if attempt + 1 >= REDIS_AUTH_RETRY_ATTEMPTS:
                break
            delay = REDIS_AUTH_RETRY_BASE_DELAY_S * (attempt + 1)
            logger.warning(
                "delegation Redis warm-up failed (attempt {}/{}); retry in {}s: {}",
                attempt + 1,
                REDIS_AUTH_RETRY_ATTEMPTS,
                delay,
                exc,
            )
            await asyncio.sleep(delay)

    assert last_exc is not None
    raise last_exc


async def close_delegation_redis() -> None:
    global _pool
    async with _pool_lock:
        pool = _pool
        _pool = None
    if pool is not None:
        await pool.aclose()


def delegation_stream_key(target_agent_id: str) -> str:
    """One stream per receiving agent. Hash tag keeps stream + task keys on one slot."""
    slug = urn_to_slug(target_agent_id)
    return f"{{{DELEGATION_STREAM_PREFIX}:{slug}}}"


def delegation_task_key(target_agent_id: str, invocation_id: str) -> str:
    slug = urn_to_slug(target_agent_id)
    return f"{{{DELEGATION_STREAM_PREFIX}:{slug}}}:task:{invocation_id}"


def delegation_consumer_name() -> str:
    return (
        os.environ.get("HOSTNAME")
        or os.environ.get("POD_NAME")
        or socket.gethostname()
        or "delegation-worker"
    )


async def ensure_delegation_stream(redis: Any, stream_key: str) -> None:
    """Create stream + consumer group if missing (idempotent)."""
    from redis.exceptions import ResponseError

    try:
        await redis.xgroup_create(
            stream_key,
            DELEGATION_CONSUMER_GROUP,
            id="0",
            mkstream=True,
        )
        logger.info(
            "delegation stream ready: stream={} group={}",
            stream_key,
            DELEGATION_CONSUMER_GROUP,
        )
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def job_to_stream_fields(job: Any) -> dict[str, str]:
    return {
        "request": job.request,
        "invocation_id": job.invocation_id,
        "session_id": job.session_id or "",
        "source_agent_id": job.source_agent_id or "",
        "source_app_name": job.source_app_name or "",
        "process_id": job.process_id or "",
        "user_id": job.user_id or "",
        "parent_delegation_id": job.parent_delegation_id or "",
    }


def job_from_stream_fields(fields: dict[str, str]) -> Any:
    from giulia.agents.delegation.types import InboundDelegationJob

    def _opt(key: str) -> str | None:
        return (fields.get(key) or "").strip() or None

    return InboundDelegationJob(
        request=fields["request"],
        invocation_id=fields["invocation_id"],
        session_id=_opt("session_id"),
        source_agent_id=_opt("source_agent_id"),
        source_app_name=_opt("source_app_name"),
        process_id=_opt("process_id"),
        user_id=_opt("user_id"),
        parent_delegation_id=_opt("parent_delegation_id"),
    )


async def set_task_status(
    redis: Any,
    *,
    target_agent_id: str,
    delegation_task_id: str,
    status: str,
    extra: dict[str, str] | None = None,
) -> None:
    key = delegation_task_key(target_agent_id, delegation_task_id)
    mapping: dict[str, str] = {
        "status": status,
        "invocation_id": delegation_task_id,
    }
    if extra:
        mapping.update(extra)
    await redis.hset(key, mapping=mapping)


async def get_task_status(
    redis: Any,
    *,
    target_agent_id: str,
    delegation_task_id: str,
) -> dict[str, str] | None:
    key = delegation_task_key(target_agent_id, delegation_task_id)
    raw = await redis.hgetall(key)
    return raw or None


async def claim_task_for_enqueue(
    redis: Any,
    *,
    target_agent_id: str,
    delegation_task_id: str,
) -> bool:
    """Return True if this request should enqueue (new or retryable duplicate)."""
    key = delegation_task_key(target_agent_id, delegation_task_id)
    created = await redis.hsetnx(key, "status", "queued")
    if created:
        return True
    status = await redis.hget(key, "status")
    if status in ("failed",):
        await redis.hset(key, mapping={"status": "queued"})
        return True
    return False
