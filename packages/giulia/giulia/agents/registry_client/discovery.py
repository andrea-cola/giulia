from __future__ import annotations

import logging
from datetime import UTC
from typing import Any

import httpx

from giulia.agents.auth.crypto import (
    Ed25519PublicKey,
    public_key_from_jwk,
    verify_signature,
    verify_vc_proof,
)
from giulia.agents.core import config
from giulia.agents.utils.cache import get_agent_cache

logger = logging.getLogger(__name__)

_bearer_token: str | None = None


def _internal_auth_headers() -> dict[str, str]:
    """Return auth headers for internal calls to the registry (master key)."""
    global _bearer_token
    if _bearer_token is None:
        from .registration import get_bearer_token

        _bearer_token = get_bearer_token()
    return {"Authorization": _bearer_token, "x-key-type": "master"}


async def discover_agents(
    capability: str | None = None,
    region: str | None = None,
    tier: str | None = None,
    keyword: str | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """
    Query the internal registry for agents matching the given criteria.
    Results are cached in-memory with TTL from each AgentAddr record.
    """
    cache = get_agent_cache()
    cache_key = f"discover:{capability}:{region}:{tier}:{keyword}"

    if use_cache:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    params: dict[str, str] = {}
    if capability:
        params["capability"] = capability
    if region:
        params["region"] = region
    if tier:
        params["tier"] = tier
    if keyword:
        params["keyword"] = keyword

    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            resp = await client.get(
                f"{config.registry_http_origin}/registry/api/v1/agents",
                params=params,
                headers=_internal_auth_headers(),
            )
            resp.raise_for_status()
            agents = resp.json()
    except Exception:
        logger.exception("Failed to query internal index, falling back to cache")
        stale = cache.get(cache_key, allow_stale=True)
        return stale if stale is not None else []

    if agents:
        min_ttl = min(a.get("ttl", 900) for a in agents)
        cache.set(cache_key, agents, min_ttl)

    return agents


async def fetch_agentfacts(facts_url: str) -> dict[str, Any]:
    """Fetch an AgentFacts document from a given URL."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(facts_url)
        resp.raise_for_status()
        return resp.json()


async def fetch_jwks_key(
    jwks_url: str,
    kid: str = "key-1",
) -> Ed25519PublicKey:
    """Fetch a JWKS document and extract the Ed25519 public key matching *kid*."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(jwks_url)
        resp.raise_for_status()
        jwks = resp.json()

    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return public_key_from_jwk(key)

    raise ValueError(f"No key with kid={kid!r} found in JWKS at {jwks_url}")


def verify_agentfacts(
    facts: dict[str, Any],
    public_key: Ed25519PublicKey,
) -> bool:
    """Verify an AgentFacts v1.2 document.

    Checks performed:
    1. ``trust.proof`` (VC signature over the document minus the proof)
    2. Top-level ``signature`` field (whole-document integrity)
    3. Expiry (``trust.expirationDate``)
    """
    from datetime import datetime

    trust = facts.get("trust")
    if not trust:
        logger.warning("AgentFacts missing trust block")
        return False

    proof = trust.get("proof")
    if not proof:
        logger.warning("AgentFacts missing proof")
        return False

    signed_doc = {k: v for k, v in facts.items() if k not in ("trust", "signature")}

    if not verify_vc_proof(public_key, signed_doc, proof):
        logger.warning("AgentFacts trust.proof verification failed")
        return False

    top_sig = facts.get("signature")
    if top_sig:
        doc_without_sig = {k: v for k, v in facts.items() if k != "signature"}
        if not verify_signature(public_key, doc_without_sig, top_sig):
            logger.warning("AgentFacts top-level signature verification failed")
            return False

    expiration = trust.get("expirationDate")
    if expiration:
        exp_dt = datetime.fromisoformat(expiration)
        if exp_dt < datetime.now(UTC):
            logger.warning("AgentFacts expired at %s", expiration)
            return False

    return True


async def fetch_and_verify_agentfacts(
    facts_url: str,
) -> tuple[dict[str, Any], bool]:
    """Fetch an AgentFacts document, resolve the JWKS, and verify signatures.

    Returns ``(facts_dict, is_verified)``.
    """
    facts = await fetch_agentfacts(facts_url)

    jwks_url = facts.get("auth", {}).get("jwks")
    if not jwks_url:
        logger.warning("AgentFacts at %s has no auth.jwks — cannot verify", facts_url)
        return facts, False

    try:
        public_key = await fetch_jwks_key(jwks_url)
    except Exception:
        logger.exception("Failed to fetch JWKS from %s", jwks_url)
        return facts, False

    verified = verify_agentfacts(facts, public_key)
    return facts, verified


async def resolve_agent(agent_id: str) -> dict[str, Any] | None:
    """Resolve a specific agent by its URN from the internal index."""
    cache = get_agent_cache()
    cache_key = f"resolve:{agent_id}"

    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            resp = await client.get(
                f"{config.registry_http_origin}/registry/api/v1/agents/{agent_id}",
                headers=_internal_auth_headers(),
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            agent = resp.json()
            cache.set(cache_key, agent, agent.get("ttl", 900))
            return agent
    except Exception:
        logger.exception("Failed to resolve agent %s", agent_id)
        return cache.get(cache_key, allow_stale=True)
