"""JWT verification using the configured KMS provider.

By default tokens are RS256-signed and the public key is fetched from
Google Cloud KMS (``GcpKmsProvider``).  Swap in any ``KmsProvider``
implementation via ``giulia.configure(kms=...)`` before startup to use
a different key source (e.g. a PEM file or a static key for tests).

The expected JWT issuer is read from the ``JWT_ISSUER`` env var / config
field.  An empty string disables issuer validation entirely.
"""

from __future__ import annotations

import logging

import jwt
from cachetools import TTLCache

logger = logging.getLogger(__name__)

_public_key_cache: TTLCache[str, str] = TTLCache(maxsize=4, ttl=3600)


class JWTValidationError(Exception):
    """Raised when a JWT cannot be verified."""


def _get_kms_key_ref() -> str:
    """Build the key reference for the active KMS provider from config."""
    from giulia.agents.core import config

    # GCP KMS resource path — used by GcpKmsProvider.
    # FileKmsProvider / StaticKmsProvider ignore this value (they use their
    # own path / pre-loaded key), but returning it avoids breaking the
    # "KMS key not configured" guard for GCP deployments.
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


def verify_jwt(token: str) -> dict:
    """Decode and validate an RS256 JWT using the configured KMS provider.

    Returns the decoded payload on success.
    Raises :class:`JWTValidationError` on any failure (bad signature,
    expired, malformed).
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
            options=decode_options,
        )
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise JWTValidationError("Token has expired") from exc
    except jwt.InvalidIssuerError as exc:
        raise JWTValidationError("Invalid token issuer") from exc
    except jwt.InvalidTokenError as exc:
        raise JWTValidationError(f"Invalid token: {exc}") from exc
