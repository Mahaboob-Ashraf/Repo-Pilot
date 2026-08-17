"""End-to-end orchestration for deterministic local repository chunking."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from app.chunking.code_chunks import (
    CodeChunk,
    build_python_chunk,
    sort_code_chunks,
)
from app.chunking.python_parser import parse_python_file
from app.ingestion import DiscoveredSourceFile, discover_repository


@dataclass(frozen=True, slots=True)
class RepositoryChunkingResult:
    """Deterministic M1 summary and chunks for one validated repository."""

    repository_root: Path
    discovered_files: tuple[DiscoveredSourceFile, ...]
    language_counts: Mapping[str, int]
    parser_supported_paths: tuple[str, ...]
    chunks: tuple[CodeChunk, ...]

    @property
    def discovered_file_count(self) -> int:
        return len(self.discovered_files)

    @property
    def parser_supported_file_count(self) -> int:
        return len(self.parser_supported_paths)

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


def build_repository_chunks(
    repository_root: str | Path,
) -> RepositoryChunkingResult:
    """Run the complete M1 discovery-to-semantic-chunks pipeline."""

    inventory = discover_repository(repository_root)
    chunks: list[CodeChunk] = []

    for source_file in inventory.parser_supported_files:
        if source_file.language != "python":
            raise ValueError(
                "No parser is registered for parser-supported language "
                f"{source_file.language!r}"
            )

        parse_result = parse_python_file(
            inventory.repository_root,
            source_file.relative_path,
        )
        chunks.extend(
            build_python_chunk(construct, imports=parse_result.imports)
            for construct in parse_result.constructs
        )

    return RepositoryChunkingResult(
        repository_root=inventory.repository_root,
        discovered_files=inventory.files,
        language_counts=MappingProxyType(inventory.language_counts),
        parser_supported_paths=tuple(
            source_file.relative_path
            for source_file in inventory.parser_supported_files
        ),
        chunks=sort_code_chunks(chunks),
    )
