"""
Publishes LLM consumption events to a Pub/Sub topic for downstream
logging into BigQuery.

Usage (async, from FastAPI app.py):
    from giulia_gateway.publisher import publish_consumption
    await publish_consumption(api_key="...", model="...", input_tokens=123)

Usage (sync):
    from giulia_gateway.publisher import publish_consumption_sync
    publish_consumption_sync(api_key="...", model="...", input_tokens=123)

Required environment variables:
    GCP_PROJECT  – GCP project ID (or VERTEX_PROJECT as alias).
    PUBSUB_TOPIC – Pub/Sub topic name for consumption events.
"""

import json
import os
from datetime import UTC, datetime

from google.cloud import pubsub_v1

from giulia_gateway.logging_config import get_logger

logger = get_logger("publisher")


def _require_env(*names: str) -> str:
    """Return the first set environment variable from *names*, or raise."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise RuntimeError(
        f"At least one of {', '.join(names)} must be set. "
        f"See giulia_gateway README for configuration."
    )


_publisher: pubsub_v1.PublisherClient | None = None


def _get_publisher() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def _build_message(
    api_key: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    thinking_tokens: int,
    request_id: str,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> bytes:
    payload = {
        "api_key": api_key,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "thinking_tokens": thinking_tokens,
        "request_id": request_id,
        "cache_creation_input_tokens": cache_creation_input_tokens,
        "cache_read_input_tokens": cache_read_input_tokens,
        "date": datetime.now(UTC).isoformat(),
    }
    return json.dumps(payload).encode("utf-8")


def publish_consumption_sync(
    api_key: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    thinking_tokens: int = 0,
    request_id: str = "",
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> None:
    """Publish a consumption message synchronously."""
    try:
        project_id = _require_env("VERTEX_PROJECT", "GCP_PROJECT")
        topic_id = _require_env("PUBSUB_TOPIC")
        publisher = _get_publisher()
        topic_path = publisher.topic_path(project_id, topic_id)
        data = _build_message(
            api_key,
            model,
            input_tokens,
            output_tokens,
            thinking_tokens,
            request_id,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
        )
        future = publisher.publish(topic_path, data)
        future.result(timeout=5)
        logger.info(
            "Published consumption: req=%s model=%s in=%d out=%d thinking=%d cache_write=%d cache_read=%d",
            request_id,
            model,
            input_tokens,
            output_tokens,
            thinking_tokens,
            cache_creation_input_tokens,
            cache_read_input_tokens,
        )
    except Exception:
        logger.exception("Failed to publish consumption event")


async def publish_consumption(
    api_key: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    thinking_tokens: int = 0,
    request_id: str = "",
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> None:
    """Publish a consumption message (fire-and-forget from async context)."""
    import asyncio
    from functools import partial

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        partial(
            publish_consumption_sync,
            api_key=api_key,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thinking_tokens=thinking_tokens,
            request_id=request_id,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
        ),
    )
