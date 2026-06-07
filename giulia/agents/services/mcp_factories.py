"""Factories for ADK MCP toolsets."""

from __future__ import annotations

from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams


def make_cloudsql_mcp_toolset(url: str, timeout: float = 30.0) -> McpToolset:
    """Build a McpToolset for the Cloud SQL MCP server.

    Auth is enforced at the Load Balancer level (IAP). Agents running inside
    the cluster connect directly via the internal ClusterIP and require no
    additional token. For local development, use ``make mcp-proxy`` to
    port-forward the cluster service to localhost:5001.
    """
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=url,
            timeout=timeout,
        )
    )
