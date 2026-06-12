"""Cloud SQL (PostgreSQL + pgvector) implementation of the AgentStore protocol.

Uses :class:`~giulia.providers.database.CloudSqlConnector` for connection
management (GCP IAM auth via ``cloud-sql-python-connector``) and
:class:`~giulia.registry.embeddings.EmbeddingModel` for Vertex AI embeddings.

Quick start
-----------

.. code-block:: python

    from giulia.registry import Registry, CloudSQLAgentStore

    store = CloudSQLAgentStore()          # reads DB_* and EMBEDDING_* env vars
    async with Registry(store) as registry:
        agent = await registry.register(payload)
        results = await registry.search(keyword="billing")

Custom configuration
--------------------

.. code-block:: python

    from giulia.providers.database import CloudSqlConnector
    from giulia.registry.embeddings import EmbeddingModel
    from giulia.registry import Registry, CloudSQLAgentStore

    db = CloudSqlConnector(instance="project:region:instance", db="app", user="sa@project.iam")
    em = EmbeddingModel(project="my-project", location="us-central1")
    store = CloudSQLAgentStore(db=db, embedding_model=em)
    async with Registry(store) as registry:
        ...

Schema
------

Requires the ``agents`` table created by the CloudSQL migrations
(``dw-ai-brain/iac/migrations/``).  The ``embedding`` column must be of
type ``vector(768)`` (pgvector extension).
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any

from giulia.logging import logger
from giulia.registry.embeddings import EmbeddingModel, build_agent_text
from giulia.registry.models import AgentAddr


def _vec_to_pg(vec: list[float]) -> str:
    """Convert a float list to a pgvector literal, e.g. ``'[0.1,0.2,...]'``."""
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


def _row_to_agent(row: dict[str, Any]) -> AgentAddr:
    return AgentAddr(
        agent_id=row["agent_id"],
        agent_name=row["agent_name"],
        description=row["description"],
        company=row["company"],
        primary_facts_url=row["primary_facts_url"] or "",
        private_facts_url=row["private_facts_url"],
        adaptive_resolver_url=row["adaptive_resolver_url"],
        ttl=row["ttl_seconds"],
        signature=row["signature"] or "",
        registered_at=row["registered_at"],
        last_update=row["last_update"],
        capabilities=list(row["capabilities"] or []),
        protocol=row["protocol"] or "a2a",
        tier=row["tier"] or "private",  # type: ignore[arg-type]
        region=row["region"],
    )


class CloudSQLAgentStore:
    """Concrete :class:`~giulia.registry.AgentStore` backed by Cloud SQL + pgvector.

    Args:
        db: A :class:`~giulia.providers.database.DatabaseConnector` instance.
            Defaults to a new :class:`~giulia.providers.database.CloudSqlConnector`
            configured from environment variables (``DB_INSTANCE``, ``DB_NAME``,
            ``DB_USER``).
        embedding_model: An :class:`~giulia.registry.embeddings.EmbeddingModel`
            instance for computing vector embeddings.  Defaults to a new instance
            reading ``EMBEDDING_MODEL``, ``GCP_PROJECT_ID``, and ``VERTEX_LOCATION``
            from the environment.
        max_results: Maximum number of results for semantic search. Defaults to
            the ``SEMANTIC_SEARCH_MAX_RESULTS`` env var, falling back to ``100``.
        max_distance: Maximum cosine distance for semantic search results.
            Defaults to the ``SEMANTIC_MAX_DISTANCE`` env var, falling back to
            ``0.5``.
    """

    def __init__(
        self,
        db: Any | None = None,
        embedding_model: EmbeddingModel | None = None,
        max_results: int | None = None,
        max_distance: float | None = None,
    ) -> None:
        if db is None:
            from giulia.providers.database import CloudSqlConnector

            db = CloudSqlConnector()
        self._db = db
        self._em = embedding_model or EmbeddingModel()
        self._max_results = max_results or int(
            os.getenv("SEMANTIC_SEARCH_MAX_RESULTS", "100")
        )
        self._max_distance = max_distance or float(
            os.getenv("SEMANTIC_MAX_DISTANCE", "0.5")
        )

    # ------------------------------------------------------------------
    # AgentStore protocol
    # ------------------------------------------------------------------

    async def ensure_index(self) -> None:
        """Open the connection pool and verify pgvector is available."""
        await self._db.open()
        await self._db.execute("SELECT 1")
        logger.info("CloudSQL connection pool ready")

    async def save(self, agent: AgentAddr) -> AgentAddr:
        existing = await self.get(agent.agent_id)
        if existing:
            agent.registered_at = existing.registered_at
        agent.last_update = datetime.now(UTC)

        embedding_vec = await self._compute_embedding(agent)

        await self._db.execute(
            """
            INSERT INTO agents (
                agent_id, agent_name, description, company,
                service_url, public_url,
                primary_facts_url, private_facts_url, adaptive_resolver_url,
                tier, region, ttl_seconds, signature, protocol,
                capabilities, embedding,
                registered_at, last_update
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6,
                $7, $8, $9,
                $10, $11, $12, $13, $14,
                $15, $16,
                $17, $18
            )
            ON CONFLICT (agent_id) DO UPDATE SET
                agent_name            = EXCLUDED.agent_name,
                description           = EXCLUDED.description,
                company               = EXCLUDED.company,
                service_url           = EXCLUDED.service_url,
                public_url            = EXCLUDED.public_url,
                primary_facts_url     = EXCLUDED.primary_facts_url,
                private_facts_url     = EXCLUDED.private_facts_url,
                adaptive_resolver_url = EXCLUDED.adaptive_resolver_url,
                tier                  = EXCLUDED.tier,
                region                = EXCLUDED.region,
                ttl_seconds           = EXCLUDED.ttl_seconds,
                signature             = EXCLUDED.signature,
                protocol              = EXCLUDED.protocol,
                capabilities          = EXCLUDED.capabilities,
                embedding             = EXCLUDED.embedding,
                last_update           = EXCLUDED.last_update
            """,
            agent.agent_id,
            agent.agent_name,
            agent.description,
            agent.company,
            agent.private_facts_url,
            agent.primary_facts_url,
            agent.primary_facts_url,
            agent.private_facts_url,
            agent.adaptive_resolver_url,
            agent.tier.value if agent.tier else None,
            agent.region,
            agent.ttl,
            agent.signature,
            agent.protocol,
            list(agent.capabilities),
            embedding_vec,
            agent.registered_at,
            agent.last_update,
        )
        return agent

    async def get(self, agent_id: str) -> AgentAddr | None:
        row = await self._db.fetchrow(
            """
            SELECT agent_id, agent_name, description, company,
                   primary_facts_url, private_facts_url, adaptive_resolver_url,
                   ttl_seconds, signature, protocol,
                   capabilities, tier, region,
                   registered_at, last_update
            FROM agents
            WHERE agent_id = $1
            """,
            agent_id,
        )
        return _row_to_agent(row) if row else None

    async def search(
        self,
        capability: str | None = None,
        region: str | None = None,
        tier: str | None = None,
        keyword: str | None = None,
    ) -> list[AgentAddr]:
        kw = (keyword or "").strip() or None
        if kw:
            return await self._semantic_search(kw, capability, region, tier)
        return await self._structured_search(capability, region, tier)

    async def update(self, agent_id: str, updates: dict) -> AgentAddr | None:
        agent = await self.get(agent_id)
        if agent is None:
            return None
        for k, v in updates.items():
            if v is not None:
                setattr(agent, k, v)
        return await self.save(agent)

    async def delete(self, agent_id: str) -> bool:
        result = await self._db.execute(
            "DELETE FROM agents WHERE agent_id = $1", agent_id
        )
        return result == "DELETE 1"

    # ------------------------------------------------------------------
    # Search internals
    # ------------------------------------------------------------------

    async def _compute_embedding(self, agent: AgentAddr) -> str | None:
        text = build_agent_text(agent)
        try:
            vec = await asyncio.to_thread(self._em.embed_text, text)
            return _vec_to_pg(vec)
        except Exception:
            logger.exception(
                "Failed to embed agent {} — skipping vector index", agent.agent_id
            )
            return None

    async def _semantic_search(
        self,
        keyword: str,
        capability: str | None,
        region: str | None,
        tier: str | None,
    ) -> list[AgentAddr]:
        q_vec = await asyncio.to_thread(self._em.embed_query, keyword)
        q_literal = _vec_to_pg(q_vec)

        conditions: list[str] = ["embedding IS NOT NULL"]
        params: list[object] = [q_literal, self._max_distance, self._max_results]
        idx = 4  # $1=vec, $2=max_distance, $3=limit

        if capability:
            conditions.append(f"${idx} = ANY(capabilities)")
            params.append(capability)
            idx += 1
        if region:
            conditions.append(f"region = ${idx}")
            params.append(region)
            idx += 1
        if tier:
            conditions.append(f"tier = ${idx}")
            params.append(tier)
            idx += 1

        where = " AND ".join(conditions)
        query = f"""
            SELECT agent_id, agent_name, description, company,
                   primary_facts_url, private_facts_url, adaptive_resolver_url,
                   ttl_seconds, signature, protocol,
                   capabilities, tier, region,
                   registered_at, last_update,
                   (embedding <=> $1::vector) AS distance
            FROM agents
            WHERE {where}
              AND (embedding <=> $1::vector) < $2
            ORDER BY distance
            LIMIT $3
        """
        rows = await self._db.fetch(query, *params)
        return [_row_to_agent(row) for row in rows]

    async def _structured_search(
        self,
        capability: str | None,
        region: str | None,
        tier: str | None,
    ) -> list[AgentAddr]:
        conditions: list[str] = []
        params: list[object] = []
        idx = 1

        if capability:
            conditions.append(f"${idx} = ANY(capabilities)")
            params.append(capability)
            idx += 1
        if region:
            conditions.append(f"region = ${idx}")
            params.append(region)
            idx += 1
        if tier:
            conditions.append(f"tier = ${idx}")
            params.append(tier)
            idx += 1

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"""
            SELECT agent_id, agent_name, description, company,
                   primary_facts_url, private_facts_url, adaptive_resolver_url,
                   ttl_seconds, signature, protocol,
                   capabilities, tier, region,
                   registered_at, last_update
            FROM agents
            {where}
            ORDER BY agent_name
        """
        rows = await self._db.fetch(query, *params)
        return [_row_to_agent(row) for row in rows]
