"""Embedding provider port for optional local semantic retrieval (Phase F).

The port keeps Brain and the app layer independent of any concrete embedding
backend: implementations live in ``adapters/``, receive plain text batches and
return one finite float vector per text. Every bound here is fail-closed —
an over-budget batch, an oversized text or a malformed vector is rejected
instead of silently degraded.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Any, List, Sequence

EMBEDDING_MAX_BATCH_TEXTS = 32
EMBEDDING_MAX_TEXT_CHARS = 8 * 1024
EMBEDDING_MAX_DIMS = 4096
EMBEDDING_MAX_MODEL_ID_CHARS = 128


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding request or response violates the port."""


def validate_embedding_model_id(model_id: Any) -> str:
    """Validate a bounded model identifier usable in URLs and index rows."""
    if not isinstance(model_id, str) or not model_id:
        raise EmbeddingProviderError("embedding model id must be a non-empty string")
    if len(model_id) > EMBEDDING_MAX_MODEL_ID_CHARS:
        raise EmbeddingProviderError(
            f"embedding model id exceeds {EMBEDDING_MAX_MODEL_ID_CHARS} characters"
        )
    if any(character.isspace() or character == '"' for character in model_id):
        raise EmbeddingProviderError(
            "embedding model id must not contain whitespace or quotes"
        )
    return model_id


def validate_embedding_vectors(vectors: Any) -> List[List[float]]:
    """Validate a bounded embedding response: one finite vector per text."""
    if not isinstance(vectors, list) or not vectors:
        raise EmbeddingProviderError("embedding response must be a non-empty list")
    dims: int | None = None
    for vector in vectors:
        if not isinstance(vector, list) or not vector:
            raise EmbeddingProviderError("each embedding must be a non-empty list")
        if dims is None:
            dims = len(vector)
            if dims > EMBEDDING_MAX_DIMS:
                raise EmbeddingProviderError(
                    f"embedding dims exceed {EMBEDDING_MAX_DIMS}"
                )
        elif len(vector) != dims:
            raise EmbeddingProviderError(
                "embedding response vectors have inconsistent dimensions"
            )
        for value in vector:
            if type(value) is not float and type(value) is not int:
                raise EmbeddingProviderError("embedding values must be numbers")
            if not math.isfinite(value):
                raise EmbeddingProviderError("embedding values must be finite")
    return vectors


class EmbeddingProvider(ABC):
    """Stable port for bounded local text embeddings."""

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Identifier of the embedding model this provider serves."""

    @abstractmethod
    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        """Embed a bounded batch of texts, returning one vector per text."""

    def validate_batch(self, texts: Sequence[str]) -> List[str]:
        """Enforce the bounded batch contract before any provider call."""
        if not isinstance(texts, (list, tuple)):
            raise EmbeddingProviderError("embedding batch must be a list of strings")
        if len(texts) > EMBEDDING_MAX_BATCH_TEXTS:
            raise EmbeddingProviderError(
                f"embedding batch exceeds {EMBEDDING_MAX_BATCH_TEXTS} texts"
            )
        cleaned: List[str] = []
        for text in texts:
            if not isinstance(text, str):
                raise EmbeddingProviderError("embedding texts must be strings")
            if not text:
                raise EmbeddingProviderError("embedding texts must be non-empty")
            if len(text) > EMBEDDING_MAX_TEXT_CHARS:
                raise EmbeddingProviderError(
                    f"embedding text exceeds {EMBEDDING_MAX_TEXT_CHARS} characters"
                )
            cleaned.append(text)
        return cleaned


__all__ = [
    "EMBEDDING_MAX_BATCH_TEXTS",
    "EMBEDDING_MAX_DIMS",
    "EMBEDDING_MAX_MODEL_ID_CHARS",
    "EMBEDDING_MAX_TEXT_CHARS",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "validate_embedding_model_id",
    "validate_embedding_vectors",
]
