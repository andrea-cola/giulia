"""Google Chat REST API client using Application Default Credentials.

Uses the same ADC/Workload Identity pattern as other GCP services in this codebase.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import google.auth
import google.auth.transport.requests
import httpx

from .models import SendMessageResponse

logger = logging.getLogger(__name__)

CHAT_API_BASE = "https://chat.googleapis.com/v1"
CHAT_BOT_SCOPE = "https://www.googleapis.com/auth/chat.bot"

_credentials = None


def _get_access_token() -> str:
    """Fetch a short-lived GCP access token for Chat API calls."""
    global _credentials
    if _credentials is None:
        _credentials, _ = google.auth.default(scopes=[CHAT_BOT_SCOPE])
    request = google.auth.transport.requests.Request()
    _credentials.refresh(request)
    return _credentials.token


async def _get_auth_headers() -> dict[str, str]:
    """Get authorization headers for Chat API calls."""
    token = await asyncio.to_thread(_get_access_token)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def send_message(
    space_name: str,
    text: str,
    thread_name: str | None = None,
    message_id: str | None = None,
) -> SendMessageResponse:
    """Send a message to a Google Chat space.

    Args:
        space_name: Space resource name (e.g. 'spaces/AAABBBCCC').
        text: Message text content.
        thread_name: Optional thread name to reply to.
        message_id: Optional client-assigned message ID (must start with 'client-').

    Returns:
        SendMessageResponse with the created message details.

    Raises:
        httpx.HTTPStatusError: If the API request fails.
    """
    url = f"{CHAT_API_BASE}/{space_name}/messages"

    params: dict[str, str] = {}
    if message_id:
        params["messageId"] = message_id

    body: dict[str, Any] = {"text": text}
    if thread_name:
        body["thread"] = {"name": thread_name}

    headers = await _get_auth_headers()

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=body, params=params)
        response.raise_for_status()
        data = response.json()

    logger.info(
        "Sent message to %s (thread=%s): %s",
        space_name,
        thread_name,
        data.get("name", "unknown"),
    )

    return SendMessageResponse(
        name=data.get("name", ""),
        spaceName=data.get("space", {}).get("name", space_name),
        threadName=data.get("thread", {}).get("name"),
        createTime=data.get("createTime"),
    )


async def list_messages(
    space_name: str,
    page_size: int = 25,
    page_token: str | None = None,
    filter_str: str | None = None,
    show_deleted: bool = False,
) -> dict[str, Any]:
    """List messages in a Google Chat space.

    Args:
        space_name: Space resource name (e.g. 'spaces/AAABBBCCC').
        page_size: Maximum number of messages to return (1-1000).
        page_token: Page token from a previous request.
        filter_str: Optional filter expression (e.g. 'createTime > "2024-01-01"').
        show_deleted: Whether to include deleted messages.

    Returns:
        Dict with 'messages' list and optional 'nextPageToken'.

    Raises:
        httpx.HTTPStatusError: If the API request fails.
    """
    url = f"{CHAT_API_BASE}/{space_name}/messages"

    params: dict[str, str | int | bool] = {
        "pageSize": min(max(page_size, 1), 1000),
        "showDeleted": show_deleted,
    }
    if page_token:
        params["pageToken"] = page_token
    if filter_str:
        params["filter"] = filter_str

    headers = await _get_auth_headers()

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()


async def list_spaces(
    page_size: int = 100,
    page_token: str | None = None,
) -> dict[str, Any]:
    """List spaces the Chat App is a member of.

    Args:
        page_size: Maximum number of spaces to return.
        page_token: Page token from a previous request.

    Returns:
        Dict with 'spaces' list and optional 'nextPageToken'.

    Raises:
        httpx.HTTPStatusError: If the API request fails.
    """
    url = f"{CHAT_API_BASE}/spaces"

    params: dict[str, str | int] = {"pageSize": page_size}
    if page_token:
        params["pageToken"] = page_token

    headers = await _get_auth_headers()

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()


async def get_space(space_name: str) -> dict[str, Any]:
    """Get details about a specific space.

    Args:
        space_name: Space resource name (e.g. 'spaces/AAABBBCCC').

    Returns:
        Space details dict.

    Raises:
        httpx.HTTPStatusError: If the API request fails.
    """
    url = f"{CHAT_API_BASE}/{space_name}"
    headers = await _get_auth_headers()

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
