"""Utility functions for handling Agent URNs, slugs, and names."""

from __future__ import annotations


def urn_to_slug(agent_id: str) -> str:
    """Stable slug for registry and stream keys (last segment of URN, or sanitized id).

    Example:
        urn:agent:giulia:public:sophia -> sophia
        urn:agent:giulia:internal:crm-connector -> crm-connector
    """
    text = agent_id.strip()
    if ":" in text:
        return text.rsplit(":", 1)[-1].lower()
    return text.lower().replace("/", "-")


def urn_to_python_identifier(agent_id: str) -> str:
    """Convert an agent URN to a valid Python identifier.

    Replaces hyphens with underscores and uses the last URN segment.
    Used for ADK remote agent names.

    Example:
        urn:agent:giulia:public:supplier-scouting -> supplier_scouting
    """
    tail = agent_id.rsplit(":", 1)[-1]
    name = tail if tail else agent_id
    return name.replace("-", "_")
