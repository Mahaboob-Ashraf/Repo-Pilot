"""Runtime configuration loaded once through RepoPilot's settings boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

from dotenv import load_dotenv


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "gemma4:e4b-it-qat"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 120.0
DEFAULT_OLLAMA_EMBEDDING_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_EMBEDDING_MODEL = "embeddinggemma"
DEFAULT_OLLAMA_EMBEDDING_TIMEOUT_SECONDS = 60.0
DEFAULT_GENERATION_PROVIDER = "ollama"
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"
DEFAULT_GEMINI_TIMEOUT_SECONDS = 120.0
SUPPORTED_GENERATION_PROVIDERS = frozenset({"ollama", "gemini"})
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _load_root_dotenv() -> None:
    """Load the fixed repository-root dotenv file without overriding the process."""

    load_dotenv(REPOSITORY_ROOT / ".env", override=False)


def _positive_timeout(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuration sourced from environment variables."""

    generation_provider: str = DEFAULT_GENERATION_PROVIDER
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    ollama_timeout_seconds: float = DEFAULT_OLLAMA_TIMEOUT_SECONDS
    gemini_api_key: str | None = field(default=None, repr=False)
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_timeout_seconds: float = DEFAULT_GEMINI_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.generation_provider not in SUPPORTED_GENERATION_PROVIDERS:
            raise ValueError(
                "REPOPILOT_GENERATION_PROVIDER must be 'ollama' or 'gemini'"
            )
        if not self.ollama_model.strip():
            raise ValueError("REPOPILOT_OLLAMA_MODEL must not be blank")
        if not self.gemini_model.strip():
            raise ValueError("REPOPILOT_GEMINI_MODEL must not be blank")
        if self.ollama_timeout_seconds <= 0:
            raise ValueError("REPOPILOT_OLLAMA_TIMEOUT_SECONDS must be positive")
        if self.gemini_timeout_seconds <= 0:
            raise ValueError("REPOPILOT_GEMINI_TIMEOUT_SECONDS must be positive")

    @classmethod
    def from_environment(cls) -> Settings:
        _load_root_dotenv()
        generation_provider = os.getenv(
            "REPOPILOT_GENERATION_PROVIDER", DEFAULT_GENERATION_PROVIDER
        ).strip().lower()
        gemini_key = os.getenv("REPOPILOT_GEMINI_API_KEY")

        return cls(
            generation_provider=generation_provider,
            ollama_base_url=os.getenv(
                "REPOPILOT_OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL
            ).rstrip("/"),
            ollama_model=os.getenv(
                "REPOPILOT_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL
            ),
            ollama_timeout_seconds=_positive_timeout(
                "REPOPILOT_OLLAMA_TIMEOUT_SECONDS",
                DEFAULT_OLLAMA_TIMEOUT_SECONDS,
            ),
            gemini_api_key=gemini_key.strip() if gemini_key else None,
            gemini_model=os.getenv(
                "REPOPILOT_GEMINI_MODEL", DEFAULT_GEMINI_MODEL
            ).strip(),
            gemini_timeout_seconds=_positive_timeout(
                "REPOPILOT_GEMINI_TIMEOUT_SECONDS",
                DEFAULT_GEMINI_TIMEOUT_SECONDS,
            ),
        )


@dataclass(frozen=True, slots=True)
class OllamaEmbeddingSettings:
    """Configuration for the separate local embedding provider."""

    ollama_base_url: str = DEFAULT_OLLAMA_EMBEDDING_BASE_URL
    ollama_embedding_model: str = DEFAULT_OLLAMA_EMBEDDING_MODEL
    ollama_embedding_timeout_seconds: float = (
        DEFAULT_OLLAMA_EMBEDDING_TIMEOUT_SECONDS
    )

    @classmethod
    def from_environment(cls) -> OllamaEmbeddingSettings:
        _load_root_dotenv()

        return cls(
            ollama_base_url=os.getenv(
                "REPOPILOT_OLLAMA_EMBEDDING_BASE_URL",
                DEFAULT_OLLAMA_EMBEDDING_BASE_URL,
            ).rstrip("/"),
            ollama_embedding_model=os.getenv(
                "REPOPILOT_OLLAMA_EMBEDDING_MODEL",
                DEFAULT_OLLAMA_EMBEDDING_MODEL,
            ),
            ollama_embedding_timeout_seconds=_positive_timeout(
                "REPOPILOT_OLLAMA_EMBEDDING_TIMEOUT_SECONDS",
                DEFAULT_OLLAMA_EMBEDDING_TIMEOUT_SECONDS,
            ),
        )
