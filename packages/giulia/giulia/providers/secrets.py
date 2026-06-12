"""Secrets provider protocol and built-in implementations.

Providers
---------
- ``GcpSecretsProvider``  — Google Cloud Secret Manager (default)
- ``EnvSecretsProvider``  — reads from environment variables
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable


class SecretNotFoundError(Exception):
    """Raised when a secret cannot be found or accessed."""


@runtime_checkable
class SecretsProvider(Protocol):
    """Structural protocol for fetching secrets.

    The *secret_id* semantics are implementation-defined:
    - For GCP: a full resource name like
      ``projects/my-project/secrets/my-secret/versions/latest``
    - For env: the name of an environment variable
    """

    def get_secret(self, secret_id: str) -> str:
        """Return the secret value as a plain string.

        Raises:
            SecretNotFoundError: if the secret cannot be found or accessed.
        """
        ...


class GcpSecretsProvider:
    """Fetch secrets from Google Cloud Secret Manager.

    This is the default provider; requires ``google-cloud-secret-manager``.

    *secret_id* must be a full GCP resource path, e.g.::

        projects/my-project/secrets/my-secret/versions/latest
    """

    def get_secret(self, secret_id: str) -> str:
        try:
            from google.cloud import secretmanager  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "google-cloud-secret-manager is required for GcpSecretsProvider. "
                "Install it with: pip install google-cloud-secret-manager"
            ) from exc

        client = secretmanager.SecretManagerServiceClient()
        try:
            response = client.access_secret_version(request={"name": secret_id})
            return response.payload.data.decode("UTF-8")
        except Exception as exc:
            raise SecretNotFoundError(
                f"Failed to fetch secret {secret_id!r} from GCP Secret Manager: {exc}"
            ) from exc


class EnvSecretsProvider:
    """Fetch secrets from environment variables.

    Useful for local development, testing, or non-GCP deployments.

    *secret_id* is the name of an environment variable, e.g. ``MY_SECRET``.
    For compatibility with GCP-style resource paths, if the value contains
    ``/`` the last segment before ``/versions/`` is used as the variable name::

        # "projects/proj/secrets/MY_SECRET/versions/latest" → env var MY_SECRET
    """

    def get_secret(self, secret_id: str) -> str:
        env_var = self._resolve_env_var_name(secret_id)
        value = os.environ.get(env_var)
        if value is None:
            raise SecretNotFoundError(
                f"Environment variable {env_var!r} is not set "
                f"(resolved from secret_id={secret_id!r})"
            )
        return value

    @staticmethod
    def _resolve_env_var_name(secret_id: str) -> str:
        """Extract env var name from a GCP resource path or return as-is."""
        if "/" not in secret_id:
            return secret_id
        # projects/PROJ/secrets/NAME/versions/VER → NAME
        parts = secret_id.split("/")
        try:
            secrets_idx = parts.index("secrets")
            return parts[secrets_idx + 1]
        except (ValueError, IndexError):
            return secret_id
