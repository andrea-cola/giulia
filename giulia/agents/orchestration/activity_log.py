"""Insert-only activity log for inter-agent orchestration tracking.

Writes to ``agent_task_log`` (Cloud SQL). Each call to :func:`log_event`
inserts one row — the table is never updated in place.

Table schema: ``lib/giulia/agents/sql/001_agent_task_log.sql``.
"""

from __future__ import annotations

import logging
from typing import Any

from giulia.logging import logger as _loguru_logger
from giulia.sql import get_db_client

logger = logging.getLogger(__name__)

_VALID_STATUSES = frozenset({"running", "dispatching", "completed", "error"})


async def log_event(
    *,
    invocation_id: str,
    session_id: str,
    status: str,
    source_agent_id: str | None = None,
    source_app_name: str | None = None,
    process_id: str | None = None,
    parent_delegation_id: str | None = None,
    target_agent_id: str | None = None,
    request: str | None = None,
    last_message: str | None = None,
    error_message: str | None = None,
) -> None:
    """Insert one event row in agent_task_log (best-effort, never raises)."""
    if status not in _VALID_STATUSES:
        logger.warning("agent_task_log: unknown status %r, skipping write", status)
        return
    _loguru_logger.debug(
        "agent_task_log: inserting status={} src={} -> tgt={} inv={} session={}",
        status,
        source_agent_id,
        target_agent_id,
        invocation_id,
        session_id,
    )
    try:
        db = get_db_client()
        await db.open()
        await db.execute(
            """
            INSERT INTO agent_task_log
                (process_id, invocation_id, session_id,
                    source_agent_id, source_app_name,
                    status, parent_delegation_id,
                    target_agent_id, request, last_message, error_message)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            process_id,
            invocation_id,
            session_id,
            source_agent_id,
            source_app_name,
            status,
            parent_delegation_id,
            target_agent_id,
            request,
            last_message,
            error_message,
        )
    except Exception:
        _loguru_logger.exception(
            "agent_task_log: FAILED to insert status={} src={} inv={} session={}",
            status,
            source_agent_id,
            invocation_id,
            session_id,
        )


async def get_invocation(invocation_id: str) -> list[dict[str, Any]]:
    """Return all events for one invocation, ordered by created_at."""
    try:
        db = get_db_client()
        await db.open()
        return await db.fetch(
            "SELECT * FROM agent_task_log WHERE invocation_id = $1 ORDER BY created_at ASC",
            invocation_id,
        )
    except Exception:
        logger.exception("agent_task_log: get invocation_id=%s failed", invocation_id)
        return []


async def get_workflow_by_session(session_id: str) -> list[dict[str, Any]]:
    """Return all events linked to a session_id (cross-agent chain)."""
    try:
        db = get_db_client()
        await db.open()
        return await db.fetch(
            """
            SELECT * FROM agent_task_log
            WHERE session_id = $1 OR invocation_id = $1
            ORDER BY created_at ASC
            """,
            session_id,
        )
    except Exception:
        logger.exception("agent_task_log: get session_id=%s failed", session_id)
        return []


async def get_process(process_id: str) -> list[dict[str, Any]]:
    """Return all events for a business process, ordered by created_at."""
    try:
        db = get_db_client()
        await db.open()
        return await db.fetch(
            "SELECT * FROM agent_task_log WHERE process_id = $1 ORDER BY created_at ASC",
            process_id,
        )
    except Exception:
        logger.exception("agent_task_log: get process_id=%s failed", process_id)
        return []
