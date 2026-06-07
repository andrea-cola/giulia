"""Agent registry — discovery, resolution, and ADK tools.

Public surface:
  - ``discover_agents`` / ``resolve_agent`` / ``resolve_agent_base_url`` — lookup
  - ``search_agents_in_registry`` / ``get_registered_agent`` — ADK tools (registry search)
  - ``make_invoke_registered_agent_tool`` / ``make_dispatch_agent_tool`` — ADK tool factories (sync A2A)
  - ``AgentRegistryBrief`` — trimmed registry row model
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

from .models import AgentRegistryBrief  # noqa: F401

__all__ = [
    "AgentRegistryBrief",
    "discover_agents",
    "get_registered_agent",
    "make_dispatch_agent_tool",
    "make_invoke_registered_agent_tool",
    "resolve_agent",
    "resolve_agent_base_url",
    "search_agents_in_registry",
]
