"""Human approval records for multi-agent workflows (Cloud SQL).

Append-only: each status change is a new row. ``approval_id`` groups history;
``event_id`` is the row primary key.

Table schema: ``lib/giulia/agents/sql/002_workflow_approvals.sql``.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, field_validator

from giulia.sql import get_db_client

logger = logging.getLogger(__name__)


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ALERT = "alert"


class WorkflowApprovalCreate(BaseModel):
    invocation_id: str
    session_id: str
    assignee: str
    target_agent_id: str
    user_id: str
    app_name: str | None = None
    process_id: str | None = None
    delegation_task_id: str | None = None
    prompt_summary: str | None = None
    approval_id: str | None = None
    next_step: str | None = None
    form_schema: dict | None = None

    @field_validator("form_schema", mode="before")
    @classmethod
    def _coerce_form_schema(cls, v: object) -> dict:
        return v if isinstance(v, dict) else {}


class WorkflowApprovalRecord(BaseModel):
    event_id: str
    approval_id: str
    invocation_id: str
    session_id: str
    process_id: str | None = None
    delegation_task_id: str | None = None
    assignee: str
    target_agent_id: str
    user_id: str
    app_name: str | None = None
    status: ApprovalStatus
    prompt_summary: str | None = None
    response_text: str | None = None
    next_step: str | None = None
    form_schema: dict = {}
    created_at: Any = None


def _parse_form_schema(val: Any) -> dict:
    """Parse form_schema from DB — returns dict (never None)."""
    import json as _json

    if val is None:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            parsed = _json.loads(val)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _row_to_record(row: dict[str, Any]) -> WorkflowApprovalRecord:
    return WorkflowApprovalRecord(
        event_id=row["event_id"],
        approval_id=row["approval_id"],
        invocation_id=row["invocation_id"],
        session_id=row["session_id"],
        process_id=row.get("process_id"),
        delegation_task_id=row.get("delegation_task_id"),
        assignee=row["assignee"],
        target_agent_id=row["target_agent_id"],
        user_id=row["user_id"],
        app_name=row.get("app_name"),
        status=ApprovalStatus(row["status"]),
        prompt_summary=row.get("prompt_summary"),
        response_text=row.get("response_text"),
        next_step=row.get("next_step"),
        form_schema=_parse_form_schema(row.get("form_schema")),
        created_at=row.get("created_at"),
    )


async def get_latest_approval(approval_id: str) -> WorkflowApprovalRecord | None:
    """Most recent event for *approval_id* (current state)."""
    try:
        db = get_db_client()
        await db.open()
        row = await db.fetchrow(
            """
            SELECT * FROM workflow_approvals
            WHERE approval_id = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            approval_id.strip(),
        )
        return _row_to_record(dict(row)) if row else None
    except Exception:
        logger.exception(
            "workflow_approvals: get_latest failed approval_id=%s", approval_id
        )
        return None


async def dispatch_to_human(
    *,
    invocation_id: str,
    session_id: str,
    source_agent_id: str,
    target_agent_id: str,
    assignee: str,
    prompt_summary: str,
    user_id: str,
    process_id: str | None = None,
    app_name: str | None = None,
    approval_id: str | None = None,
    next_step: str | None = None,
    form_schema: dict | None = None,
) -> WorkflowApprovalRecord | None:
    """Log a dispatching-to-human event and create the pending approval record atomically.

    This is the single entry point for any agent that needs a HITL gate.
    It writes a ``dispatching`` row to ``agent_task_log`` and then inserts
    the ``pending`` row in ``workflow_approvals``.

    Also sets ``current_hitl_pending`` so the delegation handler knows this
    invocation ended while waiting for human input — not as a true completion.

    Returns the approval record, or None on failure.
    """
    from giulia.agents.core.context import _hitl_pending_by_inv, current_hitl_pending
    from giulia.agents.orchestration.activity_log import log_event

    current_hitl_pending.set(True)
    _hitl_pending_by_inv[session_id] = True

    logger.info(
        "dispatch_to_human: source=%s -> human | session=%s inv=%s approval_id=%s",
        source_agent_id,
        session_id,
        invocation_id,
        approval_id,
    )

    await log_event(
        invocation_id=invocation_id,
        session_id=session_id,
        status="dispatching",
        source_agent_id=source_agent_id,
        source_app_name=app_name,
        process_id=process_id,
        target_agent_id="human",
        request=prompt_summary,
    )

    return await create_approval(
        WorkflowApprovalCreate(
            invocation_id=invocation_id,
            session_id=session_id,
            assignee=assignee,
            target_agent_id=target_agent_id,
            user_id=user_id,
            app_name=app_name,
            prompt_summary=prompt_summary,
            approval_id=approval_id,
            next_step=next_step,
            form_schema=form_schema,
            process_id=process_id,
        )
    )


async def create_approval(
    data: WorkflowApprovalCreate,
    status: ApprovalStatus = ApprovalStatus.PENDING,
) -> WorkflowApprovalRecord | None:
    """Append the initial row with the given status. Returns the record or None on failure.

    Pass ``status=ApprovalStatus.APPROVED`` to create an informational / auto-approved
    notification that does not require human action.
    """
    import json as _json

    approval_id = (data.approval_id or "").strip() or uuid4().hex
    event_id = uuid4().hex
    form_schema_json = _json.dumps(data.form_schema or {})
    try:
        db = get_db_client()
        await db.open()
        row = await db.fetchrow(
            """
            INSERT INTO workflow_approvals
                (event_id, approval_id, invocation_id, session_id,
                    delegation_task_id, assignee, target_agent_id, user_id, app_name,
                    status, prompt_summary, next_step, form_schema, process_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            RETURNING *
            """,
            event_id,
            approval_id,
            data.invocation_id.strip(),
            data.session_id.strip(),
            data.delegation_task_id,
            data.assignee.strip(),
            data.target_agent_id.strip(),
            data.user_id.strip(),
            data.app_name,
            status,
            data.prompt_summary,
            data.next_step,
            form_schema_json,
            data.process_id,
        )
        return _row_to_record(dict(row)) if row else None
    except Exception:
        logger.exception(
            "workflow_approvals: create failed invocation_id=%s", data.invocation_id
        )
        return None


async def resolve_approval(
    approval_id: str,
    *,
    status: ApprovalStatus,
    response_text: str | None = None,
) -> WorkflowApprovalRecord | None:
    """Append a terminal status row (no in-place update)."""
    import json as _json

    if status not in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.CANCELLED,
    ):
        return None

    latest = await get_latest_approval(approval_id)
    if latest is None or latest.status != ApprovalStatus.PENDING:
        return None

    event_id = uuid4().hex
    form_schema_json = _json.dumps(latest.form_schema or {})
    try:
        db = get_db_client()
        await db.open()
        row = await db.fetchrow(
            """
            INSERT INTO workflow_approvals
                (event_id, approval_id, invocation_id, session_id,
                    delegation_task_id, assignee, target_agent_id, user_id, app_name,
                    status, prompt_summary, response_text, next_step, form_schema, process_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            RETURNING *
            """,
            event_id,
            latest.approval_id,
            latest.invocation_id,
            latest.session_id,
            latest.delegation_task_id,
            latest.assignee,
            latest.target_agent_id,
            latest.user_id,
            latest.app_name,
            status,
            latest.prompt_summary,
            response_text,
            latest.next_step,
            form_schema_json,
            latest.process_id,
        )
        record = _row_to_record(dict(row)) if row else None
    except Exception:
        logger.exception(
            "workflow_approvals: resolve failed approval_id=%s", approval_id
        )
        return None

    if record is not None:
        from giulia.agents.orchestration.activity_log import log_event  # noqa: PLC0415

        # Map approval status to agent_task_log status
        log_status = (
            "completed"
            if status in (ApprovalStatus.APPROVED, ApprovalStatus.CANCELLED)
            else "error"  # rejected
        )
        await log_event(
            invocation_id=latest.invocation_id,
            session_id=latest.session_id,
            status=log_status,
            source_agent_id="human",
            target_agent_id=latest.target_agent_id,
            last_message=response_text or status.value,
        )

    return record
