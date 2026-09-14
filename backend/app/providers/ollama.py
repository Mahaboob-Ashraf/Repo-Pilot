"""Async Ollama implementation of the local inference provider boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from app.config import Settings
from app.providers.base import InferenceResponseError, InferenceUnavailableError
from app.providers.base import GenerationUsage


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
        self._last_usage: GenerationUsage | None = None

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def last_usage(self) -> GenerationUsage | None:
        return self._last_usage

    async def generate(self, prompt: str) -> str:
        return await self._generate(prompt, response_schema=None)

    async def generate_structured(
        self,
        prompt: str,
        response_schema: Mapping[str, Any],
    ) -> str:
        """Use Ollama's native JSON-schema response-format capability."""

        return await self._generate(prompt, response_schema=response_schema)

    async def _generate(
        self,
        prompt: str,
        *,
        response_schema: Mapping[str, Any] | None,
    ) -> str:
        self._last_usage = None
        request_body: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }
        if response_schema is not None:
            request_body["format"] = dict(response_schema)
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    "/api/generate",
                    json=request_body,
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

        prompt_tokens = payload.get("prompt_eval_count")
        output_tokens = payload.get("eval_count")
        if isinstance(prompt_tokens, int) or isinstance(output_tokens, int):
            safe_prompt = prompt_tokens if isinstance(prompt_tokens, int) else None
            safe_output = output_tokens if isinstance(output_tokens, int) else None
            self._last_usage = GenerationUsage(
                input_tokens=safe_prompt,
                output_tokens=safe_output,
                total_tokens=(
                    safe_prompt + safe_output
                    if safe_prompt is not None and safe_output is not None
                    else None
                ),
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
