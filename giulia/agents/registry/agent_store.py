"""Abstract storage protocol for the agent registry.

Concrete implementations (e.g. ``RedisAgentStore`` in the registry service)
satisfy this protocol so that any consumer can depend on the interface without
being coupled to a specific storage technology.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from giulia.agents.registry.models import AgentAddr


@runtime_checkable
class AgentStore(Protocol):
    """Read/write interface for agent registry storage backends."""

    async def ensure_index(self) -> None:
        """Initialise the backend (create indices, warm up connections, etc.)."""
        ...

    async def save(self, agent: AgentAddr) -> AgentAddr:
        """Upsert *agent* and return the persisted record."""
        ...

    async def get(self, agent_id: str) -> AgentAddr | None:
        """Return the agent with *agent_id*, or ``None`` if not found."""
        ...

    async def search(
        self,
        capability: str | None = None,
        region: str | None = None,
        tier: str | None = None,
        keyword: str | None = None,
    ) -> list[AgentAddr]:
        """Return agents matching the supplied filters.

        When *keyword* is provided a semantic/vector search is performed in
        addition to (or instead of) the structured filters.
        """
        ...

    async def update(self, agent_id: str, updates: dict) -> AgentAddr | None:
        """Apply *updates* to an existing agent and return the updated record.

        Returns ``None`` if no agent with *agent_id* exists.
        """
        ...

    async def delete(self, agent_id: str) -> bool:
        """Remove *agent_id* from the store.

        Returns ``True`` if the agent existed and was deleted, ``False``
        otherwise.
        """
        ...
