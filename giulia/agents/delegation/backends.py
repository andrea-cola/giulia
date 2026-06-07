"""Inbound delegation queue backends (in-memory and Redis Streams)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from giulia.agents.delegation.types import InboundDelegationJob
from giulia.logging import logger


class InboundDelegationBackend(Protocol):
    def set_handler(
        self,
        handler: Callable[[InboundDelegationJob], Awaitable[None]],
    ) -> None: ...

    @property
    def is_running(self) -> bool: ...

    def pending_count(self) -> int: ...

    async def enqueue(self, job: InboundDelegationJob) -> bool: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def drain_for_tests(self, timeout: float = 30.0) -> None: ...


class InMemoryInboundDelegationBackend:
    """Local asyncio queue (set DELEGATION_BACKEND=memory in .env for local dev)."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[InboundDelegationJob | None] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._handler: Callable[[InboundDelegationJob], Awaitable[None]] | None = None
        self._processed_task_ids: set[str] = set()

    def set_handler(
        self,
        handler: Callable[[InboundDelegationJob], Awaitable[None]],
    ) -> None:
        self._handler = handler

    @property
    def is_running(self) -> bool:
        return self._worker_task is not None and not self._worker_task.done()

    def pending_count(self) -> int:
        return self._queue.qsize()

    async def enqueue(self, job: InboundDelegationJob) -> bool:
        if job.invocation_id in self._processed_task_ids:
            logger.info(
                "inbound delegation duplicate ignored (memory): task_id={}",
                job.invocation_id,
            )
            return False

        self._processed_task_ids.add(job.invocation_id)
        await self._queue.put(job)
        logger.info(
            "inbound delegation enqueued (memory): task_id={} source={} pending={}",
            job.invocation_id,
            job.source_agent_id or "(unknown)",
            self.pending_count(),
        )
        return True

    async def start(self) -> None:
        if self.is_running:
            return
        if self._handler is None:
            raise RuntimeError(
                "Inbound delegation backend has no handler; call set_handler() first."
            )
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Inbound delegation worker started (in-memory)")

    async def stop(self) -> None:
        if not self.is_running:
            return
        await self._queue.put(None)
        assert self._worker_task is not None
        await self._worker_task
        self._worker_task = None
        logger.info("Inbound delegation worker stopped (in-memory)")

    async def _worker_loop(self) -> None:
        assert self._handler is not None
        handler = self._handler
        while True:
            job = await self._queue.get()
            try:
                if job is None:
                    break
                await handler(job)
            except Exception:
                logger.exception(
                    "inbound delegation handler failed task_id={}",
                    job.invocation_id if job else "?",
                )
            finally:
                self._queue.task_done()

    async def drain_for_tests(self, timeout: float = 30.0) -> None:
        await asyncio.wait_for(self._queue.join(), timeout=timeout)


class RedisStreamsInboundDelegationBackend:
    """Redis Streams consumer on this pod; producer is the local HTTP accept handler."""

    def __init__(self, *, target_agent_id: str) -> None:
        self._target_agent_id = target_agent_id
        self._handler: Callable[[InboundDelegationJob], Awaitable[None]] | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._redis: Any = None
        self._stream_key: str | None = None

    def set_handler(
        self,
        handler: Callable[[InboundDelegationJob], Awaitable[None]],
    ) -> None:
        self._handler = handler

    @property
    def is_running(self) -> bool:
        return self._worker_task is not None and not self._worker_task.done()

    def pending_count(self) -> int:
        return 0

    async def enqueue(self, job: InboundDelegationJob) -> bool:
        from giulia.agents.delegation.redis_backend import (
            claim_task_for_enqueue,
            delegation_stream_key,
            ensure_delegation_stream,
            get_delegation_redis,
            job_to_stream_fields,
            set_task_status,
        )

        redis = await get_delegation_redis()
        stream_key = delegation_stream_key(self._target_agent_id)
        await ensure_delegation_stream(redis, stream_key)

        if not await claim_task_for_enqueue(
            redis,
            target_agent_id=self._target_agent_id,
            delegation_task_id=job.invocation_id,
        ):
            logger.info(
                "inbound delegation duplicate ignored: task_id={}",
                job.invocation_id,
            )
            return False

        await redis.xadd(stream_key, job_to_stream_fields(job))
        await set_task_status(
            redis,
            target_agent_id=self._target_agent_id,
            delegation_task_id=job.invocation_id,
            status="queued",
            extra={
                "source_agent_id": job.source_agent_id or "",
                "session_id": job.session_id or "",
            },
        )
        logger.info(
            "inbound delegation enqueued (redis): task_id={} source={} stream={}",
            job.invocation_id,
            job.source_agent_id or "(unknown)",
            stream_key,
        )
        return True

    async def start(self) -> None:
        if self.is_running:
            return
        if self._handler is None:
            raise RuntimeError(
                "Inbound delegation backend has no handler; call set_handler() first."
            )
        from giulia.agents.delegation.redis_backend import (
            delegation_consumer_name,
            delegation_stream_key,
            ensure_delegation_stream,
            get_delegation_redis,
        )

        self._redis = await get_delegation_redis()
        self._stream_key = delegation_stream_key(self._target_agent_id)
        await ensure_delegation_stream(self._redis, self._stream_key)
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info(
            "Inbound delegation worker started (redis stream={} consumer={})",
            self._stream_key,
            delegation_consumer_name(),
        )

    async def stop(self) -> None:
        if not self.is_running:
            return
        assert self._worker_task is not None
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass
        self._worker_task = None
        from giulia.agents.delegation.redis_backend import close_delegation_redis

        await close_delegation_redis()
        self._redis = None
        logger.info("Inbound delegation worker stopped (redis)")

    async def _worker_loop(self) -> None:
        from redis.exceptions import AuthenticationError

        from giulia.agents.delegation.redis_backend import (
            DELEGATION_CONSUMER_GROUP,
            close_delegation_redis,
            delegation_consumer_name,
            get_delegation_redis,
            job_from_stream_fields,
            set_task_status,
        )

        assert self._handler is not None
        assert self._redis is not None
        assert self._stream_key is not None

        handler = self._handler
        consumer = delegation_consumer_name()
        stream = self._stream_key
        auth_failures = 0

        while True:
            try:
                messages = await self._redis.xreadgroup(
                    DELEGATION_CONSUMER_GROUP,
                    consumer,
                    {stream: ">"},
                    count=1,
                    block=5000,
                )
                auth_failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if isinstance(exc, AuthenticationError):
                    auth_failures += 1
                    delay = min(60, 2 ** min(auth_failures, 5))
                    logger.warning(
                        "delegation Redis auth failed (attempt {}); "
                        "refreshing client, retry in {}s: {}",
                        auth_failures,
                        delay,
                        exc,
                    )
                    await close_delegation_redis()
                    self._redis = await get_delegation_redis(force_new=True)
                    await asyncio.sleep(delay)
                    continue

                logger.exception("delegation XREADGROUP failed; retrying in 2s")
                await asyncio.sleep(2)
                continue

            if not messages:
                continue

            for _stream_name, entries in messages:
                for entry_id, fields in entries:
                    job = job_from_stream_fields(fields)
                    try:
                        await set_task_status(
                            self._redis,
                            target_agent_id=self._target_agent_id,
                            delegation_task_id=job.invocation_id,
                            status="processing",
                        )
                        await handler(job)
                        await set_task_status(
                            self._redis,
                            target_agent_id=self._target_agent_id,
                            delegation_task_id=job.invocation_id,
                            status="completed",
                        )
                    except Exception:
                        await set_task_status(
                            self._redis,
                            target_agent_id=self._target_agent_id,
                            delegation_task_id=job.invocation_id,
                            status="failed",
                        )
                        logger.exception(
                            "inbound delegation handler failed task_id={}",
                            job.invocation_id,
                        )
                    finally:
                        await self._redis.xack(
                            stream,
                            DELEGATION_CONSUMER_GROUP,
                            entry_id,
                        )

    async def drain_for_tests(self, timeout: float = 30.0) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            status = await self._read_any_queued_status()
            if status is None:
                await asyncio.sleep(0.1)
                continue
            if status in ("completed", "failed"):
                return
            await asyncio.sleep(0.2)
        raise TimeoutError("delegation redis drain timed out")

    async def _read_any_queued_status(self) -> str | None:
        return None


def resolve_delegation_backend_name() -> str:
    explicit = (os.environ.get("DELEGATION_BACKEND") or "redis").strip().lower()
    if explicit in ("memory", "redis"):
        return explicit
    if explicit == "auto":
        from giulia.agents.delegation.redis_backend import memorystore_configured

        return "redis" if memorystore_configured() else "memory"
    return "redis"


def create_inbound_delegation_backend(
    *,
    target_agent_id: str,
) -> InboundDelegationBackend:
    name = resolve_delegation_backend_name()
    if name == "redis":
        logger.info(
            "Using Redis Streams inbound delegation for target={}",
            target_agent_id,
        )
        return RedisStreamsInboundDelegationBackend(target_agent_id=target_agent_id)
    logger.info(
        "Using in-memory inbound delegation for target={} (DELEGATION_BACKEND=memory)",
        target_agent_id,
    )
    return InMemoryInboundDelegationBackend()
