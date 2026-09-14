"""Google Gemini implementation of RepoPilot's generation boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.config import Settings
from app.providers.base import (
    GenerationUsage,
    InferenceProviderError,
    InferenceResponseError,
    InferenceUnavailableError,
)


_RETRYABLE_STATUS_CODES = frozenset({408, 409, 429})


class _SanitizedGeminiCause(RuntimeError):
    """Cause marker that preserves classification without retaining SDK details."""


class GeminiProvider:
    """Async Gemini provider with schema output and bounded safe failures."""

    def __init__(
        self,
        settings: Settings,
        *,
        _client_factory: Callable[[], AbstractAsyncContextManager[Any]] | None = None,
    ) -> None:
        if not settings.gemini_api_key:
            raise InferenceProviderError("Gemini API key is not configured")
        self._api_key = settings.gemini_api_key
        self._model = settings.gemini_model
        self._timeout_ms = max(1, round(settings.gemini_timeout_seconds * 1000))
        self._client_factory = _client_factory or self._open_google_client
        self._last_usage: GenerationUsage | None = None

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model(self) -> str:
        return self._model

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
        return await self._generate(prompt, response_schema=response_schema)

    async def check_model_access(self) -> str:
        """Verify that the exact configured model is accessible without fallback."""

        try:
            async with self._client_factory() as client:
                model = await client.models.get(model=self._model)
        except Exception as exc:
            self._raise_mapped_error(exc)
        returned = getattr(model, "name", None)
        if not isinstance(returned, str) or self._model not in returned:
            raise InferenceResponseError(
                "Gemini model lookup returned an unusable response"
            )
        return self._model

    async def list_suitable_models(self) -> tuple[str, ...]:
        """Return safe generation-capable Gemini model names for failed preflight."""

        try:
            async with self._client_factory() as client:
                pager = await client.models.list()
                names: list[str] = []
                async for model in pager:
                    name = getattr(model, "name", None)
                    methods = getattr(model, "supported_actions", None)
                    if methods is None:
                        methods = getattr(model, "supported_generation_methods", None)
                    if (
                        isinstance(name, str)
                        and "gemini" in name.casefold()
                        and _supports_generation(methods)
                    ):
                        names.append(name.removeprefix("models/"))
        except Exception as exc:
            self._raise_mapped_error(exc)
        return tuple(sorted(set(names)))

    async def _generate(
        self,
        prompt: str,
        *,
        response_schema: Mapping[str, Any] | None,
    ) -> str:
        self._last_usage = None
        config: dict[str, Any] = {"temperature": 0}
        if response_schema is not None:
            config.update(
                {
                    "response_mime_type": "application/json",
                    "response_json_schema": dict(response_schema),
                }
            )
        try:
            async with self._client_factory() as client:
                response = await client.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=config,
                )
        except Exception as exc:
            self._raise_mapped_error(exc)

        try:
            generated_text = response.text
        except (AttributeError, TypeError, ValueError) as exc:
            raise InferenceResponseError(
                "Gemini response did not contain generated text"
            ) from _SanitizedGeminiCause(type(exc).__name__)
        if not isinstance(generated_text, str) or not generated_text.strip():
            raise InferenceResponseError(
                "Gemini response did not contain generated text"
            )
        self._last_usage = _read_usage(response)
        return generated_text

    def _open_google_client(self) -> AbstractAsyncContextManager[Any]:
        client = genai.Client(
            api_key=self._api_key,
            http_options=types.HttpOptions(
                timeout=self._timeout_ms,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        return client.aio

    @staticmethod
    def _raise_mapped_error(exc: Exception) -> None:
        safe_cause = _SanitizedGeminiCause(type(exc).__name__)
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
            raise InferenceUnavailableError("Gemini API is unavailable") from safe_cause
        if isinstance(exc, (httpx.NetworkError, httpx.TransportError)):
            raise InferenceUnavailableError("Gemini API is unavailable") from safe_cause
        if isinstance(exc, genai_errors.APIError):
            code = getattr(exc, "code", None)
            safe_cause = _SanitizedGeminiCause(
                f"{type(exc).__name__} status {code}"
                if isinstance(code, int)
                else type(exc).__name__
            )
            if code in _RETRYABLE_STATUS_CODES or (
                isinstance(code, int) and code >= 500
            ):
                raise InferenceUnavailableError("Gemini API is unavailable") from safe_cause
            raise InferenceProviderError("Gemini API request failed") from safe_cause
        if isinstance(exc, (OSError, ConnectionError)):
            raise InferenceUnavailableError("Gemini API is unavailable") from safe_cause
        raise InferenceProviderError("Gemini provider failed") from safe_cause


def _read_usage(response: Any) -> GenerationUsage | None:
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None:
        return None
    input_tokens = _safe_count(getattr(metadata, "prompt_token_count", None))
    output_tokens = _safe_count(getattr(metadata, "candidates_token_count", None))
    total_tokens = _safe_count(getattr(metadata, "total_token_count", None))
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None
    return GenerationUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def _safe_count(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _supports_generation(methods: Any) -> bool:
    if methods is None:
        return True
    if not isinstance(methods, (list, tuple, set, frozenset)):
        return False
    return any("generate" in str(method).casefold() for method in methods)


__all__ = ["GeminiProvider"]
