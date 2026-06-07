"""Global provider registry.

Call ``configure()`` once before ``GiuliaAgent.create_app()`` to override
any default GCP provider with an alternative implementation.

All getters (``get_secrets``, ``get_kms``, ``get_redis_auth``, ``get_database``)
auto-initialize to their GCP-backed defaults on first access if ``configure()``
was never called, ensuring full backward compatibility.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from giulia.providers.database import DatabaseConnector
    from giulia.providers.kms import KmsProvider
    from giulia.providers.redis_auth import RedisAuthProvider
    from giulia.providers.secrets import SecretsProvider

_secrets_provider: SecretsProvider | None = None
_kms_provider: KmsProvider | None = None
_redis_auth_provider: RedisAuthProvider | None = None
_database_provider: DatabaseConnector | None = None


def configure(
    *,
    secrets: SecretsProvider | None = None,
    kms: KmsProvider | None = None,
    redis_auth: RedisAuthProvider | None = None,
    database: DatabaseConnector | None = None,
) -> None:
    """Override one or more cloud provider implementations.

    Call this once at application startup, before ``GiuliaAgent.create_app()``.
    Any provider left as ``None`` retains its current value (or the GCP default
    if it has never been set).

    Args:
        secrets:    Provider for secret values (e.g. bearer tokens, OAuth secrets).
        kms:        Provider for JWT public-key retrieval.
        redis_auth: Provider for Redis authentication credentials.
        database:   Async PostgreSQL connector.

    Example::

        import giulia
        giulia.configure(
            secrets=giulia.providers.EnvSecretsProvider(),
            kms=giulia.providers.FileKmsProvider("/keys/jwt-public.pem"),
            redis_auth=giulia.providers.NoAuthRedisProvider(),
            database=giulia.providers.PostgresConnector(dsn="postgresql://..."),
        )
    """
    global _secrets_provider, _kms_provider, _redis_auth_provider, _database_provider
    if secrets is not None:
        _secrets_provider = secrets
    if kms is not None:
        _kms_provider = kms
    if redis_auth is not None:
        _redis_auth_provider = redis_auth
    if database is not None:
        _database_provider = database


def get_secrets() -> SecretsProvider:
    """Return the active secrets provider, defaulting to ``GcpSecretsProvider``."""
    global _secrets_provider
    if _secrets_provider is None:
        from giulia.providers.secrets import GcpSecretsProvider

        _secrets_provider = GcpSecretsProvider()
    return _secrets_provider


def get_kms() -> KmsProvider:
    """Return the active KMS provider, defaulting to ``GcpKmsProvider``."""
    global _kms_provider
    if _kms_provider is None:
        from giulia.providers.kms import GcpKmsProvider

        _kms_provider = GcpKmsProvider()
    return _kms_provider


def get_redis_auth() -> RedisAuthProvider:
    """Return the active Redis auth provider, defaulting to ``GcpIamRedisAuthProvider``."""
    global _redis_auth_provider
    if _redis_auth_provider is None:
        from giulia.providers.redis_auth import GcpIamRedisAuthProvider

        _redis_auth_provider = GcpIamRedisAuthProvider()
    return _redis_auth_provider


def get_database() -> DatabaseConnector:
    """Return the active database connector, defaulting to ``CloudSqlConnector``."""
    global _database_provider
    if _database_provider is None:
        from giulia.providers.database import CloudSqlConnector

        _database_provider = CloudSqlConnector()
    return _database_provider
