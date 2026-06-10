"""Giulia — agent framework for registry discovery, registration, A2A, and cryptographic identity."""

from __future__ import annotations

from typing import Any

__version__ = "0.1.0"

# Re-export configure() at the top level so users can write:
#   import giulia
#   giulia.configure(secrets=..., kms=..., redis_auth=..., database=...)
# Re-export the providers sub-package for convenient access:
#   giulia.providers.EnvSecretsProvider()
from giulia import providers  # noqa: E402
from giulia.providers.registry import configure


def __getattr__(name: str) -> Any:
    """Lazy-load common symbols for backward compatibility and performance."""
    # Logging (auto-configured on first access)
    if name == "logger":
        from .logging import logger

        return logger

    # Core
    if name == "GiuliaAgent":
        from .core.giulia_agent import GiuliaAgent

        return GiuliaAgent
    if name == "config":
        from .core.config import config

        return config
    if name == "Config":
        from .core.config import Config

        return Config
    if name == "AgentYAMLConfig":
        from .core.config_schema import AgentYAMLConfig

        return AgentYAMLConfig

    # Registry / Discovery
    if name == "discover_agents":
        from .registry_client.discovery import discover_agents

        return discover_agents
    if name == "resolve_agent":
        from .registry_client.discovery import resolve_agent

        return resolve_agent
    if name == "register_private_agent":
        from .registry_client.registration import register_private_agent

        return register_private_agent

    # Registry models & protocol
    if name == "AgentTier":
        from .agents.registry.models import AgentTier

        return AgentTier
    if name == "AgentAddr":
        from .agents.registry.models import AgentAddr

        return AgentAddr
    if name == "AgentAddrCreate":
        from .agents.registry.models import AgentAddrCreate

        return AgentAddrCreate
    if name == "AgentAddrUpdate":
        from .agents.registry.models import AgentAddrUpdate

        return AgentAddrUpdate
    if name == "AgentStore":
        from .agents.registry.agent_store import AgentStore

        return AgentStore

    # Utils
    if name == "urn_to_slug":
        from .utils.urn import urn_to_slug

        return urn_to_slug

    # Auth
    if name == "verify_jwt":
        from .auth.jwt_auth import verify_jwt

        return verify_jwt
    if name == "JWTValidationError":
        from .auth.jwt_auth import JWTValidationError

        return JWTValidationError

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "configure",
    "providers",
    "logger",
    "GiuliaAgent",
    "config",
    "Config",
    "AgentYAMLConfig",
    # Registry discovery
    "discover_agents",
    "resolve_agent",
    "register_private_agent",
    # Registry models & protocol
    "AgentTier",
    "AgentAddr",
    "AgentAddrCreate",
    "AgentAddrUpdate",
    "AgentStore",
    # Utils / auth
    "urn_to_slug",
    "verify_jwt",
    "JWTValidationError",
]
