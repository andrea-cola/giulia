"""High-level Registry facade.

Wraps any :class:`~giulia.registry.AgentStore` backend and provides a
developer-friendly async API for agent lifecycle management.

Usage as an async context manager::

    from giulia.registry import Registry

    async with Registry(my_store) as registry:
        agent = await registry.register(create_payload)
        results = await registry.search(keyword="invoice processing")
        await registry.delete(agent.agent_id)

Usage with explicit lifecycle::

    registry = Registry(my_store)
    await registry.open()
    try:
        agent = await registry.get("urn:agent:acme:private:billing")
    finally:
        await registry.close()
"""

from __future__ import annotations

from giulia.registry.models import AgentAddr, AgentAddrCreate, AgentAddrUpdate
from giulia.registry.store import AgentStore


class Registry:
    """Facade around an :class:`AgentStore` backend.

    Adds convenience methods (``register``, ``open``/``close``, context
    manager) on top of the raw storage protocol, and accepts both
    :class:`AgentAddrCreate` payloads and full :class:`AgentAddr` records
    in :meth:`register`.

    Parameters
    ----------
    store:
        Any object satisfying the :class:`AgentStore` protocol.
    """

    def __init__(self, store: AgentStore) -> None:
        self._store = store

    @property
    def store(self) -> AgentStore:
        """The underlying storage backend."""
        return self._store

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def open(self) -> None:
        """Initialise the backend (create indices, open connection pools).

        Delegates to :meth:`AgentStore.ensure_index`.  Safe to call more
        than once.
        """
        await self._store.ensure_index()

    async def close(self) -> None:
        """Release backend resources (close pools, drain connections).

        If the store exposes a ``close()`` coroutine it will be called;
        otherwise this is a no-op.
        """
        if hasattr(self._store, "close"):
            await self._store.close()

    async def __aenter__(self) -> Registry:
        await self.open()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Agent CRUD
    # ------------------------------------------------------------------

    async def register(self, payload: AgentAddrCreate | AgentAddr) -> AgentAddr:
        """Register a new agent or update an existing one.

        Accepts either an :class:`AgentAddrCreate` (the registration
        payload agents send at startup) or a full :class:`AgentAddr`
        record.  Returns the persisted record with server-set fields
        (``registered_at``, ``last_update``) populated.
        """
        if isinstance(payload, AgentAddrCreate):
            agent = AgentAddr(**payload.model_dump())
        else:
            agent = payload
        return await self._store.save(agent)

    async def get(self, agent_id: str) -> AgentAddr | None:
        """Resolve a single agent by its URN.

        Parameters
        ----------
        agent_id:
            Full URN, e.g. ``"urn:agent:acme:private:billing"``.

        Returns
        -------
        AgentAddr | None
            The agent record, or ``None`` if not found.
        """
        return await self._store.get(agent_id)

    async def search(
        self,
        *,
        capability: str | None = None,
        region: str | None = None,
        tier: str | None = None,
        keyword: str | None = None,
    ) -> list[AgentAddr]:
        """Search agents by structured filters and/or semantic keyword.

        All parameters are optional and can be combined freely.

        Parameters
        ----------
        capability:
            Exact capability URN filter.
        region:
            Deployment region filter.
        tier:
            ``"private"`` or ``"public"``.
        keyword:
            Free-text semantic search over name, description, company,
            and capabilities.

        Returns
        -------
        list[AgentAddr]
            Matching agents.  When *keyword* is used, results are ordered
            by semantic relevance.
        """
        return await self._store.search(
            capability=capability, region=region, tier=tier, keyword=keyword
        )

    async def update(
        self, agent_id: str, updates: AgentAddrUpdate | dict
    ) -> AgentAddr | None:
        """Apply a partial update to an existing agent.

        Parameters
        ----------
        agent_id:
            URN of the agent to update.
        updates:
            Either an :class:`AgentAddrUpdate` instance or a plain dict
            of ``{field_name: new_value}`` pairs.  ``None`` values are
            ignored.

        Returns
        -------
        AgentAddr | None
            The updated record, or ``None`` if *agent_id* was not found.
        """
        if isinstance(updates, AgentAddrUpdate):
            updates = updates.model_dump(exclude_none=True)
        return await self._store.update(agent_id, updates)

    async def delete(self, agent_id: str) -> bool:
        """Remove an agent from the registry.

        Returns ``True`` if the agent existed and was deleted.
        """
        return await self._store.delete(agent_id)
