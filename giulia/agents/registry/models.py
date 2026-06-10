"""Pydantic models for the agent registry.

Canonical shapes (AgentAddr, AgentTier, AgentAddrCreate, AgentAddrUpdate) are
defined here so that both the registry service and any giulia-based consumer
share the same types without a circular dependency.

AgentRegistryBrief is a trimmed read-only projection used by ADK tools.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Canonical registry record types
# ---------------------------------------------------------------------------


class AgentTier(StrEnum):
    PRIVATE = "private"
    PUBLIC = "public"


class AgentAddr(BaseModel):
    """Full registry record for a registered agent."""

    agent_id: str = Field(
        ..., description="URN identifier, e.g. urn:agent:acme:private:inventory"
    )
    agent_name: str = Field(
        ..., description="Human-readable agent name, e.g. inventory"
    )
    description: str | None = Field(
        default=None, description="Short description of what the agent does"
    )
    company: str | None = Field(default=None, description="Company that owns the agent")
    primary_facts_url: str = Field(..., description="URL to /.well-known/agent-facts")
    private_facts_url: str | None = None
    adaptive_resolver_url: str | None = None
    ttl: int = Field(default=900, description="Time-to-live in seconds")
    signature: str = Field(
        default="", description="Ed25519 signature over the record fields"
    )
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_update: datetime = Field(default_factory=lambda: datetime.now(UTC))
    capabilities: list[str] = Field(default_factory=list)
    protocol: str = "a2a"
    tier: AgentTier = AgentTier.PRIVATE
    region: str | None = None


class AgentAddrCreate(BaseModel):
    """Payload for registering a new agent."""

    agent_id: str = Field(
        ..., description="URN identifier, e.g. urn:agent:acme:private:inventory"
    )
    agent_name: str = Field(..., description="Human-readable agent name")
    description: str | None = None
    company: str | None = None
    primary_facts_url: str
    private_facts_url: str | None = None
    adaptive_resolver_url: str | None = None
    ttl: int = 900
    signature: str = ""
    capabilities: list[str] = Field(default_factory=list)
    protocol: str = "a2a"
    tier: AgentTier = AgentTier.PRIVATE
    region: str | None = None


class AgentAddrUpdate(BaseModel):
    """Partial-update payload for an existing agent record."""

    primary_facts_url: str | None = None
    ttl: int | None = None
    signature: str | None = None
    capabilities: list[str] | None = None
    region: str | None = None


# ---------------------------------------------------------------------------
# Trimmed projection used by ADK tools
# ---------------------------------------------------------------------------


class AgentRegistryBrief(BaseModel):
    """Subset of a registry ``AgentAddr`` row returned to the model."""

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
    def from_agent_addr(cls, agent: AgentAddr) -> Self:
        """Build a brief from a fully-typed ``AgentAddr``."""
        return cls(
            agent_id=agent.agent_id,
            agent_name=agent.agent_name,
            description=agent.description,
            company=agent.company,
            capabilities=list(agent.capabilities),
            primary_facts_url=agent.primary_facts_url,
            private_facts_url=agent.private_facts_url,
            tier=_tier_str(agent.tier),
            region=agent.region,
            protocol=agent.protocol,
        )

    @classmethod
    def from_registry_row(cls, raw: Mapping[str, Any] | AgentAddr) -> Self:
        """Build a brief from a raw registry dict or a typed ``AgentAddr``."""
        if isinstance(raw, AgentAddr):
            return cls.from_agent_addr(raw)
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
