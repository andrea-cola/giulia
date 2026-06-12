"""Pydantic models for Google Chat webhook events."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ChatEventType(StrEnum):
    """Google Chat event types sent to webhooks."""

    MESSAGE = "MESSAGE"
    ADDED_TO_SPACE = "ADDED_TO_SPACE"
    REMOVED_FROM_SPACE = "REMOVED_FROM_SPACE"
    CARD_CLICKED = "CARD_CLICKED"


class ChatUserType(StrEnum):
    """Type of user in Google Chat."""

    HUMAN = "HUMAN"
    BOT = "BOT"


class ChatSpaceType(StrEnum):
    """Type of Chat space."""

    ROOM = "ROOM"
    DM = "DM"
    SPACE = "SPACE"


class ChatUser(BaseModel):
    """A user in Google Chat."""

    name: str = Field(..., description="Resource name, e.g. 'users/123456789'")
    display_name: str = Field(default="", alias="displayName")
    email: str = Field(default="")
    type: ChatUserType = Field(default=ChatUserType.HUMAN)
    domain_id: str | None = Field(default=None, alias="domainId")


class ChatSpace(BaseModel):
    """A Google Chat space."""

    name: str = Field(..., description="Resource name, e.g. 'spaces/AAABBBCCC'")
    display_name: str = Field(default="", alias="displayName")
    type: ChatSpaceType = Field(default=ChatSpaceType.SPACE)
    single_user_bot_dm: bool = Field(default=False, alias="singleUserBotDm")
    threaded: bool = Field(default=False)


class ChatThread(BaseModel):
    """A thread within a Google Chat space."""

    name: str = Field(..., description="Resource name, e.g. 'spaces/AAA/threads/BBB'")
    thread_key: str | None = Field(default=None, alias="threadKey")


class ChatMessage(BaseModel):
    """A message in Google Chat."""

    name: str = Field(default="", description="Resource name of the message")
    sender: ChatUser | None = None
    text: str = Field(default="")
    thread: ChatThread | None = None
    create_time: str | None = Field(default=None, alias="createTime")
    argument_text: str | None = Field(default=None, alias="argumentText")
    annotations: list[dict[str, Any]] = Field(default_factory=list)


class ChatWebhookEvent(BaseModel):
    """Inbound webhook event from Google Chat.

    Google Chat POSTs this payload when a user interacts with a Chat App.
    """

    type: ChatEventType
    event_time: str | None = Field(default=None, alias="eventTime")
    space: ChatSpace
    message: ChatMessage | None = None
    user: ChatUser | None = None
    config_complete_redirect_url: str | None = Field(
        default=None, alias="configCompleteRedirectUrl"
    )

    @property
    def sender_email(self) -> str | None:
        """Extract sender email from the event."""
        if self.message and self.message.sender:
            return self.message.sender.email or None
        if self.user:
            return self.user.email or None
        return None

    @property
    def sender_name(self) -> str | None:
        """Extract sender resource name (users/...) from the event."""
        if self.message and self.message.sender:
            return self.message.sender.name
        if self.user:
            return self.user.name
        return None

    @property
    def message_text(self) -> str:
        """Extract plain text content from the message."""
        if self.message:
            return self.message.argument_text or self.message.text or ""
        return ""

    @property
    def space_name(self) -> str:
        """Space resource name (spaces/...)."""
        return self.space.name

    @property
    def thread_name(self) -> str | None:
        """Thread resource name if present."""
        if self.message and self.message.thread:
            return self.message.thread.name
        return None


class SendMessageRequest(BaseModel):
    """Request payload for sending a message to Google Chat."""

    space_name: str = Field(..., description="Space resource name (spaces/...)")
    text: str = Field(..., description="Message text content")
    thread_name: str | None = Field(
        default=None, description="Thread name to reply to (optional)"
    )


class SendMessageResponse(BaseModel):
    """Response from sending a message to Google Chat."""

    name: str = Field(..., description="Resource name of the created message")
    space_name: str = Field(default="", alias="spaceName")
    thread_name: str | None = Field(default=None, alias="threadName")
    create_time: str | None = Field(default=None, alias="createTime")
