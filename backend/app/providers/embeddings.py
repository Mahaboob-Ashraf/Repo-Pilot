"""Provider-neutral local embedding contract, types, and validation."""

from __future__ import annotations

from collections.abc import Sequence
import math
from typing import Protocol


EmbeddingVector = tuple[float, ...]
EmbeddingBatch = tuple[EmbeddingVector, ...]


class EmbeddingProviderError(Exception):
    """Base error raised by an embedding provider."""


class EmbeddingUnavailableError(EmbeddingProviderError):
    """Raised when the configured embedding service cannot be reached."""


class EmbeddingResponseError(EmbeddingProviderError):
    """Raised when an embedding service returns an unusable response."""


class EmbeddingInputError(ValueError):
    """Raised when text cannot be submitted for embedding."""


class EmbeddingProvider(Protocol):
    @property
    def provider_name(self) -> str:
        """Return the embedding runtime/provider identifier."""

    @property
    def model(self) -> str:
        """Return the configured embedding model identifier."""

    async def embed_text(self, text: str) -> EmbeddingVector:
        """Embed one text using the configured model."""

    async def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch:
        """Embed a batch while preserving input order and cardinality."""


def validate_embedding_batch(
    embeddings: object,
    *,
    expected_count: int,
) -> EmbeddingBatch:
    """Validate and normalize a provider batch without assuming dimension."""

    if not isinstance(embeddings, (list, tuple)):
        raise EmbeddingResponseError("Embedding response must contain a vector list")
    if len(embeddings) != expected_count:
        raise EmbeddingResponseError(
            "Embedding response count did not match input count"
        )
    if expected_count == 0:
        return ()

    normalized: list[EmbeddingVector] = []
    expected_dimension: int | None = None
    for raw_vector in embeddings:
        if not isinstance(raw_vector, (list, tuple)) or not raw_vector:
            raise EmbeddingResponseError("Embedding vectors must not be empty")

        vector: list[float] = []
        for value in raw_vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EmbeddingResponseError(
                    "Embedding vectors must contain only finite numbers"
                )
            numeric_value = float(value)
            if not math.isfinite(numeric_value):
                raise EmbeddingResponseError(
                    "Embedding vectors must contain only finite numbers"
                )
            vector.append(numeric_value)

        if expected_dimension is None:
            expected_dimension = len(vector)
        elif len(vector) != expected_dimension:
            raise EmbeddingResponseError(
                "Embedding vectors had inconsistent dimensions"
            )
        normalized.append(tuple(vector))

    return tuple(normalized)
