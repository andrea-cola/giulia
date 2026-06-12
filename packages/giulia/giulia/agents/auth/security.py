from __future__ import annotations

import logging
import re
import time
from typing import Any

from .crypto import Ed25519PublicKey, verify_vc_proof

logger = logging.getLogger(__name__)

_nsa_registry: dict[str, float] = {}
NSA_PROBATION_SECONDS = 3600


async def verify_external_caller(
    caller_did: str,
    caller_agentfacts: dict[str, Any] | None = None,
    public_key: Ed25519PublicKey | None = None,
) -> dict[str, Any]:
    """
    Verify an external caller against the agent registry.
    Returns a verdict dict with 'allowed', 'reason', and metadata.
    """
    verdict: dict[str, Any] = {"allowed": False, "caller_did": caller_did}

    if caller_agentfacts is None:
        logger.error("Caller agentfacts are required")
        raise ValueError("Caller agentfacts are required")

    if public_key and caller_agentfacts:
        trust = caller_agentfacts.get("trust", {})
        proof = trust.get("proof", {})
        doc = {k: v for k, v in caller_agentfacts.items() if k != "trust"}
        trust_no_proof = {k: v for k, v in trust.items() if k != "proof"}
        doc["trust"] = trust_no_proof
        if not verify_vc_proof(public_key, doc, proof):
            verdict["reason"] = "AgentFacts signature verification failed"
            return verdict

    is_nsa = _check_nsa(caller_did)
    if is_nsa:
        verdict["nsa_probation"] = True
        logger.warning("Caller %s is a Newly Seen Agent (NSA)", caller_did)

    verdict["allowed"] = True
    verdict["reason"] = "Verified"
    return verdict


def _check_nsa(caller_did: str) -> bool:
    """
    Newly Seen Agent detection.
    Returns True if the agent has never been seen before or is still in probation.
    """
    now = time.time()
    first_seen = _nsa_registry.get(caller_did)
    if first_seen is None:
        _nsa_registry[caller_did] = now
        return True
    return (now - first_seen) < NSA_PROBATION_SECONDS


_DLP_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),  # email
    re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b"),  # credit card
]


def dlp_scan(text: str) -> list[str]:
    """
    Scan text for sensitive data patterns.
    Returns a list of pattern names that matched.
    """
    findings: list[str] = []
    labels = ["SSN", "email", "credit_card"]
    for pattern, label in zip(_DLP_PATTERNS, labels, strict=False):
        if pattern.search(text):
            findings.append(label)
    return findings


def sanitize_response(data: dict[str, Any]) -> dict[str, Any]:
    """
    Sanitize outbound response data:
    - Remove internal agent names and endpoints
    - Run DLP scan on string values
    """
    sanitized = {}
    internal_keys = {
        "agent_id",
        "k8s_service_url",
        "primary_facts_url",
        "private_facts_url",
    }
    for key, value in data.items():
        if key in internal_keys:
            continue
        if isinstance(value, str) and ":internal:" in value:
            continue
        sanitized[key] = value
    return sanitized
