"""Async Ollama implementation of the local inference provider boundary."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings
from app.providers.base import InferenceResponseError, InferenceUnavailableError


class OllamaProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = settings.ollama_base_url
        self._model = settings.ollama_model
        self._timeout = settings.ollama_timeout_seconds
        self._transport = transport

    @property
    def model(self) -> str:
        return self._model

    async def generate(self, prompt: str) -> str:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    "/api/generate",
                    json={"model": self._model, "prompt": prompt, "stream": False},
                )
                response.raise_for_status()
        except (httpx.NetworkError, httpx.TimeoutException) as exc:
            raise InferenceUnavailableError(
                f"Ollama is unavailable at {self._base_url}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise InferenceResponseError(
                f"Ollama returned HTTP {exc.response.status_code}"
            ) from exc

        payload = self._read_payload(response)
        generated_text = payload.get("response")
        if not isinstance(generated_text, str):
            raise InferenceResponseError(
                "Ollama response did not contain generated text"
            )

        # Ollama may return a separate `thinking` field. It is intentionally ignored.
        return generated_text

    @staticmethod
    def _read_payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise InferenceResponseError("Ollama returned invalid JSON") from exc

        if not isinstance(payload, dict):
            raise InferenceResponseError("Ollama returned an invalid response object")
        return payload

