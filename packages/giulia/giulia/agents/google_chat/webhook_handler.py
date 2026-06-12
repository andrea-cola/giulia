"""Google Chat webhook utilities.

Note: The actual webhook endpoint is hosted centrally at the registry:
    POST /registry/api/v1/google-chat/webhook

This module provides helper functions for signature verification that can be
used if you need to implement custom webhook handling.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

logger = logging.getLogger(__name__)

_webhook_secret: str | None = None


def get_webhook_secret() -> str | None:
    """Fetch the webhook verification secret from Secret Manager or env.

    Checks in order:
    1. GOOGLE_CHAT_WEBHOOK_SECRET environment variable
    2. Secret Manager (requires GOOGLE_CLOUD_PROJECT)

    Returns:
        The secret string, or None if not configured.
    """
    global _webhook_secret
    if _webhook_secret is not None:
        return _webhook_secret

    env_secret = os.getenv("GOOGLE_CHAT_WEBHOOK_SECRET")
    if env_secret:
        _webhook_secret = env_secret
        return _webhook_secret

    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    secret_name = os.getenv("GOOGLE_CHAT_SECRET_NAME", "google-chat-webhook-secret")

    if not project_id:
        logger.warning(
            "GOOGLE_CLOUD_PROJECT not set, cannot fetch webhook secret from Secret Manager"
        )
        return None

    try:
        from giulia.providers.registry import get_secrets

        resource = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
        _webhook_secret = get_secrets().get_secret(resource)
        return _webhook_secret
    except Exception:
        logger.exception("Failed to fetch webhook secret from secrets provider")
        return None


def verify_signature(body: bytes, signature: str | None, secret: str) -> bool:
    """Verify the HMAC-SHA256 signature from Google Chat.

    Args:
        body: The raw request body bytes.
        signature: The X-Goog-Signature header value.
        secret: The webhook verification secret.

    Returns:
        True if the signature is valid, False otherwise.
    """
    if not signature:
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)
