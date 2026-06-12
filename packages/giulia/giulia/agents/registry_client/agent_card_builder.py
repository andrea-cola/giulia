"""Build an A2A agent card from an ADK agent and a unified config.

Skills are derived automatically from the agent's tool list and planner,
so the static ``.well-known/agent-card.json`` file is no longer needed.

Aligned with A2A protocol v1.0.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from google.adk.agents import Agent

    from ..core.config_schema import AgentYAMLConfig


def build_skills_from_agent(
    agent: Agent,
    agent_name: str,
) -> list[dict[str, Any]]:
    """Derive A2A ``skills`` entries from the ADK agent definition."""
    skills: list[dict[str, Any]] = [
        {
            "id": agent_name,
            "name": "model",
            "description": agent.description or "",
            "tags": ["llm"],
            "examples": [],
            "inputModes": ["text/plain"],
            "outputModes": ["text/plain"],
        }
    ]

    for tool in getattr(agent, "tools", None) or []:
        tool_name = getattr(tool, "__name__", str(tool))
        raw_doc = getattr(tool, "__doc__", "") or ""
        first_line = raw_doc.strip().split("\n", 1)[0]

        skills.append(
            {
                "id": f"{agent_name}-{tool_name}",
                "name": tool_name,
                "description": first_line,
                "tags": ["llm", "tools"],
            }
        )

    if getattr(agent, "planner", None):
        skills.append(
            {
                "id": f"{agent_name}-planner",
                "name": "planning",
                "description": "Can think about the tasks to do and make plans",
                "tags": ["llm", "planning"],
            }
        )

    return skills


def build_agent_card(
    cfg: AgentYAMLConfig,
    agent: Agent,
) -> dict[str, Any]:
    """Build a complete A2A agent-card dict from unified config + ADK agent."""
    description = cfg.description or agent.description or ""

    card: dict[str, Any] = {
        "name": cfg.name,
        "description": description,
        "url": cfg.public_url,
        "version": cfg.a2a.version,
        "protocolVersion": cfg.a2a.protocolVersion,
        "capabilities": {
            "streaming": cfg.a2a.streaming,
            "pushNotifications": cfg.a2a.pushNotifications,
        },
        "skills": build_skills_from_agent(agent, cfg.name),
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "provider": cfg.a2a.provider.model_dump(),
    }

    if cfg.a2a.securitySchemes:
        card["securitySchemes"] = {
            name: scheme.model_dump(exclude_none=True)
            for name, scheme in cfg.a2a.securitySchemes.items()
        }

    if cfg.a2a.security:
        card["security"] = cfg.a2a.security

    card["supportsAuthenticatedExtendedCard"] = True
    return card
