"""Build and serve AgentFacts v1.2 JSON-LD documents.

Spec reference: https://spec.projectnanda.org/agentfacts/v1.2.jsonld
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from starlette.responses import JSONResponse

from giulia.agents.auth.crypto import (
    Ed25519PrivateKey,
    create_vc_proof,
    generate_did_key,
    generate_did_web,
    sign_payload,
)

AGENTFACTS_CONTEXT = "https://spec.projectnanda.org/agentfacts/v1.2.jsonld"
AGENTFACTS_SCHEMA_VERSION = "1.2.0"


def agent_card_to_agentfacts(
    agent_card: dict[str, Any],
    private_key: Ed25519PrivateKey | None,
    *,
    agent_name: str,
    handle: str,
    owner: str,
    capabilities: list[str] | None = None,
    auth_method: str = "oidc",
    auth_jwks: str | None = None,
    tier: str = "private",
    domain: str | None = None,
    ttl: int = 3600,
    region: str | None = None,
    telemetry: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build an AgentFacts v1.2 JSON-LD document.

    Produces a complete document with ``@context``, ``handle``, ``owner``,
    ``auth``, ``meta`` and a detached-JWS-style ``signature`` field, as
    required by the AgentFacts v1.2 specification.
    """
    if tier == "public" and domain:
        did = generate_did_web(domain)
    elif private_key is not None:
        did = generate_did_key(private_key.public_key())
    else:
        did = f"urn:agent:{agent_name}"

    endpoint = agent_card.get("url", "")

    now = datetime.now(UTC)

    facts: dict[str, Any] = {
        "@context": AGENTFACTS_CONTEXT,
        "id": did,
        "handle": handle,
        "owner": owner,
        "endpoint": endpoint,
        "capabilities": capabilities or [],
        "auth": _build_auth(auth_method, auth_jwks),
        "meta": {
            "schema_version": AGENTFACTS_SCHEMA_VERSION,
            "published": now.isoformat(),
            "record_nonce": random.randint(0, 2**31),
        },
    }

    if region:
        facts["region"] = region

    if telemetry:
        facts["telemetry"] = telemetry

    facts["trust"] = _build_trust(private_key, did, agent_name, now, ttl, facts)

    if private_key is not None:
        facts["signature"] = sign_payload(private_key, facts)

    return facts


def _build_auth(method: str, jwks: str | None) -> dict[str, Any]:
    auth: dict[str, Any] = {"method": method}
    if jwks:
        auth["jwks"] = jwks
    return auth


def _build_trust(
    private_key: Ed25519PrivateKey | None,
    did: str,
    name: str,
    now: datetime,
    ttl: int,
    document: dict[str, Any],
) -> dict[str, Any]:
    trust: dict[str, Any] = {
        "issuer": did,
        "issuanceDate": now.isoformat(),
        "expirationDate": (now + timedelta(seconds=ttl)).isoformat(),
        "credentialSubject": {"id": did, "name": name},
    }
    if private_key is not None:
        trust["proof"] = create_vc_proof(private_key, did, document)
    return trust


def serve_agentfacts_endpoint(agentfacts: dict[str, Any]) -> JSONResponse:
    """Return AgentFacts as a JSON response for ``/.well-known/agent-facts``."""
    return JSONResponse(agentfacts)
