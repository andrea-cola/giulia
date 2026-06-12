"""ADK tool factory for fire-and-forget inter-agent delegation."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import httpx
from google.adk.tools.tool_context import ToolContext

from giulia.agents.delegation.handler import submit_inbound_delegation
from giulia.agents.orchestration.activity_log import log_event
from giulia.agents.orchestration.adk import get_giulia_context
from giulia.logging import logger


def make_delegate_registered_agent_tool(
    httpx_client: httpx.AsyncClient | Callable[[], httpx.AsyncClient] | None = None,
    *,
    target_agent_id: str | None = None,
    source_agent_id: str | None = None,
    tool_name: str | None = None,
    tool_description: str | None = None,
) -> Callable[..., Awaitable[str]]:
    """Build an ADK tool that submits work to a target agent's inbound queue.

    Args:
        httpx_client: An AsyncClient or a factory. If None, uses the default A2A client factory.
        target_agent_id: Optional fixed URN for the target agent. If set, the LLM
            won't be asked for an agent_id.
        source_agent_id: URN of the agent creating the tool (for logging).
        tool_name: Custom name for the tool.
        tool_description: Custom description for the tool.
    """
    from giulia.agents.a2a.a2a_agent_factory import get_a2a_client_factory

    client_factory = httpx_client or get_a2a_client_factory()

    async def delegate_tool(
        tool_context: ToolContext,
        *,
        request: str,
        agent_id: str | None = None,
    ) -> str:
        aid = (target_agent_id or agent_id or "").strip()
        req = (request or "").strip()

        if not aid:
            return json.dumps(
                {"status": "invalid", "message": "Missing target agent_id."}
            )
        if not req:
            return json.dumps({"status": "invalid", "message": "Missing request text."})

        import uuid

        ctx = get_giulia_context(tool_context)
        new_invocation_id = f"e-{uuid.uuid4()}"

        owns_client = False
        client: httpx.AsyncClient
        if isinstance(client_factory, httpx.AsyncClient):
            client = client_factory
        else:
            client = client_factory()
            owns_client = True

        await log_event(
            invocation_id=new_invocation_id,
            session_id=ctx.session_id,
            status="dispatching",
            source_agent_id=source_agent_id,
            source_app_name=ctx.app_name,
            process_id=ctx.process_id,
            parent_delegation_id=ctx.invocation_id,
            target_agent_id=aid,
            request=req,
        )

        status = "error"
        error_message: str | None = None
        try:
            await submit_inbound_delegation(
                target_agent_id=aid,
                request=req,
                invocation_id=new_invocation_id,
                session_id=ctx.session_id,
                source_agent_id=source_agent_id,
                source_app_name=ctx.app_name,
                process_id=ctx.process_id,
                parent_delegation_id=ctx.invocation_id,
                httpx_client=client,
            )
            status = "completed"
        except Exception as exc:
            error_message = str(exc)
            logger.warning(
                "delegate_tool: inbound POST failed for {} — agent may not be running locally ({})",
                aid,
                exc,
            )
            return json.dumps(
                {"status": "error", "message": error_message, "agent_id": aid}
            )
        finally:
            await log_event(
                invocation_id=new_invocation_id,
                session_id=ctx.session_id,
                status=status,
                source_agent_id=source_agent_id,
                source_app_name=ctx.app_name,
                process_id=ctx.process_id,
                parent_delegation_id=ctx.invocation_id,
                target_agent_id=aid,
                error_message=error_message,
            )
            if owns_client:
                await client.aclose()

        return json.dumps(
            {
                "status": "success",
                "agent_id": aid,
                "invocation_id": new_invocation_id,
            }
        )

    # Set metadata for ADK
    delegate_tool.__name__ = tool_name or (
        "delegate_work"
        if not target_agent_id
        else f"invoke_{target_agent_id.split(':')[-1].replace('-', '_')}"
    )
    delegate_tool.__doc__ = tool_description or (
        "Delegate work to a registered agent asynchronously."
        if not target_agent_id
        else f"Send a request to the {target_agent_id} agent. Continue with other tasks immediately."
    )

    return delegate_tool
