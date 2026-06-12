"""Datwave GCS Artifact Service.

Implements a hierarchical folder structure for artifacts in GCS:

    {process_id}/{task_id}/{agent_id}/{filename}/{version}

``process_id`` is read from ``giulia.agents.context.current_process_id``, which
is set at the inbound delegation entry point.  ``session_id`` (from ADK) is used
as ``task_id``.  The legacy ``"process_id:task_id"`` format in ``session_id`` is
still accepted for backward compatibility but should not be used in new code.
"""

from __future__ import annotations

import logging
from typing import Any, override

from google.adk.artifacts.gcs_artifact_service import GcsArtifactService
from google.genai import types

logger = logging.getLogger("giulia." + __name__)


class DatwaveGcsArtifactService(GcsArtifactService):
    """GCS Artifact Service with Datwave-specific folder structure.

    Path layout: ``{process_id}/{task_id}/{app_name}/{filename}/{version}``
    """

    def __init__(self, bucket_name: str, **kwargs: Any) -> None:
        super().__init__(bucket_name=bucket_name, **kwargs)

    # ── Public interface (make user_id optional everywhere) ───────────────────

    @override
    async def save_artifact(
        self,
        *,
        app_name: str,
        filename: str,
        artifact: types.Part | dict[str, Any],
        session_id: str | None = None,
        custom_metadata: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> int:
        return await super().save_artifact(
            app_name=app_name,
            user_id=user_id or "default_user",
            filename=filename,
            artifact=artifact,
            session_id=session_id,
            custom_metadata=custom_metadata,
        )

    @override
    async def load_artifact(
        self,
        *,
        app_name: str,
        filename: str,
        user_id: str | None = None,
        session_id: str | None = None,
        version: int | None = None,
    ) -> types.Part | None:
        logger.info("Loading artifact: %s/%s/%s", session_id, app_name, filename)
        return await super().load_artifact(
            app_name=app_name,
            user_id=user_id or "default_user",
            filename=filename,
            session_id=session_id,
            version=version,
        )

    @override
    async def list_artifact_keys(
        self,
        *,
        app_name: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> list[str]:
        return await super().list_artifact_keys(
            app_name=app_name,
            user_id=user_id or "default_user",
            session_id=session_id,
        )

    @override
    async def delete_artifact(
        self,
        *,
        app_name: str,
        filename: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        return await super().delete_artifact(
            app_name=app_name,
            user_id=user_id or "default_user",
            filename=filename,
            session_id=session_id,
        )

    @override
    async def list_versions(
        self,
        *,
        app_name: str,
        filename: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> list[int]:
        return await super().list_versions(
            app_name=app_name,
            user_id=user_id or "default_user",
            filename=filename,
            session_id=session_id,
        )

    @override
    async def list_artifact_versions(
        self,
        *,
        app_name: str,
        filename: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> list[Any]:
        return await super().list_artifact_versions(
            app_name=app_name,
            user_id=user_id or "default_user",
            filename=filename,
            session_id=session_id,
        )

    @override
    async def get_artifact_version(
        self,
        *,
        app_name: str,
        filename: str,
        user_id: str | None = None,
        session_id: str | None = None,
        version: int | None = None,
    ) -> Any | None:
        return await super().get_artifact_version(
            app_name=app_name,
            user_id=user_id or "default_user",
            filename=filename,
            session_id=session_id,
            version=version,
        )

    # ── URI helper ────────────────────────────────────────────────────────────

    def get_artifact_uri(
        self,
        *,
        app_name: str,
        filename: str,
        session_id: str,
        version: int,
        user_id: str | None = None,
    ) -> str:
        """Return the full GCS URI for a saved artifact."""
        blob_name = self._get_blob_name(
            app_name=app_name,
            user_id=user_id or "default_user",
            filename=filename,
            version=version,
            session_id=session_id,
        )
        return f"gs://{self.bucket_name}/{blob_name}"

    # ── Path structure ────────────────────────────────────────────────────────

    @override
    def _get_blob_prefix(
        self,
        app_name: str,
        user_id: str,
        filename: str,
        session_id: str | None = None,
    ) -> str:
        """Return the GCS blob prefix.

        Structure:  ``{process_id}/{task_id}/{app_name}/{filename}``

        We prefer the process_id from our execution context (current_process_id).
        If session_id contains a ":" (legacy pattern), we respect that for backward compatibility.
        """
        if self._file_has_user_namespace(filename):
            return f"{app_name}/user/{filename}"

        if session_id is None:
            return f"global/{app_name}/{filename}"

        from giulia.agents.core.context import current_process_id

        # Default to context-aware process_id
        process_id = current_process_id.get()
        task_id = session_id

        # Legacy fallback: if session_id is "process:task", it takes precedence
        # to ensure we don't break existing hardcoded session_id patterns.
        if ":" in session_id:
            parts = session_id.split(":", 1)
            process_id, task_id = parts

        logger.info("Blob prefix: %s/%s/%s/%s", process_id, task_id, app_name, filename)

        return f"{process_id}/{task_id}/{app_name}/{filename}"
