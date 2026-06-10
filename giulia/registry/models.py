"""Pydantic models for the agent registry.

These are the canonical data shapes shared between the registry service
and every giulia-based agent.  Import them from here (or from
``giulia.registry``) — never redefine them locally.

Overview
--------

=========================================================  =============================================
Model                                                      Purpose
=========================================================  =============================================
:class:`AgentTier`                                         Enum: ``private`` or ``public``
:class:`AgentAddr`                                         Full registry record for a registered agent
:class:`AgentAddrCreate`                                   Registration payload (sent by agents at startup)
:class:`AgentAddrUpdate`                                   Partial-update payload (PATCH semantics)
:class:`AgentRegistryBrief`                                Trimmed projection returned to ADK tool callers
=========================================================  =============================================
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
    """Visibility tier of an agent in the registry."""

    PRIVATE = "private"
    """Only visible within the same organisation / namespace."""

    PUBLIC = "public"
    """Discoverable by any authenticated caller."""


class AgentAddr(BaseModel):
    """Full registry record for a registered agent.

    This is the primary model persisted by every :class:`AgentStore`
    backend.  It carries identity, network endpoints, capabilities, and
    lifecycle timestamps.

    Fields
    ------
    agent_id : str
        URN identifier (e.g. ``urn:agent:acme:private:billing``).
        Serves as the primary key in every store.
    agent_name : str
        Human-readable short name (e.g. ``"billing"``).
    description : str | None
        One-liner describing what the agent does.
    company : str | None
        Organisation that owns the agent.
    primary_facts_url : str
        Public ``/.well-known/agent-facts`` endpoint.
    private_facts_url : str | None
        Internal (in-cluster) ``/.well-known/agent-facts`` endpoint.
    adaptive_resolver_url : str | None
        Optional adaptive-resolver endpoint for dynamic routing.
    ttl : int
        Time-to-live in seconds.  If no heartbeat arrives within this
        window the agent is considered stale.  Default: 900 (15 min).
    signature : str
        Ed25519 signature over the record fields (integrity proof).
    registered_at : datetime
        Timestamp of first registration (set once, never overwritten).
    last_update : datetime
        Timestamp of the most recent upsert.
    capabilities : list[str]
        Capability URNs the agent advertises
        (e.g. ``["urn:cap:billing", "urn:cap:invoicing"]``).
    protocol : str
        Wire protocol.  Default ``"a2a"`` (Agent-to-Agent).
    tier : AgentTier
        Visibility tier.  Default :attr:`AgentTier.PRIVATE`.
    region : str | None
        Deployment region (e.g. ``"europe-west1"``).
    """

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
    """Registration payload sent by agents at startup.

    Contains all the fields an agent supplies when calling
    ``POST /registry/api/v1/agents``.  The server fills in
    ``registered_at`` and ``last_update`` automatically.
    """

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
    """Partial-update payload (PATCH semantics).

    Only non-``None`` fields are applied to the existing record.
    Typically used with ``PUT /registry/api/v1/agents/{agent_id}``.
    """

    primary_facts_url: str | None = None
    ttl: int | None = None
    signature: str | None = None
    capabilities: list[str] | None = None
    region: str | None = None


# ---------------------------------------------------------------------------
# Trimmed projection used by ADK tools
# ---------------------------------------------------------------------------


class AgentRegistryBrief(BaseModel):
    """Lightweight projection of an :class:`AgentAddr` for ADK tool responses.

    Strips timestamps, TTL, and signatures — keeps only the fields that
    are useful for the LLM to decide which agent to invoke.
    """

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
        """Build a brief from a fully-typed :class:`AgentAddr`."""
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
        """Build a brief from a raw registry dict or a typed :class:`AgentAddr`.

        Useful when working with raw HTTP responses from the registry API
        (which return plain dicts) as well as typed model instances.
        """
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
