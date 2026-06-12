"""ADK function tools for Google Chat integration.

These tools can be imported and used by any ADK agent to send messages
to Google Chat spaces and read message history.
"""

from __future__ import annotations

import json
import logging

import httpx
from google.adk.tools.tool_context import ToolContext

from . import client

logger = logging.getLogger(__name__)


async def _store_context_mapping(space_name: str, context_id: str) -> bool:
    """Store the space_name -> context_id mapping in Redis via the API service."""
    try:
        from giulia.agents.core.config import config

        payload = {
            "space_name": space_name,
            "context_id": context_id,
        }

        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as http_client:
            resp = await http_client.post(
                f"{config.api_url}/api/v1/chat/google/context",
                json=payload,
            )
            resp.raise_for_status()
            return True
    except Exception:
        logger.exception("Failed to store context mapping for space %s", space_name)
        return False


async def send_google_chat_message(
    tool_context: ToolContext,
    *,
    space_name: str,
    text: str,
    thread_name: str = "",
) -> str:
    """Send a message to a Google Chat space.

    Use this tool to send messages to Google Chat spaces where the Chat App
    is a member. The message will be sent as the Chat App (bot).

    Args:
        tool_context: ADK tool context (provided automatically).
        space_name: The Google Chat space to send to (e.g. 'spaces/AAABBBCCC').
                   You can find this in the space URL or by asking the user.
        text: The message text to send. Supports basic Markdown formatting:
              *bold*, _italic_, ~strikethrough~, `code`.
        thread_name: Optional thread to reply to (e.g. 'spaces/AAA/threads/BBB').
                    Leave empty to start a new thread or post to main chat.

    Returns:
        JSON string with status and message details, or error information.
    """
    space = (space_name or "").strip()
    msg_text = (text or "").strip()
    thread = (thread_name or "").strip() or None

    if not space:
        return json.dumps({"status": "error", "message": "space_name is required"})
    if not msg_text:
        return json.dumps({"status": "error", "message": "text is required"})

    if not space.startswith("spaces/"):
        space = f"spaces/{space}"

    try:
        response = await client.send_message(
            space_name=space,
            text=msg_text,
            thread_name=thread,
        )

        context_id = getattr(tool_context, "context_id", None)
        if context_id:
            await _store_context_mapping(space, context_id)
            logger.info(
                "Stored context mapping: %s -> %s",
                space,
                context_id,
            )

        return json.dumps(
            {
                "status": "ok",
                "message_name": response.name,
                "space_name": response.space_name,
                "thread_name": response.thread_name,
                "create_time": response.create_time,
            }
        )
    except httpx.HTTPStatusError as e:
        logger.exception("Failed to send Google Chat message")
        return json.dumps(
            {
                "status": "error",
                "message": f"API error: {e.response.status_code}",
                "detail": str(e),
            }
        )
    except Exception as e:
        logger.exception("Failed to send Google Chat message")
        return json.dumps(
            {
                "status": "error",
                "message": "Failed to send message",
                "detail": str(e),
            }
        )


async def list_google_chat_messages(
    tool_context: ToolContext,
    *,
    space_name: str,
    page_size: int = 25,
) -> str:
    """List recent messages in a Google Chat space.

    Use this tool to read message history from a Chat space. Useful for
    getting context about a conversation before responding.

    Args:
        tool_context: ADK tool context (provided automatically).
        space_name: The Google Chat space to read from (e.g. 'spaces/AAABBBCCC').
        page_size: Number of messages to retrieve (1-100, default 25).

    Returns:
        JSON string with status and list of messages, or error information.
    """
    _ = tool_context
    space = (space_name or "").strip()

    if not space:
        return json.dumps({"status": "error", "message": "space_name is required"})

    if not space.startswith("spaces/"):
        space = f"spaces/{space}"

    size = max(1, min(page_size, 100))

    try:
        result = await client.list_messages(space_name=space, page_size=size)

        messages = []
        for msg in result.get("messages", []):
            sender = msg.get("sender", {})
            messages.append(
                {
                    "name": msg.get("name", ""),
                    "text": msg.get("text", ""),
                    "sender_name": sender.get("displayName", ""),
                    "sender_email": sender.get("email", ""),
                    "create_time": msg.get("createTime", ""),
                    "thread_name": msg.get("thread", {}).get("name", ""),
                }
            )

        return json.dumps(
            {
                "status": "ok",
                "count": len(messages),
                "messages": messages,
                "next_page_token": result.get("nextPageToken"),
            }
        )
    except httpx.HTTPStatusError as e:
        logger.exception("Failed to list Google Chat messages")
        return json.dumps(
            {
                "status": "error",
                "message": f"API error: {e.response.status_code}",
                "detail": str(e),
            }
        )
    except Exception as e:
        logger.exception("Failed to list Google Chat messages")
        return json.dumps(
            {
                "status": "error",
                "message": "Failed to list messages",
                "detail": str(e),
            }
        )


async def list_google_chat_spaces(
    tool_context: ToolContext,
    *,
    page_size: int = 50,
) -> str:
    """List Google Chat spaces the Chat App is a member of.

    Use this tool to discover available spaces before sending messages.

    Args:
        tool_context: ADK tool context (provided automatically).
        page_size: Number of spaces to retrieve (1-100, default 50).

    Returns:
        JSON string with status and list of spaces, or error information.
    """
    _ = tool_context
    size = max(1, min(page_size, 100))

    try:
        result = await client.list_spaces(page_size=size)

        spaces = []
        for space in result.get("spaces", []):
            spaces.append(
                {
                    "name": space.get("name", ""),
                    "display_name": space.get("displayName", ""),
                    "type": space.get("type", ""),
                    "threaded": space.get("threaded", False),
                }
            )

        return json.dumps(
            {
                "status": "ok",
                "count": len(spaces),
                "spaces": spaces,
                "next_page_token": result.get("nextPageToken"),
            }
        )
    except httpx.HTTPStatusError as e:
        logger.exception("Failed to list Google Chat spaces")
        return json.dumps(
            {
                "status": "error",
                "message": f"API error: {e.response.status_code}",
                "detail": str(e),
            }
        )
    except Exception as e:
        logger.exception("Failed to list Google Chat spaces")
        return json.dumps(
            {
                "status": "error",
                "message": "Failed to list spaces",
                "detail": str(e),
            }
        )
