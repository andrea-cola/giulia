"""Agent registry — models, storage protocol, facade, and ADK tools.

This package is the canonical home for the agent registry within the giulia
framework.  It provides everything a developer needs to interact with the
registry — whether building a new storage backend, registering agents, or
wiring up ADK tools.

Quick start
-----------

.. code-block:: python

    from giulia.registry import Registry, AgentStore

    class MyStore:
        \"\"\"A custom AgentStore backend (Redis, SQL, in-memory, ...).\"\"\"
        async def ensure_index(self) -> None: ...
        async def save(self, agent): ...
        async def get(self, agent_id): ...
        async def search(self, *, capability=None, region=None, tier=None, keyword=None): ...
        async def update(self, agent_id, updates): ...
        async def delete(self, agent_id): ...

    async with Registry(MyStore()) as registry:
        agent = await registry.register(payload)
        results = await registry.search(keyword="invoice")

Modules
-------
- ``models``        — Pydantic models: ``AgentAddr``, ``AgentAddrCreate``,
  ``AgentAddrUpdate``, ``AgentTier``, ``AgentRegistryBrief``
- ``store``         — ``AgentStore`` protocol (the interface backends implement)
- ``registry``      — ``Registry`` facade (async context manager wrapping any store)
- ``cloudsql_store``— ``CloudSQLAgentStore``: built-in Cloud SQL + pgvector backend
- ``embeddings``    — ``EmbeddingModel`` and ``build_agent_text`` for Vertex AI embeddings
- ``tools``         — ADK tools for registry search and remote agent invocation
"""

from giulia.registry.cloudsql_store import CloudSQLAgentStore  # noqa: F401
from giulia.registry.embeddings import EmbeddingModel, build_agent_text  # noqa: F401
from giulia.registry.models import (  # noqa: F401
    AgentAddr,
    AgentAddrCreate,
    AgentAddrUpdate,
    AgentRegistryBrief,
    AgentTier,
)
from giulia.registry.registry import Registry  # noqa: F401
from giulia.registry.store import AgentStore  # noqa: F401
from giulia.registry.tools import (  # noqa: F401
    get_registered_agent,
    make_dispatch_agent_tool,
    make_invoke_registered_agent_tool,
    search_agents_in_registry,
)

__all__ = [
    "Registry",
    # Storage protocol
    "AgentStore",
    # Built-in backends
    "CloudSQLAgentStore",
    # Embeddings
    "EmbeddingModel",
    "build_agent_text",
    # Models
    "AgentTier",
    "AgentAddr",
    "AgentAddrCreate",
    "AgentAddrUpdate",
    "AgentRegistryBrief",
    # ADK tools
    "get_registered_agent",
    "make_dispatch_agent_tool",
    "make_invoke_registered_agent_tool",
    "search_agents_in_registry",
]
