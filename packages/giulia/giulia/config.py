"""Shared database configuration for giulia.

This module intentionally has no dependencies on ``giulia.agents`` so that
``giulia.sql`` can import it without triggering any circular import chain.
``giulia.agents.core.config.Config`` inherits from this class and extends it
with agent-specific settings.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseSettings):
    """Minimal pydantic-settings class covering Cloud SQL / DB knobs only."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -----------------------------------------------------------------------
    # Database
    # -----------------------------------------------------------------------
    db_instance: str = Field(alias="DB_INSTANCE")
    db_name: str = Field(default="brain", alias="DB_NAME")
    db_user: str = Field(alias="DB_USER")  # must be set — no project-specific default
    db_ip_type: str = Field(default="private", alias="DB_IP_TYPE")
    db_min_pool: int = Field(default=1, alias="DB_MIN_POOL")
    db_max_pool: int = Field(default=5, alias="DB_MAX_POOL")


def _find_dotenv() -> Path | None:
    """Walk up from cwd looking for a .env file (mirrors load_dotenv behaviour)."""
    cwd = Path.cwd()
    for directory in [cwd, *cwd.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = _find_dotenv()
    if env_path:
        load_dotenv(env_path, override=False)


_load_dotenv()

_db_config_instance: DatabaseConfig | None = None


def _get_db_config() -> DatabaseConfig:
    """Return the singleton DatabaseConfig, instantiating it on first call."""
    global _db_config_instance
    if _db_config_instance is None:
        _db_config_instance = DatabaseConfig()  # type: ignore[call-arg]
    return _db_config_instance


class _DbConfigProxy:
    """Lazy proxy so callers can still write ``from giulia.config import db_config``."""

    def __getattr__(self, name: str) -> object:
        return getattr(_get_db_config(), name)


db_config: DatabaseConfig = _DbConfigProxy()  # type: ignore[assignment]
