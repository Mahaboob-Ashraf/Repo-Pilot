"""Async Ollama implementation of the local embedding provider boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from app.config import OllamaEmbeddingSettings
from app.providers.embeddings import (
    EmbeddingBatch,
    EmbeddingInputError,
    EmbeddingResponseError,
    EmbeddingUnavailableError,
    EmbeddingVector,
    validate_embedding_batch,
)


class OllamaEmbeddingProvider:
    def __init__(
        self,
        settings: OllamaEmbeddingSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = settings.ollama_base_url
        self._model = settings.ollama_embedding_model
        self._timeout = settings.ollama_embedding_timeout_seconds
        self._transport = transport

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model(self) -> str:
        return self._model

    async def embed_text(self, text: str) -> EmbeddingVector:
        return (await self.embed_batch((text,)))[0]

    async def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch:
        if isinstance(texts, str):
            raise EmbeddingInputError(
                "Embedding batch input must be a sequence of strings"
            )
        requested_texts = tuple(texts)
        if not requested_texts:
            return ()
        if any(not isinstance(text, str) or not text.strip() for text in requested_texts):
            raise EmbeddingInputError("Embedding inputs must be nonblank strings")

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    "/api/embed",
                    json={
                        "model": self._model,
                        "input": list(requested_texts),
                        "truncate": False,
                    },
                )
                response.raise_for_status()
        except (httpx.NetworkError, httpx.TimeoutException) as exc:
            raise EmbeddingUnavailableError(
                f"Ollama embeddings are unavailable at {self._base_url}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise EmbeddingResponseError(
                f"Ollama embeddings returned HTTP {exc.response.status_code}"
            ) from exc

        payload = self._read_payload(response)
        if "embeddings" not in payload:
            raise EmbeddingResponseError(
                "Ollama embedding response did not contain embeddings"
            )
        return validate_embedding_batch(
            payload["embeddings"],
            expected_count=len(requested_texts),
        )

    @staticmethod
    def _read_payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise EmbeddingResponseError(
                "Ollama embeddings returned invalid JSON"
            ) from exc

        if not isinstance(payload, dict):
            raise EmbeddingResponseError(
                "Ollama embeddings returned an invalid response object"
            )
        return payload
