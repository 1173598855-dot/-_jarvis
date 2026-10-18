"""Ollama adapter for the bounded embedding provider port (Phase F).

Calls the local Ollama ``POST /api/embed`` endpoint with a JSON batch and
validates the response against the port contract. The provider stays
opt-in: services only construct it when ``JARVIS_MEMORY_EMBED_MODEL`` is
configured, and every failure is wrapped into
:class:`EmbeddingProviderError` with a bounded, secret-free message.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, List, Sequence
from urllib.parse import urlsplit

from core.contracts.embedding_provider import (
    EMBEDDING_MAX_DIMS,
    EmbeddingProvider,
    EmbeddingProviderError,
    validate_embedding_model_id,
    validate_embedding_vectors,
)

EMBEDDING_HTTP_TIMEOUT_SECONDS = 30
EMBEDDING_RESPONSE_BYTES = 8 * 1024 * 1024


def _bounded_base_url(base_url: Any) -> str:
    if base_url is None:
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    if not isinstance(base_url, str) or not base_url:
        raise EmbeddingProviderError("embedding base URL must be a non-empty string")
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise EmbeddingProviderError(
            "embedding base URL must be an http(s) URL with a host"
        )
    return base_url.rstrip("/")


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Embed texts through the local Ollama ``/api/embed`` endpoint."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str | None = None,
        timeout: int = EMBEDDING_HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self._model = validate_embedding_model_id(model)
        self._base_url = _bounded_base_url(base_url)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or not 1 <= timeout <= 120
        ):
            raise EmbeddingProviderError(
                "embedding timeout must be between 1 and 120 seconds"
            )
        self._timeout = timeout

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        cleaned = self.validate_batch(texts)
        payload = json.dumps(
            {"model": self._model, "input": cleaned},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise EmbeddingProviderError(
                        f"embedding endpoint returned HTTP {status}"
                    )
                raw = response.read(EMBEDDING_RESPONSE_BYTES + 1)
        except EmbeddingProviderError:
            raise
        except urllib.error.HTTPError as error:
            raise EmbeddingProviderError(
                f"embedding endpoint returned HTTP {error.code}"
            ) from error
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise EmbeddingProviderError(
                "embedding endpoint is unreachable"
            ) from error
        if len(raw) > EMBEDDING_RESPONSE_BYTES:
            raise EmbeddingProviderError(
                "embedding response exceeds the bounded read budget"
            )
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise EmbeddingProviderError(
                "embedding response is not valid JSON"
            ) from error
        if not isinstance(body, dict) or not isinstance(body.get("embeddings"), list):
            raise EmbeddingProviderError(
                "embedding response must declare an embeddings list"
            )
        vectors = validate_embedding_vectors(body["embeddings"])
        if len(vectors) != len(cleaned):
            raise EmbeddingProviderError(
                f"embedding response returned {len(vectors)} vectors "
                f"for {len(cleaned)} texts"
            )
        for vector in vectors:
            if len(vector) > EMBEDDING_MAX_DIMS:
                raise EmbeddingProviderError(
                    f"embedding dims exceed {EMBEDDING_MAX_DIMS}"
                )
        return vectors


def embedding_provider_from_env(
    env: Any = None,
    *,
    model_env: str = "JARVIS_MEMORY_EMBED_MODEL",
) -> OllamaEmbeddingProvider | None:
    """Build the opt-in provider from environment configuration.

    Returns ``None`` when ``JARVIS_MEMORY_EMBED_MODEL`` is unset, keeping
    semantic retrieval disabled by default. An invalid configured value
    raises so that assembly fails closed instead of booting degraded.
    """
    environment = os.environ if env is None else env
    model = str(environment.get(model_env, "")).strip()
    if not model:
        return None
    return OllamaEmbeddingProvider(model)


__all__ = [
    "EMBEDDING_HTTP_TIMEOUT_SECONDS",
    "EMBEDDING_RESPONSE_BYTES",
    "OllamaEmbeddingProvider",
    "embedding_provider_from_env",
]
