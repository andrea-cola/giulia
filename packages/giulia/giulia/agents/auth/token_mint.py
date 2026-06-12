"""Zero Trust token minting — audience-bound, per-interaction JWTs.

Provides two functions:

- ``mint_token``          — issue a fresh, scoped JWT for a specific target
- ``mint_exchanged_token`` — RFC 8693 token exchange with delegation chain

Both produce JWTs signed via the configured ``KmsSigningProvider`` (see
``giulia.providers.kms``).  The OAuth service calls these directly; agents
can use them for testing or sidecar token minting.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from giulia.agents.auth.jwt_auth import sign_jwt


def mint_token(
    *,
    sub: str,
    client_name: str,
    scopes: list[str],
    issuer: str = "giulia-oauth",
    audience: str | None = None,
    ttl: int = 60,
    max_ttl: int = 300,
    delegation_chain: list[str] | None = None,
    key_ref: str | None = None,
) -> tuple[str, int]:
    """Mint an audience-bound, per-interaction JWT.

    Args:
        sub: Subject claim — typically the client_id.
        client_name: Human-readable name for the calling entity.
        scopes: List of scope strings (e.g. ``["agent:invoke"]``).
        issuer: JWT ``iss`` claim value.
        audience: Target agent URN bound to the ``aud`` claim.
        ttl: Requested token lifetime in seconds.
        max_ttl: Hard ceiling on token lifetime.
        delegation_chain: Existing chain to carry forward.
        key_ref: KMS key reference override (defaults to agent config).

    Returns:
        ``(access_token, expires_in)`` tuple.
    """
    effective_ttl = min(ttl, max_ttl)
    now = int(datetime.now(UTC).timestamp())

    payload: dict = {
        "sub": sub,
        "iss": issuer,
        "iat": now,
        "exp": now + effective_ttl,
        "scope": " ".join(scopes),
        "client_name": client_name,
        "jti": str(uuid.uuid4()),
    }

    if audience:
        payload["aud"] = audience

    if delegation_chain:
        payload["delegation_chain"] = delegation_chain

    token = sign_jwt(payload, key_ref=key_ref)
    return token, effective_ttl


def mint_exchanged_token(
    *,
    original_payload: dict,
    new_audience: str,
    acting_as: str,
    issuer: str = "giulia-oauth",
    ttl: int = 60,
    max_ttl: int = 300,
    key_ref: str | None = None,
) -> tuple[str, int]:
    """Mint a token for delegation / token exchange (RFC 8693).

    Preserves the original subject and extends the ``delegation_chain``
    with *acting_as*.

    Args:
        original_payload: Decoded claims from the inbound JWT.
        new_audience: Target agent URN for the outbound token.
        acting_as: Identity of the party performing the exchange
                   (appended to the delegation chain).
        issuer: JWT ``iss`` claim value.
        ttl: Requested token lifetime in seconds.
        max_ttl: Hard ceiling on token lifetime.
        key_ref: KMS key reference override.

    Returns:
        ``(access_token, expires_in)`` tuple.
    """
    existing_chain = list(original_payload.get("delegation_chain", []))
    original_sub = original_payload.get("sub", "")
    if not existing_chain:
        existing_chain.append(original_sub)
    existing_chain.append(acting_as)

    return mint_token(
        sub=original_sub,
        client_name=original_payload.get("client_name", acting_as),
        scopes=original_payload.get("scope", "agent:invoke").split(),
        issuer=issuer,
        audience=new_audience,
        ttl=ttl,
        max_ttl=max_ttl,
        delegation_chain=existing_chain,
        key_ref=key_ref,
    )
