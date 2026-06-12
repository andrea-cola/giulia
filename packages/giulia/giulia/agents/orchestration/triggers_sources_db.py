"""Database queries for agent triggers and sources.

Reads from ``triggers`` and ``sources`` tables (Cloud SQL).

Table schema: ``lib/giulia/agents/sql/006_triggers_sources.sql``.
"""

from __future__ import annotations

import logging
from typing import Any

from giulia.sql import get_db_client

logger = logging.getLogger(__name__)


async def get_triggers_for_agent(agent_id: str) -> list[dict[str, Any]]:
    """Return all active triggers for a specific agent."""
    try:
        db = get_db_client()
        await db.open()
        return await db.fetch(
            """
            SELECT id, agent_id, trigger_type, trigger_name, description, config, is_active, created_at
            FROM triggers
            WHERE agent_id = $1 AND is_active = TRUE
            ORDER BY created_at ASC
            """,
            agent_id,
        )
    except Exception:
        logger.exception("get_triggers_for_agent(%s) failed", agent_id)
        return []


async def get_sources_for_agent(agent_id: str) -> list[dict[str, Any]]:
    """Return all active sources for a specific agent."""
    try:
        db = get_db_client()
        await db.open()
        return await db.fetch(
            """
            SELECT id, agent_id, source_type, source_name, description, config, is_active, created_at
            FROM sources
            WHERE agent_id = $1 AND is_active = TRUE
            ORDER BY created_at ASC
            """,
            agent_id,
        )
    except Exception:
        logger.exception("get_sources_for_agent(%s) failed", agent_id)
        return []


async def get_triggers_for_agents(
    agent_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Return all active triggers for multiple agents, grouped by agent_id."""
    if not agent_ids:
        return {}
    try:
        db = get_db_client()
        await db.open()
        rows = await db.fetch(
            """
            SELECT id, agent_id, trigger_type, trigger_name, description, config, is_active, created_at
            FROM triggers
            WHERE agent_id = ANY($1) AND is_active = TRUE
            ORDER BY agent_id, created_at ASC
            """,
            agent_ids,
        )
        result: dict[str, list[dict[str, Any]]] = {aid: [] for aid in agent_ids}
        for row in rows:
            aid = row.get("agent_id")
            if aid in result:
                result[aid].append(row)
        return result
    except Exception:
        logger.exception("get_triggers_for_agents failed")
        return {}


async def get_sources_for_agents(
    agent_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Return all active sources for multiple agents, grouped by agent_id."""
    if not agent_ids:
        return {}
    try:
        db = get_db_client()
        await db.open()
        rows = await db.fetch(
            """
            SELECT id, agent_id, source_type, source_name, description, config, is_active, created_at
            FROM sources
            WHERE agent_id = ANY($1) AND is_active = TRUE
            ORDER BY agent_id, created_at ASC
            """,
            agent_ids,
        )
        result: dict[str, list[dict[str, Any]]] = {aid: [] for aid in agent_ids}
        for row in rows:
            aid = row.get("agent_id")
            if aid in result:
                result[aid].append(row)
        return result
    except Exception:
        logger.exception("get_sources_for_agents failed")
        return {}


async def get_all_triggers() -> list[dict[str, Any]]:
    """Return all triggers."""
    try:
        db = get_db_client()
        await db.open()
        return await db.fetch(
            """
            SELECT id, agent_id, trigger_type, trigger_name, description, config, is_active, created_at
            FROM triggers
            ORDER BY agent_id, created_at ASC
            """
        )
    except Exception:
        logger.exception("get_all_triggers failed")
        return []


async def get_all_sources() -> list[dict[str, Any]]:
    """Return all sources."""
    try:
        db = get_db_client()
        await db.open()
        return await db.fetch(
            """
            SELECT id, agent_id, source_type, source_name, description, config, is_active, created_at
            FROM sources
            ORDER BY agent_id, created_at ASC
            """
        )
    except Exception:
        logger.exception("get_all_sources failed")
        return []
