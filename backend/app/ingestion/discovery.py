"""Deterministic, read-only discovery of source files in a local repository."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import os
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


LANGUAGE_BY_EXTENSION: Mapping[str, str] = MappingProxyType(
    {
        ".js": "javascript",
        ".jsx": "javascript",
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
    }
)

PARSER_SUPPORTED_LANGUAGES = frozenset({"python"})

EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
)


@dataclass(frozen=True, slots=True)
class DiscoveredSourceFile:
    """Provisional inventory metadata for one recognized source file."""

    relative_path: str
    language: str
    parser_supported: bool
    size_bytes: int


@dataclass(frozen=True, slots=True)
class RepositoryInventory:
    """Deterministic source inventory for one resolved local repository root."""

    repository_root: Path
    files: tuple[DiscoveredSourceFile, ...]

    @property
    def language_counts(self) -> dict[str, int]:
        counts = Counter(source_file.language for source_file in self.files)
        return dict(sorted(counts.items()))

    @property
    def parser_supported_files(self) -> tuple[DiscoveredSourceFile, ...]:
        return tuple(source_file for source_file in self.files if source_file.parser_supported)


class RepositoryRootError(ValueError):
    """Raised when a supplied local repository root is invalid."""


def detect_language(path: str | Path) -> str | None:
    """Classify a recognized source language by file extension only."""

    return LANGUAGE_BY_EXTENSION.get(Path(path).suffix.casefold())


def discover_repository(repository_root: str | Path) -> RepositoryInventory:
    """Return a safe, deterministic inventory without mutating the repository."""

    root = _resolve_repository_root(repository_root)
    discovered_files: list[DiscoveredSourceFile] = []

    for current_directory, directory_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        current_path = Path(current_directory)
        directory_names[:] = sorted(
            directory_name
            for directory_name in directory_names
            if _should_visit_directory(current_path / directory_name)
        )

        for file_name in sorted(file_names):
            candidate = current_path / file_name
            if candidate.is_symlink():
                continue

            language = detect_language(candidate)
            if language is None:
                continue

            try:
                resolved_file = candidate.resolve(strict=True)
                relative_path = resolved_file.relative_to(root).as_posix()
                size_bytes = resolved_file.stat().st_size
            except (FileNotFoundError, OSError, ValueError):
                # Conservatively omit files that disappear, become unreadable,
                # or resolve outside the root while discovery is in progress.
                continue

            if not resolved_file.is_file():
                continue

            discovered_files.append(
                DiscoveredSourceFile(
                    relative_path=relative_path,
                    language=language,
                    parser_supported=language in PARSER_SUPPORTED_LANGUAGES,
                    size_bytes=size_bytes,
                )
            )

    discovered_files.sort(key=lambda source_file: source_file.relative_path)
    return RepositoryInventory(
        repository_root=root,
        files=tuple(discovered_files),
    )


def _resolve_repository_root(repository_root: str | Path) -> Path:
    try:
        root = Path(repository_root).resolve(strict=True)
    except FileNotFoundError as exc:
        raise RepositoryRootError("Repository root does not exist") from exc
    if not root.is_dir():
        raise RepositoryRootError("Repository root must be a directory")
    return root


def _should_visit_directory(directory: Path) -> bool:
    return (
        directory.name.casefold() not in EXCLUDED_DIRECTORY_NAMES
        and not directory.is_symlink()
    )

