"""Giulia — agent framework for registry discovery, registration, A2A, and cryptographic identity."""

from __future__ import annotations

__version__ = "0.1.0"


# Lazy-load common symbols for backward compatibility and performance
def __getattr__(name: str):
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
    "GiuliaAgent",
    "config",
    "Config",
    "AgentYAMLConfig",
    "discover_agents",
    "resolve_agent",
    "register_private_agent",
    "urn_to_slug",
    "verify_jwt",
    "JWTValidationError",
]
