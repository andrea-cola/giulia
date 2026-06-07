"""KMS provider protocol and built-in implementations.

Providers
---------
- ``GcpKmsProvider``    — Google Cloud KMS (default)
- ``FileKmsProvider``   — reads a PEM public key from disk
- ``StaticKmsProvider`` — takes a PEM string directly (useful for tests)
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class KmsProvider(Protocol):
    """Structural protocol for fetching public keys used for JWT verification.

    The *key_ref* semantics are implementation-defined:
    - For GCP: a full KMS crypto key version resource name
    - For file: a file path
    - For static: ignored (a single key is pre-loaded)
    """

    def get_public_key_pem(self, key_ref: str) -> str:
        """Return the RSA/EC public key as a PEM-encoded string.

        Raises:
            RuntimeError: if the key cannot be loaded.
        """
        ...


class GcpKmsProvider:
    """Fetch public keys from Google Cloud KMS.

    This is the default provider; requires ``google-cloud-kms``.

    *key_ref* must be a full GCP KMS resource path, e.g.::

        projects/my-project/locations/global/keyRings/my-ring/
        cryptoKeys/my-key/cryptoKeyVersions/1
    """

    def get_public_key_pem(self, key_ref: str) -> str:
        try:
            from google.cloud import kms  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "google-cloud-kms is required for GcpKmsProvider. "
                "Install it with: pip install google-cloud-kms"
            ) from exc

        client = kms.KeyManagementServiceClient()
        try:
            response = client.get_public_key(request={"name": key_ref})
            return response.pem
        except Exception as exc:
            raise RuntimeError(
                f"Failed to fetch public key {key_ref!r} from GCP KMS: {exc}"
            ) from exc


class FileKmsProvider:
    """Read a PEM public key from a file on disk.

    Useful for local development or any environment where the public key is
    distributed as a file (e.g. a Kubernetes secret mounted at a known path).

    *key_ref* passed to ``get_public_key_pem`` is ignored when a *default_path*
    is provided at construction time; otherwise *key_ref* is treated as the
    file path.

    Example::

        provider = FileKmsProvider("/etc/keys/jwt-public.pem")
        pem = provider.get_public_key_pem("")  # path from constructor

        provider = FileKmsProvider()
        pem = provider.get_public_key_pem("/etc/keys/jwt-public.pem")
    """

    def __init__(self, default_path: str | Path | None = None) -> None:
        self._default_path = Path(default_path) if default_path else None

    def get_public_key_pem(self, key_ref: str) -> str:
        path = self._default_path or Path(key_ref)
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Failed to read public key from {path}: {exc}") from exc


class StaticKmsProvider:
    """Return a fixed PEM public key string.

    Intended for testing or environments where the public key is known at
    configuration time.

    *key_ref* passed to ``get_public_key_pem`` is ignored.

    Example::

        provider = StaticKmsProvider(pem="-----BEGIN PUBLIC KEY-----\\n...")
    """

    def __init__(self, pem: str) -> None:
        self._pem = pem

    def get_public_key_pem(self, key_ref: str) -> str:  # noqa: ARG002
        return self._pem
