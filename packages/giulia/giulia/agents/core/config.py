from __future__ import annotations

import os
from functools import cached_property
from typing import Self

from pydantic import Field, model_validator

from giulia.config import DatabaseConfig


class Config(DatabaseConfig):
    """Environment-based configuration for agents.

    Extends ``DatabaseConfig`` (from ``giulia.config``) with agent-specific
    settings. The DB fields are inherited — no need to redefine them here.
    """

    # -----------------------------------------------------------------------
    # Registry
    # -----------------------------------------------------------------------
    registry_url: str = Field(
        default="registry.agents.svc.cluster.local",
        description=(
            "Registry host or full http(s) origin (see registry_http_origin). "
            "In Kubernetes this is often the in-cluster DNS name"
        ),
    )
    registry_call_base_url: str | None = Field(
        default=None,
        description=(
            "Optional override for outbound registry HTTP (registration, "
            "discovery, API-key checks). Use when REGISTRY_URL must stay as the "
            "in-cluster hostname but the process should call a tunneled or "
            "local endpoint (e.g. http://127.0.0.1:8080)."
        ),
    )

    # -----------------------------------------------------------------------
    # Network & Ports
    # -----------------------------------------------------------------------
    api_url: str = Field(
        default="http://api:8000",
        description=(
            "API service URL for Google Chat context storage and other "
            "public API calls. In Kubernetes this is the in-cluster DNS name."
        ),
    )
    agent_port: int = 8001
    agent_host: str = "0.0.0.0"

    # -----------------------------------------------------------------------
    # Signing Keys
    # -----------------------------------------------------------------------
    signing_key_path: str = Field(default="", alias="SIGNING_KEY")
    public_signing_key_path: str = Field(default="", alias="PUBLIC_SIGNING_KEY")

    # -----------------------------------------------------------------------
    # Agent Metadata & Deployment
    # -----------------------------------------------------------------------
    deploy: bool = Field(
        default=True,
        description="Whether CI/CD should deploy this agent. Set to False to skip deployment.",
    )
    default_ttl: int = 900
    tier: str = Field(default="private", alias="AGENT_TIER")
    region: str = Field(default="europe-west1", alias="AGENT_REGION")
    service_name: str = Field(default="email-agent")
    namespace: str = Field(default="default")
    k8s_namespace: str = Field(default="agents", alias="K8S_NAMESPACE")
    google_cloud_project: str = Field(alias="GOOGLE_CLOUD_PROJECT")

    # -----------------------------------------------------------------------
    # A2A & External Auth
    # -----------------------------------------------------------------------
    a2a_client_id_secret: str = Field(
        default="",
        alias="A2A_CLIENT_ID_SECRET",
        description="GCP Secret path for A2A client ID. If empty, computed from google_cloud_project.",
    )
    a2a_client_secret_secret: str = Field(
        default="",
        alias="A2A_CLIENT_SECRET_SECRET",
        description="GCP Secret path for A2A client secret. If empty, computed from google_cloud_project.",
    )
    google_oauth_client_id: str = Field(default="", alias="GOOGLE_OAUTH_CLIENT_ID")

    # -----------------------------------------------------------------------
    # KMS
    # -----------------------------------------------------------------------
    kms_region: str = Field(default="europe-west1", alias="KMS_REGION")
    kms_key_ring: str = Field(default="", alias="KMS_KEY_RING")
    kms_key_name: str = Field(default="", alias="KMS_KEY_NAME")
    kms_key_version: str = Field(default="1", alias="KMS_KEY_VERSION")
    # Expected JWT issuer claim. Set to empty string to skip issuer validation.
    jwt_issuer: str = Field(default="", alias="JWT_ISSUER")
    # -----------------------------------------------------------------------
    # Memorystore / Redis
    # -----------------------------------------------------------------------
    memorystore_host: str = Field(default="", alias="MEMORYSTORE_HOST")
    memorystore_port: int = Field(default=6379, alias="MEMORYSTORE_PORT")
    memorystore_iam_username: str = Field(
        default="default", alias="MEMORYSTORE_IAM_USERNAME"
    )

    # -----------------------------------------------------------------------
    # Auth Trigger
    # -----------------------------------------------------------------------
    internal_trigger_path: str = Field(default="", alias="INTERNAL_TRIGGER_PATH")
    internal_trigger_secret: str = Field(default="", alias="INTERNAL_TRIGGER_SECRET")

    # -----------------------------------------------------------------------
    # Registration & Secrets
    # -----------------------------------------------------------------------
    bearer_token_secret_name: str = Field(
        default="gloria-master-key", alias="BEARER_TOKEN_SECRET_NAME"
    )

    # -----------------------------------------------------------------------
    # Telemetry
    # -----------------------------------------------------------------------
    agent_urn: str = Field(default="gloria-agent", alias="AGENT_URN")
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )

    @model_validator(mode="after")
    def _fill_secret_paths(self) -> Self:
        if not self.a2a_client_id_secret:
            raise ValueError("A2A client id secret is required")
        if not self.a2a_client_secret_secret:
            raise ValueError("A2A client secret secret is required")
        return self

    @model_validator(mode="after")
    def _force_google_genai_vertex_ai_env(self) -> Self:
        """google.genai enables Vertex only via ``GOOGLE_GENAI_USE_VERTEXAI`` in os.environ."""
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
        return self

    @cached_property
    def registry_http_origin(self) -> str:
        return self.registry_call_base_url or f"http://{self.registry_url}"

    @cached_property
    def service_url(self) -> str:
        return f"http://{self.service_name}.{self.k8s_namespace}.svc.cluster.local:{self.agent_port}"


# Global instance of the configuration.
# pydantic-settings will load values from environment variables and .env file.
config = Config()  # type: ignore[call-arg]
