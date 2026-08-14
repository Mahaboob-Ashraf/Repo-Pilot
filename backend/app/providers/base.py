"""Provider-neutral local inference contract and errors."""

from typing import Protocol


class InferenceProviderError(Exception):
    """Base error raised by an inference provider."""


class InferenceUnavailableError(InferenceProviderError):
    """Raised when the configured inference service cannot be reached."""


class InferenceResponseError(InferenceProviderError):
    """Raised when the inference service returns an unusable response."""


class InferenceProvider(Protocol):
    @property
    def model(self) -> str:
        """Return the configured model identifier."""

    async def generate(self, prompt: str) -> str:
        """Generate only the user-facing response text."""

