"""Vertex AI text embeddings for semantic agent search.

Provides two functions used by :class:`~giulia.registry.CloudSQLAgentStore`:

- :func:`build_agent_text` — concatenate searchable agent fields into a single string.
- :func:`EmbeddingModel` — lazy-initialised wrapper around Vertex AI's
  ``TextEmbeddingModel``, configured once at import time via env vars or
  constructor arguments.

Dependencies: ``google-cloud-aiplatform`` (already in ``giulia`` core).
"""

from __future__ import annotations

import os
from typing import Any

from giulia.logging import logger
from giulia.registry.models import AgentAddr

EMBEDDING_DIM = 768
_DEFAULT_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-005")
_DEFAULT_LOCATION = os.getenv("VERTEX_LOCATION", "europe-west1")


def build_agent_text(agent: AgentAddr) -> str:
    """Concatenate searchable fields into a single string for embedding."""
    parts: list[str] = []
    if agent.agent_name:
        parts.append(agent.agent_name)
    if agent.description:
        parts.append(agent.description)
    if agent.company:
        parts.append(agent.company)
    for cap in agent.capabilities or []:
        parts.append(cap)
    return " ".join(parts) if parts else agent.agent_id


class EmbeddingModel:
    """Lazy-initialised Vertex AI text embedding model.

    Args:
        model: Vertex AI model name. Defaults to the ``EMBEDDING_MODEL`` env
            var, falling back to ``"text-embedding-005"``.
        project: GCP project ID. Defaults to the ``GCP_PROJECT_ID`` env var.
        location: Vertex AI region. Defaults to the ``VERTEX_LOCATION`` env
            var, falling back to ``"europe-west1"``.

    Example::

        em = EmbeddingModel()
        doc_vec = em.embed_text("billing invoice agent")
        query_vec = em.embed_query("find billing agents")
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        project: str | None = None,
        location: str = _DEFAULT_LOCATION,
    ) -> None:
        self._model_name = model
        self._project = project or os.getenv("GCP_PROJECT_ID", "")
        self._location = location
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            import vertexai
            from vertexai.language_models import TextEmbeddingModel

            if self._project:
                vertexai.init(project=self._project, location=self._location)
            self._model = TextEmbeddingModel.from_pretrained(self._model_name)
            logger.info("Vertex AI embedding model ready: {}", self._model_name)
        return self._model

    def embed_text(self, text: str) -> list[float]:
        """Return a document embedding vector for *text*."""
        from vertexai.language_models import TextEmbeddingInput

        model = self._get_model()
        inp = TextEmbeddingInput(text=text or "", task_type="RETRIEVAL_DOCUMENT")
        return model.get_embeddings([inp])[0].values

    def embed_query(self, text: str) -> list[float]:
        """Return a query embedding vector for similarity search."""
        from vertexai.language_models import TextEmbeddingInput

        model = self._get_model()
        inp = TextEmbeddingInput(text=(text or "").strip(), task_type="RETRIEVAL_QUERY")
        return model.get_embeddings([inp])[0].values
