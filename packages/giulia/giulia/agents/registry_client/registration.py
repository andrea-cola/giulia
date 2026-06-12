from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from giulia.agents.auth.crypto import (
    Ed25519PrivateKey,
    load_private_key_from_file,
    sign_payload,
)
from giulia.agents.core import config

logger = logging.getLogger(__name__)


def get_bearer_token() -> str:
    """Get a bearer token for the agent via the configured secrets provider."""
    from giulia.providers.registry import get_secrets
    from giulia.providers.secrets import SecretNotFoundError

    secret_name = config.bearer_token_secret_name
    project_id = config.google_cloud_project

    # Build a GCP-style resource path when a project is configured so that
    # GcpSecretsProvider can resolve the secret; EnvSecretsProvider will
    # extract just the secret name from the path automatically.
    if project_id:
        secret_id = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    else:
        secret_id = secret_name

    try:
        value = get_secrets().get_secret(secret_id)
        return "Bearer " + value
    except SecretNotFoundError:
        logger.exception("Failed to fetch bearer token")
        return ""
    except Exception:
        logger.exception("Failed to fetch bearer token")
        return ""


def register_private_agent(
    agent_config: dict[str, Any],
    signing_key: Ed25519PrivateKey | None = None,
) -> dict[str, Any]:
    """
    Register a private agent with the internal registry.
    Called at pod startup.
    """

    try:
        if signing_key is None and config.signing_key_path:
            signing_key = load_private_key_from_file(config.signing_key_path)
    except Exception:
        logger.exception("Failed to load signing key")
        raise

    try:
        service_url = agent_config.get("k8s_service_url", config.service_url)
        public_url = agent_config.get("public_url")
        payload = {
            "agent_id": agent_config.get("urn"),
            "agent_name": agent_config.get("name"),
            "description": agent_config.get("description"),
            "company": agent_config.get("company"),
            "primary_facts_url": f"{public_url}/.well-known/agent-facts",
            "private_facts_url": f"{service_url}/.well-known/agent-facts",
            "capabilities": agent_config.get("capabilities", []),
            "ttl": agent_config.get("ttl", config.default_ttl),
            "protocol": "a2a",
            "tier": agent_config.get("tier", config.tier),
            "region": agent_config.get("region", config.region),
        }
        if public_url:
            payload["public_url"] = public_url

        if signing_key:
            payload["signature"] = sign_payload(signing_key, payload)
    except Exception:
        logger.exception("Failed to sign payload")
        raise

    register_url = f"{config.registry_http_origin}/registry/api/v1/agents"
    try:
        bearer_token = get_bearer_token()
        # Do not use HTTP_PROXY/HTTPS_PROXY for in-cluster registry calls; a bad
        # proxy env in the pod causes ConnectError (e.g. errno 99) before HTTP.
        with httpx.Client(timeout=10.0, trust_env=False) as client:
            resp = client.post(
                headers={
                    "Authorization": bearer_token,
                    "Content-Type": "application/json",
                    "x-key-type": "master",
                },
                url=register_url,
                json=payload,
            )
            resp.raise_for_status()
            result = resp.json()
            return result
    except Exception as e:
        logger.exception(
            "Failed to register private agent url=%s HTTP_PROXY=%r HTTPS_PROXY=%r: %s",
            register_url,
            os.environ.get("HTTP_PROXY"),
            os.environ.get("HTTPS_PROXY"),
            e,
        )
        raise


async def _heartbeat_loop(
    agent_config: dict[str, Any],
    signing_key: Ed25519PrivateKey | None = None,
    interval_factor: float = 0.7,
):
    """
    Re-register before TTL expires. Runs as a background asyncio task.
    interval_factor < 1.0 ensures re-registration happens before expiry.

    Also records heartbeats in the database for persistent liveness tracking.
    """
    from giulia.agents.orchestration.heartbeat_db import record_heartbeat

    ttl = agent_config.get("ttl", config.default_ttl)
    interval = int(ttl * interval_factor)
    loop = asyncio.get_running_loop()

    agent_id = agent_config.get("urn")
    agent_name = agent_config.get("name")
    company = agent_config.get("company")
    service_url = agent_config.get("k8s_service_url", config.service_url)
    public_url = agent_config.get("public_url")
    tier = agent_config.get("tier", config.tier)
    if hasattr(tier, "value"):
        tier = tier.value
    region = agent_config.get("region", config.region)

    while True:
        await asyncio.sleep(interval)
        try:
            await loop.run_in_executor(
                None, register_private_agent, agent_config, signing_key
            )
            logger.debug("Heartbeat re-registration succeeded")

            await record_heartbeat(
                agent_id=agent_id,
                agent_name=agent_name,
                company=company,
                service_url=service_url,
                public_url=public_url,
                tier=tier,
                region=region,
                ttl_seconds=ttl,
            )
        except Exception:
            logger.exception("Heartbeat re-registration failed")


def start_heartbeat(
    agent_config: dict[str, Any],
    signing_key: Ed25519PrivateKey | None = None,
) -> asyncio.Task:
    """Start the heartbeat background task. Must be called within a running event loop."""
    return asyncio.create_task(_heartbeat_loop(agent_config, signing_key))
