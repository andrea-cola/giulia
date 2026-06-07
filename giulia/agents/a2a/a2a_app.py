"""Datwave A2A app factory — ADK ``to_a2a`` with push notifications enabled.

ADK's ``to_a2a`` creates ``InMemoryPushNotificationConfigStore`` but does not wire
``BasePushNotificationSender``, so task updates are never POSTed to callback URLs.
This module mirrors the ADK setup and adds the sender.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
    PushNotificationConfigStore,
)
from a2a.types import AgentCard
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder
from google.adk.a2a.utils.agent_to_a2a import _load_agent_card
from google.adk.agents.base_agent import BaseAgent
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.auth.credential_service.in_memory_credential_service import (
    InMemoryCredentialService,
)
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from starlette.applications import Starlette

logger = logging.getLogger(__name__)

_push_http_client: httpx.AsyncClient | None = None


def _get_push_http_client() -> httpx.AsyncClient:
    global _push_http_client
    if _push_http_client is None:
        _push_http_client = httpx.AsyncClient(timeout=30.0)
    return _push_http_client


async def close_push_http_client() -> None:
    global _push_http_client
    if _push_http_client is not None:
        await _push_http_client.aclose()
        _push_http_client = None


def to_a2a_giulia(
    agent: BaseAgent,
    *,
    host: str = "localhost",
    port: int = 8000,
    protocol: str = "http",
    agent_card: AgentCard | str | None = None,
    push_config_store: PushNotificationConfigStore | None = None,
    runner: Runner | None = None,
    lifespan: Callable[[Starlette], AsyncIterator[None]] | None = None,
) -> Starlette:
    """Build a Starlette A2A app with in-memory push config store and sender."""
    adk_logger = logging.getLogger("google_adk")
    adk_logger.setLevel(logging.INFO)

    async def create_runner() -> Runner:
        return Runner(
            app_name=agent.name or "adk_agent",
            agent=agent,
            artifact_service=InMemoryArtifactService(),
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
            credential_service=InMemoryCredentialService(),
        )

    task_store = InMemoryTaskStore()
    agent_executor = A2aAgentExecutor(runner=runner or create_runner)

    if push_config_store is None:
        push_config_store = InMemoryPushNotificationConfigStore()

    push_sender = BasePushNotificationSender(
        httpx_client=_get_push_http_client(),
        config_store=push_config_store,
    )

    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor,
        task_store=task_store,
        push_config_store=push_config_store,
        push_sender=push_sender,
    )

    rpc_url = f"{protocol}://{host}:{port}/"
    provided_agent_card = _load_agent_card(agent_card)
    card_builder = AgentCardBuilder(agent=agent, rpc_url=rpc_url)

    async def setup_a2a(app: Starlette) -> None:
        if provided_agent_card is not None:
            final_agent_card = provided_agent_card
        else:
            final_agent_card = await card_builder.build()

        a2a_app = A2AStarletteApplication(
            agent_card=final_agent_card,
            http_handler=request_handler,
        )
        a2a_app.add_routes_to_app(app)

    @asynccontextmanager
    async def _combined_lifespan(app: Starlette) -> AsyncIterator[None]:
        await setup_a2a(app)
        try:
            if lifespan:
                async with lifespan(app):
                    yield
            else:
                yield
        finally:
            await close_push_http_client()

    return Starlette(lifespan=_combined_lifespan)
