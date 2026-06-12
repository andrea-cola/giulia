"""Shared pytest fixtures for the giulia test suite."""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_agent_urn() -> str:
    return "urn:agent:acme:private:test-agent"


@pytest.fixture
def sample_scopes() -> list[str]:
    return ["agent:invoke", "agent:read"]
