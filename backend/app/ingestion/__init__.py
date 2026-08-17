"""Local repository discovery foundations."""

from app.ingestion.discovery import (
    EXCLUDED_DIRECTORY_NAMES,
    LANGUAGE_BY_EXTENSION,
    PARSER_SUPPORTED_LANGUAGES,
    DiscoveredSourceFile,
    RepositoryInventory,
    RepositoryRootError,
    detect_language,
    discover_repository,
)

__all__ = [
    "EXCLUDED_DIRECTORY_NAMES",
    "LANGUAGE_BY_EXTENSION",
    "PARSER_SUPPORTED_LANGUAGES",
    "DiscoveredSourceFile",
    "RepositoryInventory",
    "RepositoryRootError",
    "detect_language",
    "discover_repository",
]

