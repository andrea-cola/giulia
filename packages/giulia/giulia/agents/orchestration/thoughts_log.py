"""Insert-only thoughts log for model reasoning/thinking parts.

Writes to ``agent_thoughts`` (Cloud SQL). Each call to :func:`log_thoughts`
inserts one row containing the combined thought content from an agent run.

Table schema: ``lib/giulia/agents/sql/007_agent_thoughts.sql``.
"""

from __future__ import annotations

import logging
from typing import Any

from giulia.logging import logger as _loguru_logger
from giulia.sql import get_db_client

logger = logging.getLogger(__name__)


async def log_thought(
    *,
    invocation_id: str,
    session_id: str,
    thought_text: str,
    source_agent_id: str | None = None,
    source_app_name: str | None = None,
    process_id: str | None = None,
    model: str | None = None,
) -> None:
    """Insert a single thought into agent_thoughts (best-effort, never raises).

    Args:
        invocation_id: Unique identifier for this agent run.
        session_id: Workflow correlation key.
        thought_text: Single thought text chunk from streaming.
        source_agent_id: Agent URN that produced this thought.
        source_app_name: ADK app_name of the agent.
        process_id: Business process grouping.
        model: Model that generated the thought.
    """
    if not thought_text or not thought_text.strip():
        return

    thought_text = thought_text.strip()

    _loguru_logger.debug(
        "agent_thoughts: inserting inv={} session={} chars={}",
        invocation_id,
        session_id,
        len(thought_text),
    )

    try:
        db = get_db_client()
        await db.open()
        await db.execute(
            """
            INSERT INTO agent_thoughts
                (process_id, invocation_id, session_id,
                 source_agent_id, source_app_name,
                 thought_text, thought_chunks, total_chars, model)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            process_id,
            invocation_id,
            session_id,
            source_agent_id,
            source_app_name,
            thought_text,
            1,
            len(thought_text),
            model,
        )
    except Exception:
        _loguru_logger.exception(
            "agent_thoughts: FAILED to insert inv={} session={}",
            invocation_id,
            session_id,
        )


async def log_thoughts(
    *,
    invocation_id: str,
    session_id: str,
    thought_texts: list[str],
    source_agent_id: str | None = None,
    source_app_name: str | None = None,
    process_id: str | None = None,
    model: str | None = None,
) -> None:
    """Insert thought content into agent_thoughts (best-effort, never raises).

    Args:
        invocation_id: Unique identifier for this agent run.
        session_id: Workflow correlation key.
        thought_texts: List of thought text chunks from streaming.
        source_agent_id: Agent URN that produced these thoughts.
        source_app_name: ADK app_name of the agent.
        process_id: Business process grouping.
        model: Model that generated the thoughts.
    """
    if not thought_texts:
        return

    combined_text = "\n\n".join(thought_texts).strip()
    if not combined_text:
        return

    _loguru_logger.debug(
        "agent_thoughts: inserting inv={} session={} chunks={} chars={}",
        invocation_id,
        session_id,
        len(thought_texts),
        len(combined_text),
    )

    try:
        db = get_db_client()
        await db.open()
        await db.execute(
            """
            INSERT INTO agent_thoughts
                (process_id, invocation_id, session_id,
                 source_agent_id, source_app_name,
                 thought_text, thought_chunks, total_chars, model)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            process_id,
            invocation_id,
            session_id,
            source_agent_id,
            source_app_name,
            combined_text,
            len(thought_texts),
            len(combined_text),
            model,
        )
    except Exception:
        _loguru_logger.exception(
            "agent_thoughts: FAILED to insert inv={} session={}",
            invocation_id,
            session_id,
        )


async def get_thoughts_by_invocation(invocation_id: str) -> list[dict[str, Any]]:
    """Return all thoughts for one invocation."""
    try:
        db = get_db_client()
        await db.open()
        return await db.fetch(
            "SELECT * FROM agent_thoughts WHERE invocation_id = $1 ORDER BY created_at ASC",
            invocation_id,
        )
    except Exception:
        logger.exception("agent_thoughts: get invocation_id=%s failed", invocation_id)
        return []


async def get_thoughts_by_session(session_id: str) -> list[dict[str, Any]]:
    """Return all thoughts for a session (workflow chain)."""
    try:
        db = get_db_client()
        await db.open()
        return await db.fetch(
            "SELECT * FROM agent_thoughts WHERE session_id = $1 ORDER BY created_at ASC",
            session_id,
        )
    except Exception:
        logger.exception("agent_thoughts: get session_id=%s failed", session_id)
        return []


async def get_thoughts_by_process(process_id: str) -> list[dict[str, Any]]:
    """Return all thoughts for a business process."""
    try:
        db = get_db_client()
        await db.open()
        return await db.fetch(
            "SELECT * FROM agent_thoughts WHERE process_id = $1 ORDER BY created_at ASC",
            process_id,
        )
    except Exception:
        logger.exception("agent_thoughts: get process_id=%s failed", process_id)
        return []
