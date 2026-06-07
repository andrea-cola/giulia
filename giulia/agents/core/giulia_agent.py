"""GiuliaAgent — unified wrapper for ADK agents with A2A + registry support.

Usage::

    from google.adk.agents import Agent
    from giulia.agents.core.giulia_agent import GiuliaAgent

    root_agent = Agent(name="sophia", ...)

    dw = GiuliaAgent(agent=root_agent, config_path="config.yaml")
    app = dw.create_app()
    # Run with: uvicorn module:app
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from a2a.types import AgentCard
from google.adk.agents import Agent
from google.adk.planners import BuiltInPlanner
from google.genai import types
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response

from giulia.agents.auth.crypto import (
    load_private_key_from_file,
    public_key_to_jwk,
    sign_agent_card,
)
from giulia.agents.middlewares import (
    ApiKeyMiddleware,
    RequestLoggingMiddleware,
    StripPrefixMiddleware,
)
from giulia.agents.registry_client import (
    agent_card_to_agentfacts,
    build_agent_card,
    register_private_agent,
    start_heartbeat,
)
from giulia.agents.registry_client.agentfacts import serve_agentfacts_endpoint
from giulia.logging import logger

from .config_schema import AgentYAMLConfig

DEFAULT_THINKING_CONFIG = types.ThinkingConfig(
    include_thoughts=True,
    thinking_level=types.ThinkingLevel.HIGH,
)


class GiuliaAgent:
    """Wrap an ADK ``Agent`` with A2A card generation, middleware, and registry hooks."""

    def __init__(
        self,
        agent: Agent,
        *,
        config: AgentYAMLConfig | None = None,
        config_path: str | Path | None = None,
        signing_key_path: str | None = None,
        public_signing_key_path: str | None = None,
        service_url: str | None = None,
        registry_url: str | None = None,
    ) -> None:
        self._apply_default_planner(agent)
        self.agent = agent
        self.signing_key_path = signing_key_path
        self.public_signing_key_path = public_signing_key_path
        self.service_url = service_url
        self.registry_url = registry_url

        if config is not None:
            self.config = config
        elif config_path is not None:
            self.config = self._load_config(config_path)
        else:
            raise ValueError("No config provided")

        self._card_dict = build_agent_card(self.config, self.agent)
        self._card = AgentCard(**self._card_dict)

    @staticmethod
    def _apply_default_planner(agent: Agent) -> None:
        """Inject default thinking planner if agent has no planner configured."""
        if agent.planner is None:
            agent.planner = BuiltInPlanner(thinking_config=DEFAULT_THINKING_CONFIG)

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config(path: str | Path) -> AgentYAMLConfig:
        raw = yaml.safe_load(Path(path).read_text())
        return AgentYAMLConfig(**raw.get("agent", raw))

    @property
    def public_url(self) -> str:
        return self.config.public_url

    @property
    def path_prefix(self) -> str:
        return self.config.path_prefix

    def get_agent_card(self) -> dict[str, Any]:
        return self._card_dict

    @property
    def _external_key_path(self) -> str | None:
        """Key path used for externally-visible signatures (AgentFacts, JWKS).

        Public-tier agents use the public signing key when available,
        falling back to the internal key.
        """
        if self.config.tier == "public" and self.public_signing_key_path:
            return self.public_signing_key_path
        return self.signing_key_path

    def _load_external_key(self):
        """Load the Ed25519 private key for external signatures."""
        key_path = self._external_key_path
        if not key_path:
            return None
        return load_private_key_from_file(key_path)

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    async def _agent_facts_handler(self, request: Request) -> Response:
        signing_key = None
        try:
            signing_key = self._load_external_key()
            if signing_key is None:
                logger.warning(
                    "No signing key available for AgentFacts, serving unsigned"
                )
        except Exception:
            logger.exception("Failed to load signing key for AgentFacts")

        host = request.headers.get("host", "")
        is_internal = ".svc.cluster.local" in host
        endpoint_url = (
            self.service_url if (is_internal and self.service_url) else self.public_url
        )

        if not endpoint_url:
            logger.error("No endpoint URL available for AgentFacts (host={})", host)

        card = {"url": endpoint_url, "description": self.agent.description}
        try:
            facts = agent_card_to_agentfacts(
                card,
                private_key=signing_key,
                agent_name=self.config.urn,
                handle=self.config.registry_handle,
                owner=self.config.owner_did,
                capabilities=self.config.capabilities,
                auth_method=self.config.auth.method,
                auth_jwks=self.config.auth.jwks,
                tier=self.config.tier,
                domain=self.config.domain,
                ttl=self.config.ttl,
            )
            return serve_agentfacts_endpoint(facts)
        except Exception:
            logger.exception("Failed to generate AgentFacts")
            return Response("Internal Server Error", status_code=500)

    async def _jwks_handler(self, request: Request) -> Response:
        """Serve the Ed25519 public key as a JWKS document (RFC 7517)."""
        from starlette.responses import JSONResponse

        try:
            private_key = self._load_external_key()
            if private_key is None:
                return JSONResponse({"keys": []})
            jwk = public_key_to_jwk(private_key.public_key())
            return JSONResponse({"keys": [jwk]})
        except Exception:
            logger.exception("Failed to build JWKS")
            return JSONResponse({"keys": []}, status_code=500)

    async def _signed_agent_card_handler(self, request: Request) -> Response:
        """Serve the A2A agent card with a JWS ``signatures`` array."""
        from starlette.responses import JSONResponse

        card = dict(self._card_dict)
        try:
            private_key = self._load_external_key()
            if private_key is not None:
                card = sign_agent_card(private_key, card)
        except Exception:
            logger.exception("Failed to sign agent card")

        return JSONResponse(card)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def _load_signing_key(self):
        """Load the Ed25519 private key used for registry signatures."""
        if self.signing_key_path:
            return load_private_key_from_file(self.signing_key_path)
        return None

    def _register(self) -> dict[str, Any] | None:
        payload = self.config.to_registration_payload(service_url=self.service_url)
        try:
            signing_key = self._load_signing_key()
            result = register_private_agent(payload, signing_key=signing_key)
            if result:
                logger.info("Agent registered: {}", result.get("agent_id"))
            else:
                logger.error("Registration returned empty result")
            return result
        except Exception as exc:
            logger.critical("Failed to register agent {}: {}", self.config.name, exc)
            return None

    # ------------------------------------------------------------------
    # App factory
    # ------------------------------------------------------------------

    @staticmethod
    def _inject_lifecycle_log_callbacks(agent: Agent, agent_urn: str | None) -> None:
        """No-op: lifecycle logging is handled entirely by handler.py.

        All running/completed/error rows are written by
        ``run_inbound_job_with_runner`` using IDs from the delegation job,
        which are stable and consistent across the whole workflow chain.

        ADK callbacks (before_agent_callback / after_agent_callback) use
        session IDs managed internally by ADK which differ from the
        session_id we propagate — using them would produce rows
        with mismatched session_ids that break the chain correlation.
        """

    def create_app(
        self,
        additional_lifespan: Callable[[Starlette], AbstractAsyncContextManager[None]]
        | None = None,
        *,
        runner: Any | None = None,
    ) -> Starlette:
        """Create a fully-configured Starlette app.

        Includes A2A routes, agent-facts endpoint, API-key middleware,
        path-prefix stripping, and registry registration on startup.

        Args:
            additional_lifespan: Optional Starlette lifespan merged after registry startup.
            runner: Optional pre-built ADK ``Runner`` (shared session service). When set,
                passed to ``to_a2a`` so external handlers (e.g. webhooks) can resume the
                same sessions as A2A requests.
        """
        from giulia.agents.a2a import to_a2a_giulia

        self._inject_lifecycle_log_callbacks(self.agent, self.config.urn)
        wrapper = self

        @asynccontextmanager
        async def lifespan(app: Starlette) -> AsyncIterator[None]:
            from giulia.agents.orchestration.heartbeat_db import record_heartbeat

            logger.info("Starting GiuliaAgent: {}", wrapper.config.name)
            logger.info("Public URL: {}", wrapper.public_url)
            logger.info("Service URL: {}", wrapper.service_url)

            heartbeat_task = None
            wrapper._register()
            payload = wrapper.config.to_registration_payload(
                service_url=wrapper.service_url,
            )
            signing_key = wrapper._load_signing_key()

            tier_value = wrapper.config.tier
            if hasattr(tier_value, "value"):
                tier_value = tier_value.value

            await record_heartbeat(
                agent_id=wrapper.config.urn,
                agent_name=wrapper.config.name,
                company=wrapper.config.company,
                service_url=wrapper.service_url,
                public_url=wrapper.public_url,
                tier=tier_value,
                region=payload.get("region"),
                ttl_seconds=wrapper.config.ttl,
            )
            logger.info("Initial heartbeat recorded in database")

            heartbeat_task = start_heartbeat(payload, signing_key=signing_key)
            logger.info(
                "Heartbeat started (re-register every {:.0f}s, TTL {}s)",
                wrapper.config.ttl * 0.7,
                wrapper.config.ttl,
            )

            try:
                if additional_lifespan:
                    async with additional_lifespan(app):
                        yield
                else:
                    yield
            finally:
                if heartbeat_task:
                    heartbeat_task.cancel()
                    logger.info("Heartbeat stopped for {}", wrapper.config.name)

                # Close the shared database pool on shutdown
                from giulia.sql import get_db_client

                await get_db_client().close()

        a2a_kwargs: dict[str, Any] = dict(
            agent=self.agent,
            agent_card=self._card,
            lifespan=lifespan,
        )
        if runner is not None:
            a2a_kwargs["runner"] = runner
        app: Starlette = to_a2a_giulia(**a2a_kwargs)

        app.add_middleware(RequestLoggingMiddleware)
        app.add_middleware(ApiKeyMiddleware)
        app.add_middleware(StripPrefixMiddleware, prefix=self.path_prefix)
        app.add_route(
            "/.well-known/agent-card.json",
            self._signed_agent_card_handler,
            methods=["GET"],
        )
        app.add_route(
            "/.well-known/agent-facts",
            self._agent_facts_handler,
            methods=["GET"],
        )
        app.add_route(
            "/.well-known/jwks.json",
            self._jwks_handler,
            methods=["GET"],
        )

        return app

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @classmethod
    def from_config_file(
        cls,
        agent: Agent,
        config_path: str | Path = "config.yaml",
        **kwargs: Any,
    ) -> GiuliaAgent:
        """Short-hand: create a GiuliaAgent from a YAML config file."""
        return cls(agent=agent, config_path=config_path, **kwargs)
