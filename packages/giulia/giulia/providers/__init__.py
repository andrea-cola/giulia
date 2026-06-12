"""Cloud provider abstraction layer for giulia.

All GCP-specific services (Secret Manager, KMS, Cloud SQL, Redis IAM auth) are
accessed through provider protocols defined in this package.  Call ``configure()``
once at application startup to swap in non-GCP implementations; if you never call
it every provider defaults to its GCP-backed implementation so existing users are
not affected.

Example — local / non-GCP setup::

    import giulia
    giulia.configure(
        secrets=giulia.providers.EnvSecretsProvider(),
        kms=giulia.providers.FileKmsProvider("/path/to/public.pem"),
        redis_auth=giulia.providers.NoAuthRedisProvider(),
        database=giulia.providers.PostgresConnector(dsn="postgresql://user:pw@localhost/db"),
    )

Example — GCP (default, explicit)::

    import giulia
    giulia.configure(
        secrets=giulia.providers.GcpSecretsProvider(),
        kms=giulia.providers.GcpKmsProvider(),
        redis_auth=giulia.providers.GcpIamRedisAuthProvider(),
        database=giulia.providers.CloudSqlConnector(),
    )
"""

from __future__ import annotations

from giulia.providers.database import (
    CloudSqlConnector,
    DatabaseConnector,
    PostgresConnector,
)
from giulia.providers.kms import (
    FileKmsProvider,
    GcpKmsProvider,
    KmsProvider,
    StaticKmsProvider,
)
from giulia.providers.redis_auth import (
    GcpIamRedisAuthProvider,
    NoAuthRedisProvider,
    PasswordRedisAuthProvider,
    RedisAuthProvider,
)
from giulia.providers.registry import (
    configure,
    get_database,
    get_kms,
    get_redis_auth,
    get_secrets,
)
from giulia.providers.secrets import (
    EnvSecretsProvider,
    GcpSecretsProvider,
    SecretNotFoundError,
    SecretsProvider,
)

__all__ = [
    # registry
    "configure",
    "get_secrets",
    "get_kms",
    "get_redis_auth",
    "get_database",
    # secrets
    "SecretsProvider",
    "SecretNotFoundError",
    "GcpSecretsProvider",
    "EnvSecretsProvider",
    # kms
    "KmsProvider",
    "GcpKmsProvider",
    "FileKmsProvider",
    "StaticKmsProvider",
    # redis auth
    "RedisAuthProvider",
    "GcpIamRedisAuthProvider",
    "NoAuthRedisProvider",
    "PasswordRedisAuthProvider",
    # database
    "DatabaseConnector",
    "CloudSqlConnector",
    "PostgresConnector",
]
