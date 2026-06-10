"""Storage protocol for the agent registry.

Any class that implements the six async methods below can be used as a
backend for :class:`~giulia.registry.Registry`.  The protocol is
:func:`runtime_checkable <typing.runtime_checkable>`, so you can verify
conformance with ``isinstance(my_store, AgentStore)``.

Built-in implementations live outside this library (they carry their own
infrastructure dependencies):

- ``RedisAgentStore``     — dw-ai-brain/registry  (Redis + RediSearch)
- ``CloudSQLAgentStore``  — dw-ai-brain/registry  (PostgreSQL + pgvector)

Writing a custom backend
------------------------

.. code-block:: python

    from giulia.registry import AgentStore, AgentAddr

    class InMemoryStore:
        def __init__(self):
            self._agents: dict[str, AgentAddr] = {}

        async def ensure_index(self) -> None:
            pass  # nothing to initialise

        async def save(self, agent: AgentAddr) -> AgentAddr:
            self._agents[agent.agent_id] = agent
            return agent

        async def get(self, agent_id: str) -> AgentAddr | None:
            return self._agents.get(agent_id)

        async def search(self, *, capability=None, region=None,
                         tier=None, keyword=None) -> list[AgentAddr]:
            return list(self._agents.values())  # naive — filter as needed

        async def update(self, agent_id: str, updates: dict) -> AgentAddr | None:
            agent = self._agents.get(agent_id)
            if agent is None:
                return None
            for k, v in updates.items():
                setattr(agent, k, v)
            return await self.save(agent)

        async def delete(self, agent_id: str) -> bool:
            return self._agents.pop(agent_id, None) is not None

    assert isinstance(InMemoryStore(), AgentStore)  # ✓ passes
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from giulia.registry.models import AgentAddr


@runtime_checkable
class AgentStore(Protocol):
    """Read/write interface for agent registry storage backends.

    Every method is ``async``.  Implementations must handle their own
    connection management; :meth:`ensure_index` is called once at startup
    and is the right place to open pools, create indices, etc.
    """

    async def ensure_index(self) -> None:
        """One-time initialisation — create indices, open pools, verify connectivity.

        Called by :meth:`Registry.open` (or the ``async with`` entry).
        Must be idempotent: safe to call more than once.
        """
        ...

    async def save(self, agent: AgentAddr) -> AgentAddr:
        """Insert or update (upsert) *agent* and return the persisted record.

        If an agent with the same ``agent_id`` already exists, all mutable
        fields are overwritten.  ``registered_at`` should be preserved from
        the original record; ``last_update`` should be set to *now*.
        """
        ...

    async def get(self, agent_id: str) -> AgentAddr | None:
        """Look up a single agent by its URN.

        Returns the full :class:`AgentAddr` or ``None`` if not found.
        """
        ...

    async def search(
        self,
        capability: str | None = None,
        region: str | None = None,
        tier: str | None = None,
        keyword: str | None = None,
    ) -> list[AgentAddr]:
        """Return agents matching the supplied filters.

        Parameters
        ----------
        capability:
            Exact capability URN, e.g. ``"urn:cap:billing"``.
        region:
            Deployment region, e.g. ``"europe-west1"``.
        tier:
            ``"private"`` or ``"public"``.
        keyword:
            Free-text query.  When provided, the backend should perform a
            semantic (vector) search over agent name, description, company,
            and capabilities.  May be combined with the structured filters.

        Returns
        -------
        list[AgentAddr]
            Matching agents, ordered by relevance when *keyword* is used.
        """
        ...

    async def update(self, agent_id: str, updates: dict) -> AgentAddr | None:
        """Apply a partial update to an existing agent.

        *updates* is a ``dict`` of field-name → new-value pairs (typically
        produced by ``AgentAddrUpdate.model_dump(exclude_none=True)``).

        Returns the updated :class:`AgentAddr`, or ``None`` if no agent
        with *agent_id* exists.
        """
        ...

    async def delete(self, agent_id: str) -> bool:
        """Remove an agent from the store.

        Returns ``True`` if the agent existed and was deleted, ``False``
        otherwise.
        """
        ...
