"""A2A-enabled Giulia agent template.

This template wires up a Google ADK agent with:
- A2A protocol (agent-to-agent communication)
- Delegation (call downstream agents)
- Push notifications
- Custom lifespan hook

Run with:

    uvicorn agent:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from giulia.agents.core.giulia_agent import GiuliaAgent
from giulia.agents.delegation.tools import make_delegation_tools
from giulia.logging import logger
from google.adk.agents import Agent
from starlette.applications import Starlette

root_agent = Agent(
    name="my-a2a-agent",
    model="gemini-2.5-pro",
    description="An A2A-capable Giulia agent.",
    instruction=(
        "You are a helpful assistant that can delegate tasks to other agents. "
        "Use the available tools to collaborate with specialist agents."
    ),
    tools=make_delegation_tools(),
)

dw = GiuliaAgent(
    agent=root_agent,
    config_path="config.yaml",
)


@asynccontextmanager
async def custom_lifespan(app: Starlette) -> AsyncIterator[None]:
    logger.info("Custom startup hook running")
    yield
    logger.info("Custom shutdown hook running")


app = dw.create_app(additional_lifespan=custom_lifespan)
