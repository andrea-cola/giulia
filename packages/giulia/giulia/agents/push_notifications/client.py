"""Send A2A ``message/send`` with non-blocking mode and push notification config."""

from __future__ import annotations

import logging
import secrets
from typing import Any
from uuid import uuid4

import httpx
from a2a.client import create_text_message_object
from a2a.client.transports.jsonrpc import JsonRpcTransport
from a2a.types import (
    AgentCard,
    MessageSendConfiguration,
    MessageSendParams,
    PushNotificationConfig,
    Task,
)

from giulia.agents.a2a.a2a_agent_factory import resolve_agent_base_url
from giulia.agents.delegation.handler import delegation_local_base_url_override
from giulia.agents.push_notifications.handler import (
    push_callback_url,
    register_push_token,
)

logger = logging.getLogger(__name__)


async def resolve_a2a_target_base_url(agent_id: str) -> str:
    """Resolve peer base URL (local override JSON, then registry)."""
    override = delegation_local_base_url_override(agent_id)
    if override:
        return override.rstrip("/")
    return await resolve_agent_base_url(agent_id)


async def _fetch_agent_card(
    base_url: str,
    httpx_client: httpx.AsyncClient,
) -> AgentCard:
    url = f"{base_url.rstrip('/')}/.well-known/agent-card.json"
    resp = await httpx_client.get(url)
    resp.raise_for_status()
    return AgentCard.model_validate(resp.json())


async def send_a2a_with_push(
    *,
    target_agent_id: str,
    request_text: str,
    httpx_client: httpx.AsyncClient,
    callback_url: str | None = None,
    push_token: str | None = None,
    context_id: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Fire-and-forget A2A message with push callback when the task completes."""
    base_url = await resolve_a2a_target_base_url(target_agent_id)
    card = await _fetch_agent_card(base_url, httpx_client)

    if not (card.capabilities and card.capabilities.push_notifications):
        raise ValueError(
            f"Agent {target_agent_id} does not advertise pushNotifications in its card"
        )

    token = push_token or secrets.token_urlsafe(24)
    register_push_token(token)

    callback = callback_url or push_callback_url()
    push_config = PushNotificationConfig(
        url=callback,
        token=token,
        id=str(uuid4()),
    )

    message = create_text_message_object(content=request_text)
    if context_id:
        message = message.model_copy(update={"context_id": context_id})

    params = MessageSendParams(
        message=message,
        configuration=MessageSendConfiguration(
            blocking=False,
            push_notification_config=push_config,
        ),
    )

    # Use resolved base_url for RPC, not card.url (public URL in the JSON). Same as
    # remote_a2a_agent_from_registry: local dev must hit localhost, not giulia.ai.
    rpc_url = base_url.rstrip("/") + "/"
    transport = JsonRpcTransport(
        httpx_client,
        agent_card=card.model_copy(update={"url": rpc_url}),
        url=rpc_url,
    )

    try:
        result = await transport.send_message(params)
    except Exception:
        logger.exception("A2A push send failed for %s", target_agent_id)
        raise

    if isinstance(result, Task):
        task_payload = result.model_dump(mode="json", exclude_none=True)
        return {
            "status": "submitted",
            "agent_id": target_agent_id,
            "task_id": result.id,
            "context_id": result.context_id,
            "push_callback": callback,
            "task": task_payload,
        }

    return {
        "status": "message",
        "agent_id": target_agent_id,
        "response": result.model_dump(mode="json", exclude_none=True)
        if hasattr(result, "model_dump")
        else str(result),
        "push_callback": callback,
    }
