"""Deterministic semantic chunks built from repository parsing results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

from app.chunking.python_parser import (
    ConstructType,
    PythonConstruct,
    parse_python_file,
)
from app.ingestion import discover_repository


class ChunkType(StrEnum):
    """Canonical semantic chunk classifications supported in M1."""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    TEST = "test"


@dataclass(frozen=True, slots=True)
class CodeChunk:
    """A provisional semantic retrieval unit with immutable provenance."""

    chunk_id: str
    path: str
    language: str
    chunk_type: ChunkType
    symbol: str
    qualified_symbol: str
    parent_class: str | None
    start_line: int
    end_line: int
    source_text: str
    content_hash: str
    imports: tuple[str, ...]


_CHUNK_TYPE_BY_CONSTRUCT = {
    ConstructType.FUNCTION: ChunkType.FUNCTION,
    ConstructType.CLASS: ChunkType.CLASS,
    ConstructType.METHOD: ChunkType.METHOD,
    ConstructType.TEST_FUNCTION: ChunkType.TEST,
}


def build_code_chunks(repository_root: str | Path) -> tuple[CodeChunk, ...]:
    """Discover, parse, and build semantic chunks for supported source files."""

    inventory = discover_repository(repository_root)
    chunks: list[CodeChunk] = []

    for source_file in inventory.parser_supported_files:
        if source_file.language != "python":
            continue

        parse_result = parse_python_file(
            inventory.repository_root,
            source_file.relative_path,
        )
        chunks.extend(
            build_python_chunk(construct, imports=parse_result.imports)
            for construct in parse_result.constructs
        )

    return tuple(sorted(chunks, key=_chunk_order_key))


def build_python_chunk(
    construct: PythonConstruct,
    *,
    imports: tuple[str, ...] = (),
) -> CodeChunk:
    """Convert one parsed Python construct into a canonical CodeChunk."""

    chunk_type = _CHUNK_TYPE_BY_CONSTRUCT[construct.construct_type]
    qualified_symbol = (
        f"{construct.parent_class}.{construct.symbol}"
        if construct.parent_class is not None
        else construct.symbol
    )
    normalized_imports = tuple(sorted(set(imports)))

    return CodeChunk(
        chunk_id=_build_chunk_id(
            path=construct.relative_path,
            chunk_type=chunk_type,
            qualified_symbol=qualified_symbol,
            start_line=construct.start_line,
            end_line=construct.end_line,
        ),
        path=construct.relative_path,
        language="python",
        chunk_type=chunk_type,
        symbol=construct.symbol,
        qualified_symbol=qualified_symbol,
        parent_class=construct.parent_class,
        start_line=construct.start_line,
        end_line=construct.end_line,
        source_text=construct.source_text,
        content_hash=_hash_source(construct.source_text),
        imports=normalized_imports,
    )


def _build_chunk_id(
    *,
    path: str,
    chunk_type: ChunkType,
    qualified_symbol: str,
    start_line: int,
    end_line: int,
) -> str:
    return (
        f"{path}::{chunk_type.value}::{qualified_symbol}::"
        f"{start_line}-{end_line}"
    )


def _hash_source(source_text: str) -> str:
    return sha256(source_text.encode("utf-8")).hexdigest()


def _chunk_order_key(chunk: CodeChunk) -> tuple[str, int, int, str, str]:
    return (
        chunk.path,
        chunk.start_line,
        chunk.end_line,
        chunk.chunk_type.value,
        chunk.qualified_symbol,
    )
