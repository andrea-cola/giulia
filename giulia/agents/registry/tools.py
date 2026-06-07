"""ADK tools for registry search and synchronous A2A agent invocation."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import cast

import httpx
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.tool_context import ToolContext

from giulia.agents.a2a.a2a_agent_factory import remote_a2a_agent_from_registry
from giulia.agents.registry_client.discovery import discover_agents, resolve_agent
from giulia.logging import logger

from .models import AgentRegistryBrief


def _blank_to_none(value: str) -> str | None:
    v = (value or "").strip()
    return v or None


async def search_agents_in_registry(
    tool_context: ToolContext,
    *,
    keyword: str = "",
    capability: str = "",
    region: str = "",
    tier: str = "",
) -> str:
    """Search the internal agent registry.

    When *keyword* is non-empty, search is semantic (natural language / meaning)
    over registered name, description, company, and capability URNs.

    Use *capability* for exact capability-URN filtering (can be combined with
    *keyword*). *region* and *tier* narrow results when set.
    """
    _ = tool_context
    kw = _blank_to_none(keyword)
    cap = _blank_to_none(capability)
    reg = _blank_to_none(region)
    tr = _blank_to_none(tier)
    if not kw and not cap:
        return json.dumps(
            {
                "status": "invalid",
                "message": "Provide at least `keyword` (semantic search) or "
                "`capability` (exact URN filter).",
            }
        )
    try:
        raw_list = await discover_agents(
            capability=cap, region=reg, tier=tr, keyword=kw
        )
    except Exception:
        logger.exception("search_agents_in_registry failed")
        return json.dumps(
            {"status": "error", "message": "Registry search failed; try again later."}
        )
    briefs = [
        AgentRegistryBrief.from_registry_row(a).model_dump(mode="json")
        for a in raw_list
        if isinstance(a, dict)
    ]
    return json.dumps({"status": "ok", "count": len(briefs), "agents": briefs})


async def get_registered_agent(agent_id: str, tool_context: ToolContext) -> str:
    """Look up one agent in the registry by full URN (*agent_id*)."""
    _ = tool_context
    aid = (agent_id or "").strip()
    if not aid:
        return json.dumps(
            {"status": "invalid", "message": "`agent_id` (URN) is required."}
        )
    try:
        raw = await resolve_agent(aid)
    except Exception:
        logger.exception("get_registered_agent failed for %s", aid)
        return json.dumps(
            {"status": "error", "message": "Registry lookup failed; try again later."}
        )
    if raw is None:
        return json.dumps({"status": "not_found", "agent_id": aid})
    return json.dumps(
        {
            "status": "ok",
            "agent": AgentRegistryBrief.from_registry_row(raw).model_dump(mode="json"),
        }
    )


async def _run_remote_agent(
    aid: str,
    req: str,
    httpx_client: httpx.AsyncClient | Callable[[], httpx.AsyncClient],
    tool_context: ToolContext,
    *,
    skip_summarization: bool = True,
    caller: str = "run_remote_agent",
) -> str:
    owns_client = False
    client: httpx.AsyncClient
    if isinstance(httpx_client, httpx.AsyncClient):
        client = httpx_client
    else:
        client = cast("Callable[[], httpx.AsyncClient]", httpx_client)()
        owns_client = True

    try:
        try:
            remote = await remote_a2a_agent_from_registry(aid, client)
        except Exception:
            logger.exception("%s: resolve/materialize failed for %s", caller, aid)
            return json.dumps(
                {
                    "status": "error",
                    "message": f"Could not resolve agent {aid} from the registry.",
                    "agent_id": aid,
                }
            )

        agent_tool = AgentTool(agent=remote, skip_summarization=skip_summarization)
        try:
            out = await agent_tool.run_async(
                args={"request": req}, tool_context=tool_context
            )
        except Exception:
            logger.exception("%s: remote run failed for %s", caller, aid)
            return json.dumps(
                {
                    "status": "error",
                    "message": "Remote agent call failed.",
                    "agent_id": aid,
                }
            )

        if hasattr(out, "model_dump"):
            text = out.model_dump(mode="json")
        elif isinstance(out, str):
            text = out
        else:
            text = str(out)

        return json.dumps({"status": "ok", "agent_id": aid, "response": text})
    finally:
        if owns_client:
            await client.aclose()


def make_dispatch_agent_tool(
    agent_urn: str,
    httpx_client: httpx.AsyncClient | Callable[[], httpx.AsyncClient],
    *,
    tool_name: str | None = None,
    tool_description: str | None = None,
    skip_summarization: bool = True,
) -> Callable[..., Awaitable[str]]:
    """Build a dedicated ADK tool that dispatches to one fixed registered agent.

    Binds ``agent_urn`` at creation time so Gemini only needs to supply ``request``.
    """
    urn_tail = agent_urn.rsplit(":", 1)[-1].replace("-", "_")
    fname = tool_name or f"invoke_{urn_tail}"
    fdesc = tool_description or (
        f"Run a single request against the registered agent "
        f"``{agent_urn}``. Pass the task or question in *request*."
    )

    async def _dispatch(tool_context: ToolContext, *, request: str) -> str:
        req = (request or "").strip()
        if not req:
            return json.dumps(
                {"status": "invalid", "message": "`request` is required."}
            )
        return await _run_remote_agent(
            agent_urn,
            req,
            httpx_client,
            tool_context,
            skip_summarization=skip_summarization,
            caller=fname,
        )

    _dispatch.__name__ = fname
    _dispatch.__qualname__ = fname
    _dispatch.__doc__ = fdesc
    return _dispatch


def make_invoke_registered_agent_tool(
    httpx_client: httpx.AsyncClient | Callable[[], httpx.AsyncClient],
) -> Callable[..., Awaitable[str]]:
    """Build an ADK tool that resolves any registry peer by URN and runs one A2A turn."""

    async def invoke_registered_agent(
        tool_context: ToolContext,
        *,
        agent_id: str,
        request: str,
    ) -> str:
        """Run a single request against a registered agent by full URN (*agent_id*).

        Use *agent_id* from ``search_agents_in_registry`` results or from the user.
        Pass the user's task or question in *request* (plain text).
        """
        aid = (agent_id or "").strip()
        req = (request or "").strip()
        if not aid or not req:
            return json.dumps(
                {
                    "status": "invalid",
                    "message": "Both `agent_id` (registry URN) and `request` are required.",
                }
            )
        return await _run_remote_agent(
            aid, req, httpx_client, tool_context, caller="invoke_registered_agent"
        )

    return invoke_registered_agent
