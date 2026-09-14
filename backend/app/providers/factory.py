"""Centralized construction for LLM-backed generation providers."""

from __future__ import annotations

from app.config import Settings
from app.providers.base import InferenceProvider
from app.providers.gemini import GeminiProvider
from app.providers.ollama import OllamaProvider


def build_generation_provider(settings: Settings) -> InferenceProvider:
    """Build exactly the configured generation provider; never fall back silently."""

    if settings.generation_provider == "ollama":
        return OllamaProvider(settings)
    if settings.generation_provider == "gemini":
        return GeminiProvider(settings)
    raise ValueError("unsupported generation provider")


__all__ = ["build_generation_provider"]
