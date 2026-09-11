"""Local generation and embedding provider boundaries."""

from app.providers.embeddings import (
    EmbeddingBatch,
    EmbeddingInputError,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingResponseError,
    EmbeddingUnavailableError,
    EmbeddingVector,
)
from app.providers.ollama_embeddings import OllamaEmbeddingProvider

__all__ = [
    "EmbeddingBatch",
    "EmbeddingInputError",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "EmbeddingResponseError",
    "EmbeddingUnavailableError",
    "EmbeddingVector",
    "OllamaEmbeddingProvider",
]
