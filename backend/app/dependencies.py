"""FastAPI dependency wiring."""

from functools import lru_cache

from app.config import Settings
from app.providers.base import InferenceProvider
from app.providers.ollama import OllamaProvider


@lru_cache
def get_settings() -> Settings:
    return Settings.from_environment()


def get_inference_provider() -> InferenceProvider:
    return OllamaProvider(get_settings())

