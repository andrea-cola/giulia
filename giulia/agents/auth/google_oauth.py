"""Google OAuth 2.0 token verification for Gemini Enterprise / Agent Engine.

Validates Google-issued OAuth access tokens by calling Google's tokeninfo
endpoint.  Results are cached briefly to avoid per-request round-trips.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from cachetools import TTLCache

logger = logging.getLogger(__name__)

_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"

_token_cache: TTLCache[str, _GoogleTokenInfo] = TTLCache(maxsize=256, ttl=300)

_http_client: httpx.AsyncClient | None = None


class GoogleOAuthError(Exception):
    """Raised when a Google OAuth token cannot be verified."""


@dataclass(frozen=True, slots=True)
class _GoogleTokenInfo:
    email: str
    scope: str
    expires_in: int
    audience: str


async def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=5.0)
    return _http_client


async def verify_google_token(
    token: str,
    expected_client_id: str = "",
) -> dict:
    """Verify a Google OAuth access token via the tokeninfo endpoint.

    Returns a dict with ``email``, ``scope``, ``expires_in``, ``audience``.
    Raises :class:`GoogleOAuthError` on any failure.
    """
    cached = _token_cache.get(token)
    if cached is not None:
        return {
            "email": cached.email,
            "scope": cached.scope,
            "expires_in": cached.expires_in,
            "audience": cached.audience,
        }

    client = await _get_client()
    try:
        resp = await client.get(_TOKENINFO_URL, params={"access_token": token})
    except httpx.HTTPError as exc:
        raise GoogleOAuthError(f"Failed to reach Google tokeninfo: {exc}") from exc

    if resp.status_code != 200:
        detail = (
            resp.json().get("error_description", resp.text)
            if resp.headers.get("content-type", "").startswith("application/json")
            else resp.text
        )
        raise GoogleOAuthError(f"Google token invalid: {detail}")

    data = resp.json()

    if "error" in data:
        raise GoogleOAuthError(f"Google token error: {data['error']}")

    if expected_client_id and data.get("aud") != expected_client_id:
        raise GoogleOAuthError(
            f"Token audience {data.get('aud')!r} does not match "
            f"expected client ID {expected_client_id!r}"
        )

    info = _GoogleTokenInfo(
        email=data.get("email", data.get("sub", "")),
        scope=data.get("scope", ""),
        expires_in=int(data.get("expires_in", 0)),
        audience=data.get("aud", ""),
    )
    _token_cache[token] = info

    return {
        "email": info.email,
        "scope": info.scope,
        "expires_in": info.expires_in,
        "audience": info.audience,
    }
