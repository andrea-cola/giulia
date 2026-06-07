"""ADK tool factory for A2A fire-and-forget with push notifications."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from uuid import uuid4

import httpx
from google.adk.tools.tool_context import ToolContext

from giulia.agents.orchestration.activity_log import log_event
from giulia.agents.push_notifications.client import send_a2a_with_push
from giulia.logging import logger


def _invocation_id(tool_context: ToolContext) -> str | None:
    try:
        inv_id = tool_context._invocation_context.invocation_id  # noqa: SLF001
        return str(inv_id).strip() if inv_id else None
    except AttributeError:
        return None


def _session_id(tool_context: ToolContext) -> str | None:
    try:
        state = tool_context._invocation_context.session.state  # noqa: SLF001
        dw_sid = (state or {}).get("_dw_session_id")
        if dw_sid:
            return str(dw_sid).strip()
    except AttributeError:
        pass
    try:
        sid = tool_context._invocation_context.session.id  # noqa: SLF001
        return str(sid).strip() if sid else None
    except AttributeError:
        return None


def _app_name(tool_context: ToolContext) -> str | None:
    try:
        name = tool_context._invocation_context.app_name  # noqa: SLF001
        return str(name).strip() if name else None
    except AttributeError:
        return None


def make_push_delegate_registered_agent_tool(
    httpx_client: httpx.AsyncClient | Callable[[], httpx.AsyncClient] | None = None,
    *,
    target_agent_id: str | None = None,
    source_agent_id: str | None = None,
    tool_name: str | None = None,
    tool_description: str | None = None,
) -> Callable[..., Awaitable[str]]:
    """Build an ADK tool that dispatches via A2A push (non-blocking ``message/send``)."""
    from giulia.agents.a2a.a2a_agent_factory import get_a2a_client_factory

    client_factory = httpx_client or get_a2a_client_factory()

    async def push_delegate_tool(
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

        inv_id = _invocation_id(tool_context) or uuid4().hex
        sess_id = _session_id(tool_context) or inv_id
        app_name = _app_name(tool_context)

        owns_client = False
        client: httpx.AsyncClient
        if isinstance(client_factory, httpx.AsyncClient):
            client = client_factory
        else:
            client = client_factory()
            owns_client = True

        status = "dispatching"
        error_message: str | None = None

        await log_event(
            invocation_id=inv_id,
            session_id=sess_id,
            status=status,
            source_agent_id=source_agent_id,
            source_app_name=app_name,
            target_agent_id=aid,
            request=req,
        )

        try:
            result = await send_a2a_with_push(
                target_agent_id=aid,
                request_text=req,
                httpx_client=client,
                context_id=sess_id,
            )
            status = "delegated"
            error_message = None
        except Exception as exc:
            logger.exception("push_delegate_tool failed for %s", aid)
            status = "error"
            error_message = str(exc)
            return json.dumps(
                {"status": "error", "message": error_message, "agent_id": aid}
            )
        finally:
            await log_event(
                invocation_id=inv_id,
                session_id=sess_id,
                status=status,
                source_agent_id=source_agent_id,
                source_app_name=app_name,
                target_agent_id=aid,
                error_message=error_message,
            )
            if owns_client:
                await client.aclose()

        result["invocation_id"] = inv_id
        result["session_id"] = sess_id
        result["message"] = (
            "Task submitted via A2A push. Result will arrive at this agent's "
            "push callback URL when the remote agent completes."
        )
        return json.dumps(result)

    push_delegate_tool.__name__ = tool_name or (
        "push_delegate_work"
        if not target_agent_id
        else f"push_invoke_{target_agent_id.split(':')[-1].replace('-', '_')}"
    )
    push_delegate_tool.__doc__ = tool_description or (
        "Delegate work to a registered agent via A2A push notifications (non-blocking). "
        "The remote agent POSTs the completed task to this agent's callback URL."
        if not target_agent_id
        else (
            f"Send a request to {target_agent_id} via A2A push. "
            "Continue immediately; the answer arrives asynchronously via push."
        )
    )
    return push_delegate_tool
