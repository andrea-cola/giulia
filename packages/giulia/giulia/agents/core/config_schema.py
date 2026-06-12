"""Unified agent configuration schema.

A single config.yaml drives both registry registration
and A2A agent-card generation.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentTier(str, Enum):
    PRIVATE = "private"
    PUBLIC = "public"


class ProviderConfig(BaseModel):
    organization: str
    url: str


class OAuthFlow(BaseModel):
    authorizationUrl: str | None = None
    tokenUrl: str
    scopes: dict[str, str] = Field(default_factory=dict)


class SecurityScheme(BaseModel):
    type: str = "oauth2"
    flows: dict[str, OAuthFlow] = Field(default_factory=dict)


class AuthConfig(BaseModel):
    """AgentFacts ``auth`` block — how callers authenticate."""

    method: str = "oidc"
    jwks: str | None = None


class A2AConfig(BaseModel):
    """A2A protocol metadata that goes into the agent card."""

    version: str = "1.0.0"
    protocolVersion: str = "1.0"
    streaming: bool = False
    pushNotifications: bool = False
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    securitySchemes: dict[str, SecurityScheme] = Field(default_factory=dict)
    security: list[dict[str, list[str]]] = Field(default_factory=list)


class AgentYAMLConfig(BaseModel):
    """Parsed representation of the ``agent:`` block in ``config.yaml``."""

    name: str
    description: str | None = None

    # Registry identity
    handle: str | None = None
    owner: str | None = None

    # Deployment
    port: int = 8001
    tier: AgentTier = AgentTier.PRIVATE
    company: str
    domain: str
    ttl: int = 3600

    # Capabilities advertised to the registry (URN format preferred)
    capabilities: list[str] = Field(default_factory=list)

    # Authentication config for AgentFacts
    auth: AuthConfig = Field(default_factory=AuthConfig)

    # A2A card extras
    a2a: A2AConfig = Field(default_factory=A2AConfig)

    @property
    def urn(self) -> str:
        return f"urn:agent:{self.company.lower()}:{self.tier.value.lower()}:{self.name}"

    @property
    def public_url(self) -> str:
        return f"https://{self.domain}/agents/{self.name}"

    @property
    def path_prefix(self) -> str:
        return f"/agents/{self.name}"

    @property
    def registry_handle(self) -> str:
        """Registry handle in ``@namespace:tier/agent`` form."""
        if self.handle:
            return self.handle
        return f"@{self.company.lower()}:{self.tier.value}/{self.name}"

    @property
    def owner_did(self) -> str:
        if self.owner:
            return self.owner
        return f"did:org:{self.company.lower()}"

    def to_registration_payload(
        self,
        *,
        service_url: str | None = None,
    ) -> dict[str, Any]:
        """Build the dict consumed by ``register_private_agent``."""
        payload: dict[str, Any] = {
            "urn": self.urn,
            "name": self.name,
            "handle": self.registry_handle,
            "owner": self.owner_did,
            "description": self.description,
            "company": self.company,
            "capabilities": self.capabilities,
            "ttl": self.ttl,
            "tier": self.tier,
            "domain": self.domain,
            "public_url": self.public_url,
        }
        if service_url:
            payload["k8s_service_url"] = service_url
        return payload
