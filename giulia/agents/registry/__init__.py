"""Agent registry — models, storage protocol, discovery, and ADK tools.

Public surface:
  Models:
    - ``AgentTier`` — tier enum (private / public)
    - ``AgentAddr`` — canonical registry record
    - ``AgentAddrCreate`` — registration payload
    - ``AgentAddrUpdate`` — partial-update payload
    - ``AgentRegistryBrief`` — trimmed projection for ADK tools

  Storage:
    - ``AgentStore`` — backend-agnostic storage protocol

  Discovery:
    - ``discover_agents`` / ``resolve_agent`` / ``resolve_agent_base_url``

  ADK tools:
    - ``search_agents_in_registry`` / ``get_registered_agent``
    - ``make_invoke_registered_agent_tool`` / ``make_dispatch_agent_tool``
"""

from giulia.agents.a2a.a2a_agent_factory import resolve_agent_base_url  # noqa: F401
from giulia.agents.registry.tools import (  # noqa: F401
    get_registered_agent,
    make_dispatch_agent_tool,
    make_invoke_registered_agent_tool,
    search_agents_in_registry,
)
from giulia.agents.registry_client.discovery import (  # noqa: F401
    discover_agents,
    resolve_agent,
)

from .agent_store import AgentStore  # noqa: F401
from .models import (  # noqa: F401
    AgentAddr,
    AgentAddrCreate,
    AgentAddrUpdate,
    AgentRegistryBrief,
    AgentTier,
)

__all__ = [
    # Models
    "AgentTier",
    "AgentAddr",
    "AgentAddrCreate",
    "AgentAddrUpdate",
    "AgentRegistryBrief",
    # Storage protocol
    "AgentStore",
    # Discovery
    "discover_agents",
    "resolve_agent",
    "resolve_agent_base_url",
    # ADK tools
    "get_registered_agent",
    "make_dispatch_agent_tool",
    "make_invoke_registered_agent_tool",
    "search_agents_in_registry",
]
