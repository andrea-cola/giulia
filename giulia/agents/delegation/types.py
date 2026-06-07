"""Shared types for inbound agent delegation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InboundDelegationJob:
    request: str
    invocation_id: str
    session_id: str | None
    source_agent_id: str | None = None
    source_app_name: str | None = None
    process_id: str | None = None
    # ADK user_id for the session (default ``delegation`` for cross-agent hops).
    user_id: str | None = None
    parent_delegation_id: str | None = (
        None  # invocation_id of the sender; NULL for root
    )
