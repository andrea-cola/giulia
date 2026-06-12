"""Minimal Giulia agent template.

Copy this directory as a starting point, rename the class and config,
then run with:

    uvicorn agent:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

from giulia.agents.core.giulia_agent import GiuliaAgent
from google.adk.agents import Agent

root_agent = Agent(
    name="my-agent",
    model="gemini-2.5-pro",
    description="A minimal Giulia agent.",
    instruction="You are a helpful assistant.",
)

dw = GiuliaAgent(
    agent=root_agent,
    config_path="config.yaml",
)

app = dw.create_app()
