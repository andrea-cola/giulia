"""Google Chat integration module for Datwave agents.

Provides ADK tools for sending messages to Google Chat. Inbound messages
are handled centrally by the registry webhook at:
    POST /registry/api/v1/google-chat/webhook

Usage in an ADK agent::

    from giulia.agents.google_chat import send_google_chat_message

    root_agent = Agent(
        name="my_agent",
        tools=[send_google_chat_message],
    )
"""

from .adk_tools import (
    list_google_chat_messages,
    list_google_chat_spaces,
    send_google_chat_message,
)
from .webhook_handler import get_webhook_secret, verify_signature

__all__ = [
    "send_google_chat_message",
    "list_google_chat_messages",
    "list_google_chat_spaces",
    "get_webhook_secret",
    "verify_signature",
]
