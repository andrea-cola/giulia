"""Database-backed agent heartbeat tracking.

Writes heartbeat records to ``agents`` (Cloud SQL) on each heartbeat
cycle. This provides persistent liveness tracking in addition to the Redis-based
registry TTL.

Table schema: ``giulia/agents/sql/005_agent_heartbeat.sql``.
"""

from __future__ import annotations

import logging
from typing import Any

from giulia.logging import logger as _loguru_logger
from giulia.sql import get_db_client

logger = logging.getLogger(__name__)


async def record_heartbeat(
    *,
    agent_id: str,
    agent_name: str,
    company: str | None = None,
    service_url: str | None = None,
    public_url: str | None = None,
    tier: str | None = None,
    region: str | None = None,
    ttl_seconds: int = 900,
) -> None:
    """Record a heartbeat in the database (best-effort, never raises).

    Uses INSERT ... ON CONFLICT to upsert: creates the row on first heartbeat,
    updates last_heartbeat on subsequent ones.
    """
    _loguru_logger.debug(
        "agents: recording heartbeat for agent_id={} name={}",
        agent_id,
        agent_name,
    )
    try:
        db = get_db_client()
        await db.open()
        await db.execute(
            """
            INSERT INTO agents
                (agent_id, agent_name, company, service_url, public_url,
                 tier, region, ttl_seconds, first_seen, last_heartbeat)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), NOW())
            ON CONFLICT (agent_id) DO UPDATE SET
                agent_name = EXCLUDED.agent_name,
                company = EXCLUDED.company,
                service_url = EXCLUDED.service_url,
                public_url = EXCLUDED.public_url,
                tier = EXCLUDED.tier,
                region = EXCLUDED.region,
                ttl_seconds = EXCLUDED.ttl_seconds,
                last_heartbeat = NOW()
            """,
            agent_id,
            agent_name,
            company,
            service_url,
            public_url,
            tier,
            region,
            ttl_seconds,
        )
    except Exception:
        _loguru_logger.exception(
            "agents: FAILED to record heartbeat for agent_id={} name={}",
            agent_id,
            agent_name,
        )


async def get_live_agents() -> list[dict[str, Any]]:
    """Return all agents with recent heartbeats (within their TTL)."""
    try:
        db = get_db_client()
        await db.open()
        return await db.fetch(
            """
            SELECT *,
                   EXTRACT(EPOCH FROM (NOW() - last_heartbeat)) AS seconds_since_heartbeat,
                   (last_heartbeat > NOW() - (ttl_seconds || ' seconds')::INTERVAL) AS is_alive
            FROM agents
            WHERE last_heartbeat > NOW() - (ttl_seconds || ' seconds')::INTERVAL
            ORDER BY last_heartbeat DESC
            """
        )
    except Exception:
        logger.exception("agents: get_live_agents failed")
        return []


async def get_dead_agents() -> list[dict[str, Any]]:
    """Return all agents that have missed their heartbeat (beyond TTL)."""
    try:
        db = get_db_client()
        await db.open()
        return await db.fetch(
            """
            SELECT *,
                   EXTRACT(EPOCH FROM (NOW() - last_heartbeat)) AS seconds_since_heartbeat,
                   FALSE AS is_alive
            FROM agents
            WHERE last_heartbeat <= NOW() - (ttl_seconds || ' seconds')::INTERVAL
            ORDER BY last_heartbeat DESC
            """
        )
    except Exception:
        logger.exception("agents: get_dead_agents failed")
        return []


async def get_all_agents() -> list[dict[str, Any]]:
    """Return all known agents with their liveness status."""
    try:
        db = get_db_client()
        await db.open()
        return await db.fetch(
            """
            SELECT *,
                   EXTRACT(EPOCH FROM (NOW() - last_heartbeat)) AS seconds_since_heartbeat,
                   (last_heartbeat > NOW() - (ttl_seconds || ' seconds')::INTERVAL) AS is_alive
            FROM agents
            ORDER BY last_heartbeat DESC
            """
        )
    except Exception:
        logger.exception("agents: get_all_agents failed")
        return []


async def get_agent(agent_id: str) -> dict[str, Any] | None:
    """Return heartbeat info for a specific agent."""
    try:
        db = get_db_client()
        await db.open()
        return await db.fetchrow(
            """
            SELECT *,
                   EXTRACT(EPOCH FROM (NOW() - last_heartbeat)) AS seconds_since_heartbeat,
                   (last_heartbeat > NOW() - (ttl_seconds || ' seconds')::INTERVAL) AS is_alive
            FROM agents
            WHERE agent_id = $1
            """,
            agent_id,
        )
    except Exception:
        logger.exception("agents: get_agent(%s) failed", agent_id)
        return None


async def get_agents_by_company(company: str) -> list[dict[str, Any]]:
    """Return all agents for a specific company with their liveness status."""
    try:
        db = get_db_client()
        await db.open()
        return await db.fetch(
            """
            SELECT *,
                   EXTRACT(EPOCH FROM (NOW() - last_heartbeat)) AS seconds_since_heartbeat,
                   (last_heartbeat > NOW() - (ttl_seconds || ' seconds')::INTERVAL) AS is_alive
            FROM agents
            WHERE company = $1
            ORDER BY last_heartbeat DESC
            """,
            company,
        )
    except Exception:
        logger.exception("agents: get_agents_by_company(%s) failed", company)
        return []
