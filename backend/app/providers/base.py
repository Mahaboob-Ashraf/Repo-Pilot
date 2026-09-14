"""Provider-neutral local inference contracts and errors."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


class InferenceProviderError(Exception):
    """Base error raised by an inference provider."""


class InferenceUnavailableError(InferenceProviderError):
    """Raised when the configured inference service cannot be reached."""


class InferenceResponseError(InferenceProviderError):
    """Raised when the inference service returns an unusable response."""


class InferenceProvider(Protocol):
    @property
    def provider_name(self) -> str:
        """Return a safe provider identifier."""

    @property
    def model(self) -> str:
        """Return the configured model identifier."""

    async def generate(self, prompt: str) -> str:
        """Generate only the user-facing response text."""


@runtime_checkable
class StructuredInferenceProvider(Protocol):
    """Optional provider capability for native JSON-schema generation."""

    async def generate_structured(
        self,
        prompt: str,
        response_schema: Mapping[str, Any],
    ) -> str:
        """Generate response text constrained by the supplied JSON schema."""


@dataclass(frozen=True, slots=True)
class GenerationUsage:
    """Safe token counts exposed by providers when response metadata supplies them."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@runtime_checkable
class UsageReportingInferenceProvider(Protocol):
    @property
    def last_usage(self) -> GenerationUsage | None:
        """Return token counts for the most recently completed request, if available."""


async def generate_with_optional_schema(
    provider: InferenceProvider,
    prompt: str,
    response_schema: Mapping[str, Any],
) -> str:
    """Prefer a provider's native schema support, retaining plain fallback."""

    if isinstance(provider, StructuredInferenceProvider):
        return await provider.generate_structured(prompt, response_schema)
    return await provider.generate(prompt)
