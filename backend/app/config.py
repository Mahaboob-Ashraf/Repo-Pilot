"""Runtime configuration for the M0 backend."""

from __future__ import annotations

from dataclasses import dataclass
import os


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "gemma4:e4b-it-qat"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuration sourced from environment variables."""

    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    ollama_timeout_seconds: float = DEFAULT_OLLAMA_TIMEOUT_SECONDS

    @classmethod
    def from_environment(cls) -> Settings:
        timeout = float(
            os.getenv(
                "REPOPILOT_OLLAMA_TIMEOUT_SECONDS",
                str(DEFAULT_OLLAMA_TIMEOUT_SECONDS),
            )
        )
        if timeout <= 0:
            raise ValueError("REPOPILOT_OLLAMA_TIMEOUT_SECONDS must be positive")

        return cls(
            ollama_base_url=os.getenv(
                "REPOPILOT_OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL
            ).rstrip("/"),
            ollama_model=os.getenv(
                "REPOPILOT_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL
            ),
            ollama_timeout_seconds=timeout,
        )

