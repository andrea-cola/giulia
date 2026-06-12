"""JWT signing and verification using the configured KMS provider.

By default tokens are RS256-signed and keys are managed via
Google Cloud KMS (``GcpKmsProvider``).  Swap in any ``KmsProvider``
/ ``KmsSigningProvider`` implementation via ``giulia.configure(kms=...)``
before startup to use a different key source.

The expected JWT issuer is read from the ``JWT_ISSUER`` env var / config
field.  An empty string disables issuer validation entirely.
"""

from __future__ import annotations

import base64
import json
import logging

import jwt
from cachetools import TTLCache

logger = logging.getLogger(__name__)

_public_key_cache: TTLCache[str, str] = TTLCache(maxsize=4, ttl=3600)


class JWTValidationError(Exception):
    """Raised when a JWT cannot be verified."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _b64url(data: str) -> str:
    """Base64url-encode a UTF-8 string (no padding)."""
    return base64.urlsafe_b64encode(data.encode()).rstrip(b"=").decode()


def _b64url_bytes(data: bytes) -> str:
    """Base64url-encode raw bytes (no padding)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _get_kms_key_ref() -> str:
    """Build the key reference for the active KMS provider from config."""
    from giulia.agents.core import config

    if config.kms_key_ring and config.kms_key_name:
        return (
            f"projects/{config.google_cloud_project}/locations/{config.kms_region}"
            f"/keyRings/{config.kms_key_ring}/cryptoKeys/{config.kms_key_name}"
            f"/cryptoKeyVersions/{config.kms_key_version}"
        )
    return ""


def _fetch_public_key(key_ref: str) -> str:
    """Fetch the PEM public key via the active KMS provider, with a 1-hour TTL cache."""
    cached = _public_key_cache.get(key_ref)
    if cached is not None:
        return cached

    from giulia.providers.registry import get_kms

    pem = get_kms().get_public_key_pem(key_ref)
    _public_key_cache[key_ref] = pem
    logger.info("Fetched public key for ref=%s", key_ref or "(provider default)")
    return pem


# ---------------------------------------------------------------------------
# JWT signing
# ---------------------------------------------------------------------------


def sign_jwt(
    payload: dict,
    *,
    key_ref: str | None = None,
    kid: str = "kms-key-1",
) -> str:
    """Create an RS256 JWT signed by the configured KMS signing provider.

    Args:
        payload: JWT claims dict (must include at least ``sub``, ``exp``).
        key_ref: KMS key version resource name. Defaults to the agent's
                 configured KMS key if ``None``.
        kid: Key ID placed in the JWT header.

    Returns:
        The signed JWT as a compact JWS string.

    Raises:
        RuntimeError: if the KMS provider does not support signing or
                      if signing fails.
    """
    from giulia.providers.kms import KmsSigningProvider
    from giulia.providers.registry import get_kms

    provider = get_kms()
    if not isinstance(provider, KmsSigningProvider):
        raise RuntimeError(
            f"Configured KMS provider {type(provider).__name__!r} does not "
            "support signing. Use GcpKmsProvider or another KmsSigningProvider."
        )

    effective_key_ref = key_ref or _get_kms_key_ref()

    header = {"alg": "RS256", "typ": "JWT", "kid": kid}
    segments = [_b64url(json.dumps(header)), _b64url(json.dumps(payload))]
    signing_input = f"{segments[0]}.{segments[1]}".encode()

    signature = provider.sign(effective_key_ref, signing_input)
    return f"{segments[0]}.{segments[1]}.{_b64url_bytes(signature)}"


# ---------------------------------------------------------------------------
# JWT verification
# ---------------------------------------------------------------------------


def verify_jwt(token: str, *, audience: str | None = None) -> dict:
    """Decode and validate an RS256 JWT using the configured KMS provider.

    Args:
        token: The compact JWS string to verify.
        audience: If provided, the ``aud`` claim must match this value.
                  Enables Zero Trust audience binding.

    Returns:
        The decoded payload dict on success.

    Raises:
        JWTValidationError: on any failure (bad signature, expired,
            wrong issuer, wrong audience, malformed).
    """
    from giulia.agents.core import config

    key_ref = _get_kms_key_ref()

    try:
        public_key_pem = _fetch_public_key(key_ref)
    except Exception as exc:
        raise JWTValidationError(f"Failed to fetch public key: {exc}") from exc

    issuer = config.jwt_issuer or None
    decode_options: dict = {"require": ["sub", "exp"]}
    if issuer:
        decode_options["require"].append("iss")

    try:
        payload = jwt.decode(
            token,
            public_key_pem,
            algorithms=["RS256"],
            issuer=issuer,
            audience=audience,
            options=decode_options,
        )
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise JWTValidationError("Token has expired") from exc
    except jwt.InvalidIssuerError as exc:
        raise JWTValidationError("Invalid token issuer") from exc
    except jwt.InvalidAudienceError as exc:
        raise JWTValidationError("Invalid token audience") from exc
    except jwt.InvalidTokenError as exc:
        raise JWTValidationError(f"Invalid token: {exc}") from exc
