"""Receive A2A task push notifications at ``POST /internal/a2a-push``."""

from __future__ import annotations

import asyncio
import os
import secrets
from typing import Any

from a2a.types import Task
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from giulia.agents.core.constants import A2A_PUSH_PATH, A2A_PUSH_TOKEN_HEADER
from giulia.logging import logger

_inbox_lock = asyncio.Lock()
_inbox: dict[str, list[dict[str, Any]]] = {}
_expected_tokens: set[str] = set()


def get_push_inbox() -> dict[str, list[dict[str, Any]]]:
    """Return the in-memory push inbox (task_id -> list of task payloads)."""
    return _inbox


def register_push_token(token: str) -> None:
    """Register a token we expect on an incoming push (set when sending A2A)."""
    if token:
        _expected_tokens.add(token)


def push_callback_base_url() -> str:
    """Base URL where peers POST push notifications (no path suffix)."""
    explicit = (os.environ.get("A2A_PUSH_CALLBACK_BASE_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    service = (os.environ.get("SERVICE_URL") or "").strip()
    if service:
        return service.rstrip("/")
    return "http://127.0.0.1:8001"


def push_callback_url() -> str:
    return f"{push_callback_base_url()}{A2A_PUSH_PATH}"


def _shared_push_secret() -> str:
    # Push auth is per-task token (A2A spec). Do not fall back to delegation secret.
    return (os.environ.get("A2A_PUSH_SECRET") or "").strip()


def _token_required() -> bool:
    raw = (os.environ.get("A2A_PUSH_REQUIRE_TOKEN") or "").strip().lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    # Default: require token when a shared secret or pending tokens exist.
    return bool(_shared_push_secret() or _expected_tokens)


async def _validate_push_token(header_token: str) -> bool:
    if not _token_required():
        return True
    if not header_token:
        return False
    shared = _shared_push_secret()
    if shared and secrets.compare_digest(header_token, shared):
        return True
    # Do not single-use discard: Sophia sends multiple pushes per task (working → completed).
    return header_token in _expected_tokens


async def _push_receive_handler(request: Request) -> JSONResponse:
    header_token = request.headers.get(A2A_PUSH_TOKEN_HEADER, "")
    if not await _validate_push_token(header_token):
        logger.warning(
            "A2A push rejected (401): missing or unknown %s (registered=%s)",
            A2A_PUSH_TOKEN_HEADER,
            len(_expected_tokens),
        )
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    body = await request.json()
    try:
        task = Task.model_validate(body)
    except Exception:
        logger.warning("Invalid A2A push payload: %s", body)
        return JSONResponse({"detail": "Invalid task payload"}, status_code=400)

    task_payload = task.model_dump(mode="json", exclude_none=True)
    state = (
        task.status.state.value
        if hasattr(task.status.state, "value")
        else str(task.status.state)
    )

    async with _inbox_lock:
        _inbox.setdefault(task.id, []).append(task_payload)

    logger.info(
        "A2A push received: task_id=%s state=%s context_id=%s",
        task.id,
        state,
        task.context_id,
    )
    return JSONResponse({"status": "ok", "task_id": task.id, "state": state})


def mount_a2a_push_receiver(app: Starlette) -> None:
    """Register the push callback route on *app*."""
    app.routes.append(Route(A2A_PUSH_PATH, _push_receive_handler, methods=["POST"]))
