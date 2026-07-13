"""
Cloud Function triggered by Pub/Sub to log LLM consumption data to BigQuery.

Receives messages containing: api_key, model, input_tokens, output_tokens,
thinking_tokens, request_id, cache_creation_input_tokens,
cache_read_input_tokens, date.

Required environment variable:
    BQ_TABLE – Fully-qualified BigQuery table (project.dataset.table).
"""

import base64
import json
import logging
import os

import functions_framework
from cloudevents.http import CloudEvent
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("llm-consumption-logger")

_bq_client: bigquery.Client | None = None


def _get_bq_client() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client()
    return _bq_client


@functions_framework.cloud_event
def log_consumption(cloud_event: CloudEvent) -> None:
    """Entry point: decode the Pub/Sub message and insert a row into BigQuery."""
    bq_table = os.environ.get("BQ_TABLE", "").strip()
    if not bq_table:
        raise RuntimeError(
            "BQ_TABLE environment variable is not set. "
            "Expected format: project.dataset.table"
        )

    raw = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
    payload = json.loads(raw)

    api_key = payload.get("api_key", "unknown")
    model = payload.get("model", "unknown")
    input_tokens = payload.get("input_tokens", 0)
    output_tokens = payload.get("output_tokens", 0)
    thinking_tokens = payload.get("thinking_tokens", 0)
    request_id = payload.get("request_id", "")
    cache_creation_input_tokens = payload.get("cache_creation_input_tokens", 0)
    cache_read_input_tokens = payload.get("cache_read_input_tokens", 0)
    date = payload.get("date")

    if not date:
        logger.error("Missing 'date' in payload, skipping insert")
        return

    row = {
        "api_key": api_key,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "thinking_tokens": thinking_tokens,
        "request_id": request_id,
        "cache_creation_input_tokens": cache_creation_input_tokens,
        "cache_read_input_tokens": cache_read_input_tokens,
        "date": date,
    }

    client = _get_bq_client()
    errors = client.insert_rows_json(bq_table, [row])

    if errors:
        logger.error("BigQuery insert errors: %s", errors)
        raise RuntimeError(f"BigQuery insert failed: {errors}")

    logger.info(
        "Logged consumption: req=%s model=%s in=%d out=%d thinking=%d cache_write=%d cache_read=%d api_key=%s",
        request_id,
        model,
        input_tokens,
        output_tokens,
        thinking_tokens,
        cache_creation_input_tokens,
        cache_read_input_tokens,
        api_key[:8] + "***",
    )
