"""Per-agent inbound delegation queue — HTTP handler and ADK runner integration.

Receiving agents expose ``POST /internal/delegation``. The handler enqueues work and
returns **202 Accepted** immediately. A background worker drives the ADK ``Runner``.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol
from uuid import uuid4

import httpx
from google.adk.agents import RunConfig
from google.adk.agents.run_config import StreamingMode
from google.adk.events import Event, EventActions  # noqa: PLC0415
from google.genai import types
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from giulia.agents.a2a.a2a_agent_factory import resolve_agent_base_url
from giulia.agents.core.constants import (
    INBOUND_DELEGATION_PATH,
    INBOUND_DELEGATION_SECRET_HEADER,
)
from giulia.agents.core.context import (
    _hitl_pending_by_inv,
    current_hitl_pending,
    current_process_id,
    current_session_id,
)
from giulia.agents.delegation.backends import (
    InboundDelegationBackend,
    create_inbound_delegation_backend,
)
from giulia.agents.delegation.types import InboundDelegationJob
from giulia.agents.orchestration.activity_log import log_event
from giulia.logging import logger

__all__ = [
    "InboundDelegationJob",
    "INBOUND_DELEGATION_PATH",
    "get_inbound_delegation_backend",
    "get_inbound_delegation_queue",
    "mount_inbound_delegation",
    "run_inbound_job_with_runner",
    "start_inbound_delegation_worker",
    "stop_inbound_delegation_worker",
    "submit_inbound_delegation",
    "inbound_delegation_lifespan",
]


class RunnerProtocol(Protocol):
    app_name: str
    session_service: Any

    def run_async(
        self, *, user_id: str, session_id: str, new_message: Any, run_config: RunConfig
    ) -> AsyncGenerator[Event, None]: ...


_backend: InboundDelegationBackend | None = None
_target_agent_id: str | None = None


def get_inbound_delegation_backend() -> InboundDelegationBackend:
    global _backend, _target_agent_id
    if _backend is None:
        if not _target_agent_id:
            raise RuntimeError(
                "Inbound delegation not configured; call mount_inbound_delegation() "
                "with target_agent_id first."
            )
        _backend = create_inbound_delegation_backend(
            target_agent_id=_target_agent_id,
        )
    return _backend


def get_inbound_delegation_queue() -> InboundDelegationBackend:
    """Backward-compatible alias."""
    return get_inbound_delegation_backend()


def inbound_delegation_secret() -> str:
    return (os.environ.get("INBOUND_DELEGATION_SECRET") or "").strip()


async def _ensure_delegation_session(
    runner: RunnerProtocol,
    *,
    user_id: str,
    session_id: str,
    initial_state: dict | None = None,
) -> None:
    existing = await runner.session_service.get_session(
        app_name=runner.app_name,
        user_id=user_id,
        session_id=session_id,
    )
    if existing:
        # Session exists — update in-memory state. The state_delta event appended
        # by _setup_correlation_state will persist these values properly.
        if initial_state and hasattr(existing, "state") and existing.state is not None:
            existing.state.update(initial_state)
            logger.debug(
                "Updated existing session state: session_id={} new_state={}",
                session_id,
                initial_state,
            )
        return
    await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id=user_id,
        session_id=session_id,
        state=initial_state,
    )
    logger.debug(
        "Created new delegation session: session_id={} initial_state={}",
        session_id,
        initial_state,
    )


async def _setup_correlation_state(
    runner: RunnerProtocol,
    *,
    user_id: str,
    session_id: str,
    process_id: str | None,
    invocation_id: str,
) -> None:
    """Prepare the ADK session and inject Datwave correlation IDs."""

    # Build initial state with correlation IDs
    initial_state: dict[str, str] = {"_dw_session_id": session_id}
    if process_id:
        initial_state["process_id"] = process_id

    # Ensure session exists with initial state properly set
    await _ensure_delegation_session(
        runner,
        user_id=user_id,
        session_id=session_id,
        initial_state=initial_state,
    )

    # Also append an event to record the state (for history/auditability)
    event = Event(
        invocation_id=invocation_id,
        author="system",
        actions=EventActions(state_delta=initial_state),
    )
    await runner.session_service.append_event(
        session=await runner.session_service.get_session(
            app_name=runner.app_name,
            user_id=user_id,
            session_id=session_id,
        ),
        event=event,
    )


async def _execute_agent_step(
    runner: RunnerProtocol,
    *,
    user_id: str,
    session_id: str,
    new_message: Any,
    on_thought: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Drive the ADK runner for one step and collect all texts/tool responses/thoughts.

    Returns a 3-tuple: (response_texts, tool_texts, thought_texts).

    Thought parts are identified by ``part.thought == True`` per the ADK
    ThinkingConfig contract (see https://github.com/google/adk-python/issues/770).
    They are collected separately so that callers can distinguish reasoning from
    the final agent answer without relying on streaming accumulation order.

    Args:
        on_thought: Optional callback invoked immediately when each thought is
            detected during streaming. Use this to persist thoughts in real-time.
    """
    response_texts: list[str] = []
    tool_texts: list[str] = []
    thought_texts: list[str] = []

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=new_message,
        run_config=RunConfig(streaming_mode=StreamingMode.SSE),
    ):
        content = getattr(event, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", None) or []:
            text = getattr(part, "text", None)
            thought_attr = getattr(part, "thought", None)
            if text:
                # Preserve the thought/text distinction that ADK collapses
                # when streaming: a part with thought=True is reasoning content.
                logger.debug(
                    "part: thought={} text_len={} preview={}",
                    thought_attr,
                    len(text),
                    text[:60].replace("\n", " "),
                )
                if thought_attr is True:
                    logger.warning("thought: {}", text)
                    thought_texts.append(text)
                    if on_thought:
                        await on_thought(text)
                else:
                    response_texts.append(text)

            # Extract results from Tool responses (for workflow log visibility)
            fn_resp = getattr(part, "function_response", None)
            if fn_resp is not None:
                resp_content = getattr(fn_resp, "response", None)
                if isinstance(resp_content, dict):
                    resp_text = (
                        resp_content.get("result")
                        or resp_content.get("output")
                        or resp_content.get("text")
                    )
                    if isinstance(resp_text, str) and resp_text.strip():
                        tool_texts.append(resp_text.strip())
                elif isinstance(resp_content, str) and resp_content.strip():
                    tool_texts.append(resp_content.strip())

    return response_texts, tool_texts, thought_texts


def _format_combined_message(
    response_texts: list[str], tool_texts: list[str]
) -> str | None:
    """Merge agent text and tool outputs into a single readable summary."""
    root_text = "\n".join(response_texts).strip()
    sub_text = "\n\n".join(tool_texts).strip()
    if root_text and sub_text:
        return f"{sub_text}\n\n{root_text}"
    return root_text or sub_text or None


async def run_inbound_job_with_runner(
    runner: RunnerProtocol, job: InboundDelegationJob
) -> None:
    """Run one delegated user message through a local ADK ``Runner``.

    Decomposes the execution into correlation setup, runner drive with retry,
    and status logging (running/completed/error).
    """

    user_id = (job.user_id or "delegation").strip() or "delegation"
    session_id = (job.session_id or job.invocation_id).strip()
    app_name = getattr(runner, "app_name", None)
    receiver_inv_id = uuid4().hex

    # Register a False sentinel in the process-level HITL dict before the turn
    # starts.  dispatch_to_human flips it to True if the agent calls a HITL tool.
    # We read (and clean up) the entry after the turn, regardless of outcome.
    _hitl_pending_by_inv[session_id] = False

    token = current_process_id.set(job.process_id or "")
    token_sid = current_session_id.set(session_id)
    try:
        # 1. Preparation
        try:
            await _setup_correlation_state(
                runner,
                user_id=user_id,
                session_id=session_id,
                process_id=job.process_id,
                invocation_id=receiver_inv_id,
            )
        except Exception:
            logger.warning(
                "failed to setup session correlation for session_id={}", session_id
            )

        # 2. Initial log
        new_message = types.Content(role="user", parts=[types.Part(text=job.request)])
        logger.info(
            "inbound delegation running: inv={} receiver_inv={} session={} request={!r}",
            job.invocation_id,
            receiver_inv_id,
            session_id,
            job.request[:200],
        )
        await log_event(
            invocation_id=receiver_inv_id,
            session_id=session_id,
            status="running",
            source_agent_id=_target_agent_id,
            source_app_name=app_name,
            process_id=job.process_id,
            parent_delegation_id=job.invocation_id,
        )

        # 3. Execution (with one retry on transient exceptions)
        from giulia.agents.orchestration.thoughts_log import log_thought

        async def _on_thought(thought_text: str) -> None:
            await log_thought(
                invocation_id=receiver_inv_id,
                session_id=session_id,
                thought_text=thought_text,
                source_agent_id=_target_agent_id,
                source_app_name=app_name,
                process_id=job.process_id,
            )

        res_texts: list[str] = []
        tool_texts: list[str] = []
        thought_texts: list[str] = []
        retry_done = False
        while True:
            try:
                res_texts, tool_texts, thought_texts = await _execute_agent_step(
                    runner,
                    user_id=user_id,
                    session_id=session_id,
                    new_message=new_message,
                    on_thought=_on_thought,
                )
                break
            except Exception as exc:
                if not retry_done:
                    retry_done = True
                    logger.warning(
                        "inbound delegation failed (will retry once) session={}: {}",
                        session_id,
                        exc,
                    )
                    continue

                # Permanent failure — include whatever partial output was collected
                partial = _format_combined_message(res_texts, tool_texts)
                await log_event(
                    invocation_id=receiver_inv_id,
                    session_id=session_id,
                    status="error",
                    source_agent_id=_target_agent_id,
                    source_app_name=app_name,
                    process_id=job.process_id,
                    parent_delegation_id=job.invocation_id,
                    last_message=partial,
                    error_message=str(exc),
                )
                raise

        # 4. Final log
        # If the agent called dispatch_to_human during this turn, the invocation
        # ended while waiting for HITL — not as a true completion. We signal this
        # by setting target_agent_id="human" so observers can distinguish it from
        # a genuine task completion (where target_agent_id is None).
        #
        # We check the process-level dict first (reliable across asyncio task
        # boundaries) then fall back to the ContextVar (works when ADK does not
        # spawn a new Task for the tool execution).
        hitl_pending = (
            _hitl_pending_by_inv.pop(session_id, False) or current_hitl_pending.get()
        )
        combined = _format_combined_message(res_texts, tool_texts)

        if thought_texts:
            total_thought_chars = sum(len(t) for t in thought_texts)
            logger.info(
                "inbound delegation thoughts: session={} parts={} total_chars={}",
                session_id,
                len(thought_texts),
                total_thought_chars,
            )

        await log_event(
            invocation_id=receiver_inv_id,
            session_id=session_id,
            status="completed",
            source_agent_id=_target_agent_id,
            source_app_name=app_name,
            process_id=job.process_id,
            parent_delegation_id=job.invocation_id,
            last_message=combined,
            target_agent_id="human" if hitl_pending else None,
        )

    finally:
        _hitl_pending_by_inv.pop(session_id, None)
        current_process_id.reset(token)
        current_session_id.reset(token_sid)


async def _delegation_accept_handler(request: Request) -> JSONResponse:
    try:
        raw = await request.body()
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"detail": "Invalid JSON body"}, status_code=400)

    if not isinstance(payload, dict):
        return JSONResponse({"detail": "Body must be a JSON object"}, status_code=400)

    req = (payload.get("request") or "").strip()
    if not req:
        return JSONResponse({"detail": "request is required"}, status_code=400)

    invocation_id = (payload.get("invocation_id") or "").strip() or uuid4().hex

    def _opt(key: str) -> str | None:
        v = payload.get(key)
        return str(v).strip() or None if v is not None else None

    backend = get_inbound_delegation_backend()
    if not backend.is_running:
        return JSONResponse(
            {"detail": "Inbound delegation worker is not running"},
            status_code=503,
        )

    job = InboundDelegationJob(
        request=req,
        invocation_id=invocation_id,
        session_id=_opt("session_id"),
        source_agent_id=_opt("source_agent_id"),
        source_app_name=_opt("source_app_name"),
        process_id=_opt("process_id"),
        user_id=_opt("user_id"),
        parent_delegation_id=_opt("parent_delegation_id"),
    )
    enqueued = await backend.enqueue(job)
    return JSONResponse(
        {
            "status": "accepted" if enqueued else "duplicate",
            "invocation_id": invocation_id,
            "session_id": job.session_id,
        },
        status_code=202,
    )


def delegation_local_base_url_override(agent_id: str) -> str | None:
    raw = (os.environ.get("INBOUND_DELEGATION_LOCAL_URLS") or "").strip()
    if not raw:
        return None
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("INBOUND_DELEGATION_LOCAL_URLS is not valid JSON; ignoring")
        return None
    if not isinstance(mapping, dict):
        return None
    url = mapping.get(agent_id)
    return str(url).strip() or None if url is not None else None


async def resolve_delegation_target_base_url(agent_id: str) -> str:
    override = delegation_local_base_url_override(agent_id)
    if override:
        logger.debug(
            "Using INBOUND_DELEGATION_LOCAL_URLS for %s -> %s", agent_id, override
        )
        return override.rstrip("/")
    return await resolve_agent_base_url(agent_id)


async def submit_inbound_delegation(
    *,
    target_agent_id: str,
    request: str,
    invocation_id: str | None,
    session_id: str | None,
    source_agent_id: str | None,
    source_app_name: str | None = None,
    process_id: str | None = None,
    user_id: str | None = None,
    parent_delegation_id: str | None = None,
    httpx_client: httpx.AsyncClient,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """POST a job to the target agent's inbound delegation endpoint (short HTTP)."""
    base_url = await resolve_delegation_target_base_url(target_agent_id)
    url = f"{base_url.rstrip('/')}{INBOUND_DELEGATION_PATH}"
    headers = {"Content-Type": "application/json"}
    secret = inbound_delegation_secret()
    if secret:
        headers[INBOUND_DELEGATION_SECRET_HEADER] = secret

    body: dict[str, Any] = {
        "request": request,
        "invocation_id": invocation_id,
        "session_id": session_id,
        "source_agent_id": source_agent_id,
        "source_app_name": source_app_name,
        "process_id": process_id,
        "parent_delegation_id": parent_delegation_id,
    }
    if user_id:
        body["user_id"] = user_id
    resp = await httpx_client.post(url, json=body, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError(
            f"inbound delegation response is not JSON object: {type(data)}"
        )
    return data


def mount_inbound_delegation(
    app: Starlette,
    runner: RunnerProtocol,
    *,
    target_agent_id: str,
) -> InboundDelegationBackend:
    """Register ``/internal/delegation`` and wire the worker to *runner*."""
    global _target_agent_id, _backend
    _target_agent_id = target_agent_id.strip()
    _backend = None
    backend = get_inbound_delegation_backend()
    backend.set_handler(lambda job: run_inbound_job_with_runner(runner, job))
    app.routes.append(
        Route(INBOUND_DELEGATION_PATH, _delegation_accept_handler, methods=["POST"])
    )
    return backend


async def start_inbound_delegation_worker() -> None:
    await get_inbound_delegation_backend().start()


async def stop_inbound_delegation_worker() -> None:
    await get_inbound_delegation_backend().stop()


@asynccontextmanager
async def inbound_delegation_lifespan(_app: Starlette) -> AsyncIterator[None]:
    await start_inbound_delegation_worker()
    try:
        yield
    finally:
        await stop_inbound_delegation_worker()
