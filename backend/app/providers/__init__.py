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
from app.providers.factory import build_generation_provider
from app.providers.gemini import GeminiProvider

__all__ = [
    "EmbeddingBatch",
    "EmbeddingInputError",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "EmbeddingResponseError",
    "EmbeddingUnavailableError",
    "EmbeddingVector",
    "GeminiProvider",
    "OllamaEmbeddingProvider",
    "build_generation_provider",
]
