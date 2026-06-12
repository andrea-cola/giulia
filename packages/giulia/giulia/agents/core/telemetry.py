"""OpenTelemetry tracing setup for agent calls."""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from giulia.agents.core.config import config

logger = logging.getLogger(__name__)

_tracer = None


def init_telemetry(service_name: str | None = None):
    """
    Initialize OpenTelemetry tracing.
    Exports to the OTLP endpoint configured via config.
    Falls back to console exporter if no endpoint is configured.
    """
    global _tracer
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )

        resource = Resource.create({"service.name": service_name or config.agent_urn})
        provider = TracerProvider(resource=resource)

        otlp_endpoint = config.otel_exporter_otlp_endpoint
        if otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        else:
            exporter = ConsoleSpanExporter()

        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("giulia")
        logger.info("OpenTelemetry tracing initialized for %s", service_name)
    except ImportError:
        logger.warning(
            "OpenTelemetry packages not installed. Tracing disabled. "
            "Install with: uv pip install opentelemetry-api opentelemetry-sdk "
            "opentelemetry-exporter-otlp-proto-grpc"
        )


@contextmanager
def trace_span(
    name: str, attributes: dict[str, Any] | None = None
) -> Generator[Any, None, None]:
    """Create a trace span for an operation. No-op if telemetry is not initialized."""
    if _tracer is None:
        yield None
        return

    with _tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, str(v))
        yield span


def trace_a2a_call(caller: str, target: str, capability: str):
    """Create a trace span specifically for an A2A agent-to-agent call."""
    return trace_span(
        f"a2a.call.{capability}",
        attributes={
            "a2a.caller": caller,
            "a2a.target": target,
            "a2a.capability": capability,
        },
    )


def trace_index_query(capability: str | None = None, region: str | None = None):
    """Create a trace span for an internal index query."""
    attrs: dict[str, Any] = {}
    if capability:
        attrs["index.capability"] = capability
    if region:
        attrs["index.region"] = region
    return trace_span("registry.index.query", attributes=attrs)
