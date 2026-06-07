"""Pydantic shapes for registry data exposed to ADK tools (trimmed payloads)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field


class AgentRegistryBrief(BaseModel):
    """Subset of a registry ``AgentAddr`` JSON row returned to the model."""

    model_config = ConfigDict(extra="ignore")

    agent_id: str | None = None
    agent_name: str | None = None
    description: str | None = None
    company: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    primary_facts_url: str | None = None
    private_facts_url: str | None = None
    tier: str | None = None
    region: str | None = None
    protocol: str | None = None

    @classmethod
    def from_registry_row(cls, raw: Mapping[str, Any]) -> Self:
        caps = raw.get("capabilities")
        if caps is None:
            caps_list: list[str] = []
        elif isinstance(caps, list):
            caps_list = [str(x) for x in caps]
        else:
            caps_list = [str(caps)]
        return cls(
            agent_id=raw.get("agent_id"),
            agent_name=raw.get("agent_name"),
            description=raw.get("description"),
            company=raw.get("company"),
            capabilities=caps_list,
            primary_facts_url=raw.get("primary_facts_url"),
            private_facts_url=raw.get("private_facts_url"),
            tier=_tier_str(raw.get("tier")),
            region=raw.get("region"),
            protocol=raw.get("protocol"),
        )


def _tier_str(tier: Any) -> str | None:
    if tier is None:
        return None
    if isinstance(tier, str):
        return tier
    return getattr(tier, "value", str(tier))
