"""Factory helpers for A2A agents that talk to the Datwave registry with OAuth.

This module exposes two main entry points.

create_a2a_registry_oauth_async_client builds an authenticated httpx.AsyncClient.
Specify credentials in exactly one way (never mix):

You may override oauth_token_url and oauth_scope; HTTP timeout defaults to 300 seconds.

Example:

    from giulia.agents.a2a.a2a_agent_factory import (
        create_a2a_registry_oauth_async_client,
        remote_a2a_agent_from_registry,
    )

    client = create_a2a_registry_oauth_async_client(
        client_id_env="A2A_OAUTH_CLIENT_ID",
        client_secret_env="A2A_OAUTH_CLIENT_SECRET",
    )

    remote = await remote_a2a_agent_from_registry(
        "urn:agent:giulia:public:sophia",
        client,
    )

Internal registry resolution (resolve_agent) uses Datwave configuration separately from
OAuth; both must be valid for your deployment. The default OAuth token URL is derived from
``Config.registry_http_origin`` (``REGISTRY_CALL_BASE_URL`` when set, otherwise in-cluster).

resolve_oauth_client_credentials returns the (client_id, client_secret) tuple using the
same env-versus-Secret-Manager rules if you need credentials without building a client.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

import httpx
from a2a.types import AgentCard

from giulia.agents.core import config as _registry_runtime_config
from giulia.agents.registry_client import resolve_agent
from giulia.agents.utils import urn_to_python_identifier

logger = logging.getLogger(__name__)

_DEFAULT_OAUTH_SCOPE = "agent:invoke"


def get_a2a_client_factory() -> Callable[[], httpx.AsyncClient]:
    """Returns a factory that builds an authenticated A2A client using default secrets."""

    def factory() -> httpx.AsyncClient:
        # Import config here to avoid early validation issues
        from giulia.agents.core import config

        return create_a2a_registry_oauth_async_client(
            client_id_secret_resource=config.a2a_client_id_secret,
            client_secret_secret_resource=config.a2a_client_secret_secret,
        )

    return factory


def _origin_host_is_loopback(origin: str) -> bool:
    """True when *origin* points at loopback (typical registry port-forward / local registry)."""
    try:
        host = (urlparse(origin).hostname or "").lower()
    except ValueError:
        return False
    return host in ("localhost", "127.0.0.1", "::1")


def _default_registry_oauth_token_url() -> str:
    """Registry OAuth token endpoint from ``registry_http_origin`` (tunnel or in-cluster)."""
    base = _registry_runtime_config.registry_http_origin.rstrip("/")
    return f"{base}/registry/api/v1/oauth/token"


def resolve_oauth_client_credentials(
    *,
    client_id_env: str | None = None,
    client_secret_env: str | None = None,
    client_id_secret_resource: str | None = None,
    client_secret_secret_resource: str | None = None,
) -> tuple[str, str]:
    """Load OAuth client id and secret for the Datwave registry token endpoint.

    Supply either:

    - client_id_env and client_secret_env: names of environment variables whose values are
      the id and secret, or
    - client_id_secret_resource and client_secret_secret_resource: GCP Secret Manager
      version resource names, for example projects/PROJ/secrets/NAME/versions/latest.

    Do not mix the two modes.

    Returns:
        A (client_id, client_secret) tuple of strings.

    Raises:
        ValueError: Invalid combination of arguments, unset env vars, or empty values.
    """
    env_requested = client_id_env is not None or client_secret_env is not None
    sm_requested = (
        client_id_secret_resource is not None
        or client_secret_secret_resource is not None
    )

    if env_requested and sm_requested:
        raise ValueError(
            "Use either env variable names "
            "(client_id_env / client_secret_env) or GCP secret resources "
            "(client_id_secret_resource / client_secret_secret_resource), not both."
        )

    if env_requested:
        if not (client_id_env and client_secret_env):
            raise ValueError(
                "Both client_id_env and client_secret_env must be set when using env."
            )
        try:
            client_id_raw = os.environ[client_id_env]
            secret_raw = os.environ[client_secret_env]
        except KeyError as e:
            missing = e.args[0]
            raise ValueError(
                f"Missing environment variable {missing!r} for A2A OAuth credentials "
                "(env mode)."
            ) from e
        client_id, secret = client_id_raw.strip(), secret_raw.strip()
        if not client_id or not secret:
            raise ValueError(
                "OAuth client id and secret from env must be non-empty (env mode)."
            )
        return client_id, secret

    if sm_requested:
        if not (client_id_secret_resource and client_secret_secret_resource):
            raise ValueError(
                "Both client_id_secret_resource and client_secret_secret_resource "
                "must be set when using the secrets provider."
            )
        from giulia.providers.registry import get_secrets

        secrets = get_secrets()
        cid = secrets.get_secret(client_id_secret_resource).strip()
        csec = secrets.get_secret(client_secret_secret_resource).strip()
        if not cid or not csec:
            raise ValueError(
                "OAuth client id and secret from secrets provider must be non-empty."
            )
        return cid, csec

    raise ValueError(
        "Provide either (client_id_env, client_secret_env) or "
        "(client_id_secret_resource, client_secret_secret_resource)."
    )


class RegistryA2AOAuth2Auth(httpx.Auth):
    """OAuth2 client credentials flow for the Datwave registry agent:invoke scope."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        token_url: str | None = None,
        oauth_scope: str = _DEFAULT_OAUTH_SCOPE,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url or _default_registry_oauth_token_url()
        self._oauth_scope = oauth_scope
        self._token: str | None = None
        self._expires_at: float = 0.0

    def _is_expired(self) -> bool:
        return time.monotonic() >= self._expires_at - 30

    async def _refresh_token(self) -> None:
        response: httpx.Response | None = None
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.post(
                    self._token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "scope": self._oauth_scope,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                self._token = payload["access_token"]
                self._expires_at = time.monotonic() + payload.get("expires_in", 3600)
        except Exception as e:
            logger.error("Failed to refresh A2A registry OAuth token: %s", e)
            if response is not None:
                try:
                    logger.error("OAuth token response JSON: %s", response.json())
                except ValueError:
                    logger.error("OAuth token response text: %s", response.text)
            raise

    async def async_auth_flow(self, request):
        if self._token is None or self._is_expired():
            await self._refresh_token()
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request


def create_a2a_registry_oauth_async_client(
    *,
    oauth_token_url: str | None = None,
    oauth_scope: str = _DEFAULT_OAUTH_SCOPE,
    timeout: float = 300.0,
    client_id_env: str | None = None,
    client_secret_env: str | None = None,
    client_id_secret_resource: str | None = None,
    client_secret_secret_resource: str | None = None,
) -> httpx.AsyncClient:
    """Construct an httpx.AsyncClient with registry OAuth2 for A2A (for example agent card GET).

    Credentials come from resolve_oauth_client_credentials: either environment variable
    names or GCP Secret Manager version resource paths.

    Args:
        oauth_token_url: OAuth2 token endpoint; default uses ``registry_http_origin``.
        oauth_scope: OAuth2 scope for the client credentials grant.
        timeout: Async client timeout in seconds.
        client_id_env: Name of the env var holding the OAuth client id (use with
            client_secret_env).
        client_secret_env: Name of the env var holding the OAuth client secret.
        client_id_secret_resource: GCP secret version resource for the client id.
        client_secret_secret_resource: GCP secret version resource for the client secret.
    """
    token_url = oauth_token_url or _default_registry_oauth_token_url()
    client_id, client_secret = resolve_oauth_client_credentials(
        client_id_env=client_id_env,
        client_secret_env=client_secret_env,
        client_id_secret_resource=client_id_secret_resource,
        client_secret_secret_resource=client_secret_secret_resource,
    )
    return httpx.AsyncClient(
        auth=RegistryA2AOAuth2Auth(
            client_id,
            client_secret,
            token_url=token_url,
            oauth_scope=oauth_scope,
        ),
        timeout=timeout,
        trust_env=False,
    )


async def resolve_agent_base_url(agent_id: str) -> str:
    """Resolve an agent's private base URL from the registry without constructing a RemoteA2aAgent.

    Useful when you need just the base URL to make direct HTTP calls, bypassing the
    ADK RemoteA2aAgent entirely (which avoids version-specific attribute compatibility issues).

    Args:
        agent_id: Registry identifier, e.g. urn:agent:giulia:public:sophia.

    Returns:
        The private base URL string (e.g. http://localhost:8002).

    Raises:
        ValueError: Missing registry row, absent or malformed private_facts_url.
    """
    registry_entry = await resolve_agent(agent_id)
    if registry_entry is None:
        raise ValueError(f"Registry entry not found for {agent_id}")

    private_facts_url = registry_entry.get("private_facts_url") or ""
    if not private_facts_url.strip():
        raise ValueError(f"Registry entry for {agent_id} has no private_facts_url")

    if "/.well-known/" not in private_facts_url:
        raise ValueError(
            f"private_facts_url missing /.well-known/ segment: {private_facts_url!r} "
            f"(agent_id={agent_id})"
        )
    base_and_rest = private_facts_url.rsplit("/.well-known/", 1)
    if len(base_and_rest) != 2 or not base_and_rest[0]:
        raise ValueError(
            f"Could not derive base URL from private_facts_url: {private_facts_url!r} "
            f"(agent_id={agent_id})"
        )
    return base_and_rest[0]


async def remote_a2a_agent_from_registry(
    agent_id: str,
    httpx_client: httpx.AsyncClient,
    *,
    remote_name: str | None = None,
    with_private_base_url: bool = True,
    httpx_client_for_agent: httpx.AsyncClient | None = None,
) -> Any:
    """Resolve an agent id via the registry and build RemoteA2aAgent.

    Uses ``resolve_agent_base_url`` (registry metadata via ``resolve_agent``) for the
    private base URL. Fetches ``agent-card.json`` only via the registry well-known proxy
    on ``registry_http_origin`` — the same path the Gloria registry exposes in
    ``registry/app.py`` — so callers never open ``private_facts_url`` directly.

    When ``registry_http_origin`` is loopback (port-forward / local registry), the card's
    existing ``url`` is kept so A2A can use the public endpoint from the JSON.

    Args:
        agent_id: Registry identifier, typically a URN such as urn:agent:giulia:public:sophia.
        httpx_client: Async client used to GET the agent card (including auth the registry needs).
        remote_name: name passed to RemoteA2aAgent; defaults to the last URN segment.
        with_private_base_url: if True, set the card ``url`` to the private base when appropriate.
        httpx_client_for_agent: optional client passed to RemoteA2aAgent. If None,
            uses httpx_client.

    Returns:
        RemoteA2aAgent for the resolved endpoint.

    Raises:
        ValueError: Missing registry row, absent or malformed private_facts_url, or invalid
            agent card JSON or type.
        httpx.HTTPError: Failed HTTP response after raise_for_status.

    Requires:
        google-adk (giulia optional extra giulia[adk] or a direct dependency).
    """
    from google.adk.agents.remote_a2a_agent import RemoteA2aAgent

    private_base_url = await resolve_agent_base_url(agent_id)

    registry_origin = _registry_runtime_config.registry_http_origin.rstrip("/")
    is_loopback = _origin_host_is_loopback(registry_origin)

    if is_loopback:
        # In local/port-forward setups the registry proxy endpoint returns 500
        # because the registry tries to reach the agent's public URL from inside
        # the cluster. Fetch the card directly from the agent instead.
        fetch_url = f"{private_base_url}/.well-known/agent-card.json"
        logger.debug(
            "Fetching agent card for %s directly from agent at %s (loopback registry)",
            agent_id,
            fetch_url,
        )
        try:
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as plain_client:
                agent_card_response = await plain_client.get(fetch_url)
                agent_card_response.raise_for_status()
        except httpx.HTTPError:
            logger.exception(
                "Failed to fetch agent card for %s from %s",
                agent_id,
                fetch_url,
            )
            raise
    else:
        fetch_url = (
            f"{registry_origin}/registry/api/v1/agents/"
            f"{agent_id}/.well-known/agent-card.json"
        )
        logger.debug("Fetching agent card for %s from registry %s", agent_id, fetch_url)
        try:
            agent_card_response = await httpx_client.get(fetch_url)
            agent_card_response.raise_for_status()
        except httpx.HTTPError:
            logger.exception(
                "Failed to fetch agent card for %s from %s",
                agent_id,
                fetch_url,
            )
            raise

    try:
        payload = agent_card_response.json()
    except ValueError as e:
        raise ValueError(
            f"Agent card at {fetch_url} is not valid JSON (agent_id={agent_id})"
        ) from e
    if not isinstance(payload, dict):
        raise ValueError(
            f"Agent card at {fetch_url} must be a JSON object, "
            f"got {type(payload).__name__} (agent_id={agent_id})"
        )

    agent_card = payload

    if with_private_base_url:
        # Always override url to private_base_url so A2A calls stay local/internal.
        # In loopback (local dev) this routes to localhost:<port> instead of the
        # public cloud URL that the agent card contains.
        agent_card["url"] = private_base_url

    agent_card.pop("signatures", None)
    resolved_name = (
        remote_name if remote_name is not None else urn_to_python_identifier(agent_id)
    )

    logger.debug("Loaded agent card for %s from %s", agent_id, fetch_url)

    card = AgentCard.model_validate(agent_card)
    return RemoteA2aAgent(
        name=resolved_name,
        agent_card=card,
        httpx_client=httpx_client_for_agent if httpx_client_for_agent else httpx_client,
    )


def materialize_remote_a2a_peer_sync(
    peer_urn: str,
    httpx_client: httpx.AsyncClient | Callable[[], httpx.AsyncClient],
    *,
    remote_name: str | None = None,
) -> Any:
    """Resolve *peer_urn* from the registry and return ``RemoteA2aAgent`` (import-safe).

    Retries on missing registry rows or transient errors (usually when the agents
    are being deployed for the same time). Uses ``asyncio.run`` when no event loop is running, otherwise
    a one-thread pool (safe under uvicorn import).

    Args:
        peer_urn: Registry identifier, typically a URN.
        httpx_client: Async client or factory used to GET the agent card from the registry.
        remote_name: name passed to RemoteA2aAgent; defaults to the last URN segment.

    Env:
        A2A_PEER_REGISTRY_RETRY_MAX — attempts (default 10, minimum 1).
        A2A_PEER_REGISTRY_RETRY_DELAY_S — seconds between attempts (default 10).
    """
    try:
        raw_max = os.environ.get("A2A_PEER_REGISTRY_RETRY_MAX", 10)
        max_attempts = max(1, int(raw_max))
    except ValueError:
        max_attempts = 10
    try:
        raw_delay = os.environ.get("A2A_PEER_REGISTRY_RETRY_DELAY_S", 10)
        delay_s = max(0.0, float(raw_delay))
    except ValueError:
        delay_s = 10.0

    if isinstance(httpx_client, httpx.AsyncClient):
        client = httpx_client
    else:
        client = httpx_client()

    def _run_once() -> Any:
        return asyncio.run(
            remote_a2a_agent_from_registry(peer_urn, client, remote_name=remote_name)
        )

    def _materialize_once() -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return _run_once()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_run_once).result()

    last: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return _materialize_once()
        except ValueError as e:
            last = e
            msg = str(e)
            if "Registry entry not found" in msg or "not found for" in msg:
                logger.warning(
                    "A2A peer not in registry (%s/%s) for %s: %s",
                    attempt,
                    max_attempts,
                    peer_urn,
                    e,
                )
            else:
                logger.warning(
                    "A2A peer resolve ValueError (%s/%s) for %s: %s",
                    attempt,
                    max_attempts,
                    peer_urn,
                    e,
                )
        except Exception as e:
            last = e
            logger.warning(
                "A2A peer materialize failed (%s/%s) for %s: %s",
                attempt,
                max_attempts,
                peer_urn,
                e,
            )

        if attempt < max_attempts:
            time.sleep(delay_s)
        else:
            if last is None:
                raise RuntimeError(
                    f"A2A peer materialize exhausted retries for {peer_urn} without exception"
                )
            raise last
