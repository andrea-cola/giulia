"""Starlette HTTP routes for agent-side HITL approval handling.

Mount via :func:`mount_workflow_approvals` in each agent's ``server.py``.
Exposes ``POST /internal/workflow-approvals/{approval_id}`` so that any caller
(API server, other agents, scripts) can resolve a pending approval and
re-inject the answer into this agent's inbound delegation queue.
"""

from __future__ import annotations

import json

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from giulia.agents.core.constants import WORKFLOW_APPROVALS_PATH
from giulia.agents.orchestration.approvals import (
    ApprovalStatus,
    WorkflowApprovalCreate,
    create_approval,
    resolve_approval,
)
from giulia.logging import logger

_local_agent_id: str | None = None


def mount_workflow_approvals(app: Starlette, *, target_agent_id: str) -> None:
    """Register ``/internal/workflow-approvals`` routes on *app*."""
    global _local_agent_id
    _local_agent_id = target_agent_id.strip()
    app.routes.append(Route(WORKFLOW_APPROVALS_PATH, _create_handler, methods=["POST"]))
    app.routes.append(
        Route(
            f"{WORKFLOW_APPROVALS_PATH}/{{approval_id}}",
            _resolve_handler,
            methods=["PATCH"],
        )
    )


async def _create_handler(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"detail": "Invalid JSON body"}, status_code=400)

    record = await create_approval(
        WorkflowApprovalCreate(
            approval_id=payload.get("approval_id"),
            invocation_id=payload.get("invocation_id"),
            session_id=payload.get("session_id"),
            user_id=payload.get("user_id"),
            target_agent_id=payload.get("target_agent_id") or _local_agent_id or "",
            assignee=payload.get("assignee"),
            prompt_summary=payload.get("prompt_summary"),
            app_name=payload.get("app_name"),
            delegation_task_id=payload.get("delegation_task_id"),
        )
    )
    if record is None:
        return JSONResponse({"detail": "Failed to create approval"}, status_code=500)

    return JSONResponse(
        {"status": "awaiting_approval", "approval_id": record.approval_id},
        status_code=202,
    )


async def _resolve_handler(request: Request) -> JSONResponse:
    approval_id = request.path_params.get("approval_id") or ""
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"detail": "Invalid JSON body"}, status_code=400)

    status_raw = (payload.get("status") or "").lower()
    try:
        status = ApprovalStatus(status_raw)
    except ValueError:
        return JSONResponse({"detail": "Invalid status"}, status_code=400)

    record = await resolve_approval(
        approval_id,
        status=status,
        response_text=payload.get("response_text"),
    )
    if record is None:
        return JSONResponse({"detail": "Not found or not pending"}, status_code=404)

    if status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
        resume_msg = "[HITL Response] The human reviewer has responded to your pending approval request."
        if record.prompt_summary:
            resume_msg += f"\n\nOriginal request: {record.prompt_summary}"
        resume_msg += f"\n\nDecision: {status.value.upper()}"
        if record.response_text:
            resume_msg += f"\nReviewer note: {record.response_text}"
        if record.next_step:
            resume_msg += f"\n\nNext action required: {record.next_step}"
        else:
            resume_msg += (
                "\n\nPlease continue with the workflow based on this decision."
            )
        try:
            from giulia.agents.delegation.handler import submit_inbound_delegation

            async with httpx.AsyncClient(timeout=10.0) as client:
                await submit_inbound_delegation(
                    target_agent_id=record.target_agent_id,
                    request=resume_msg,
                    invocation_id=f"resume-{record.approval_id}",
                    session_id=record.session_id,
                    process_id=record.process_id,
                    source_agent_id="orchestration",
                    user_id=record.user_id,
                    httpx_client=client,
                )
        except Exception:
            logger.warning(
                "HITL resume delegation failed for approval_id=%s", approval_id
            )

    return JSONResponse({"status": record.status.value})
