"""Auth middleware for agents — API keys, Google OAuth, and KMS JWTs.

Supports three token formats in the ``Authorization: Bearer <token>`` header:

* **API keys** (``sk-*`` prefix) — forwarded to the Registry's
  ``/registry/api/v1/validate-key`` endpoint for validation (same path
  family as agent registration).
* **Google OAuth tokens** — verified via Google's tokeninfo endpoint
  (for Gemini Enterprise / Agent Engine callers).
* **KMS-signed JWTs** — validated locally using the Cloud KMS
  public key (RS256, for A2A callers).

When ``INTERNAL_TRIGGER_PATH`` and ``INTERNAL_TRIGGER_SECRET`` are both set,
requests whose path equals ``INTERNAL_TRIGGER_PATH`` may authenticate with
``X-Internal-Trigger-Secret`` instead of ``Authorization`` (timing-safe
compare). Intended for in-project GCS - Cloud Function - agent smoke paths.

The Registry URL is read from the ``REGISTRY_URL`` environment variable
(set in every agent deployment).
"""

from __future__ import annotations

import httpx

from giulia.agents.core.constants import A2A_PUSH_PATH
from giulia.logging import logger


def _open_paths() -> set[str]:
    return {
        "/health",
        "/.well-known/agent-facts",
        "/.well-known/agent-card.json",
        "/.well-known/agent.json",
        "/.well-known/jwks.json",
        "/docs",
        "/openapi.json",
        # Telegram Bot API webhooks (unauthenticated; verify via secret token in prod).
        "/telegram/webhook",
        # A2A push callbacks authenticate via X-A2A-Notification-Token in the handler.
        A2A_PUSH_PATH,
    }


_OPEN_PATHS: set[str] = _open_paths()

_client: httpx.AsyncClient | None = None


async def _get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        from giulia.agents.core import config  # noqa: PLC0415

        _client = httpx.AsyncClient(
            base_url=config.registry_http_origin,
            timeout=5.0,
            trust_env=False,
        )
    return _client


async def validate_api_key(
    authorization: str, key_type: str | None = None
) -> tuple[int, str, str]:
    """Ask the Registry to validate a Bearer token.

    Returns ``(status_code, client_name, detail)`` where *status_code*
    is 200 on success or the error code returned by the Registry.
    """
    headers: dict[str, str] = {"authorization": authorization}
    if key_type:
        headers["x-key-type"] = key_type

    client = await _get_http_client()
    try:
        resp = await client.post("/registry/api/v1/validate-key", headers=headers)
    except httpx.HTTPError:
        logger.exception("Failed to contact the registry for key validation")
        return 503, "", "Auth backend unavailable"

    if resp.status_code == 200:
        data = resp.json()
        return 200, data.get("client_name", "unknown"), ""

    detail = (
        resp.json().get("detail", "Unauthorized")
        if resp.headers.get("content-type", "").startswith("application/json")
        else "Unauthorized"
    )
    return resp.status_code, "", detail
