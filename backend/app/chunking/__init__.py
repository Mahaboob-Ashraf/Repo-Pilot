"""Semantic source parsing and chunk representation foundations."""

from app.chunking.code_chunks import (
    ChunkType,
    CodeChunk,
    build_code_chunks,
    build_python_chunk,
)

from app.chunking.pipeline import (
    RepositoryChunkingResult,
    build_repository_chunks,
)

from app.chunking.python_parser import (
    ConstructType,
    PathOutsideRepositoryError,
    PythonConstruct,
    PythonParseResult,
    PythonSyntaxError,
    extract_python_constructs,
    parse_python_file,
)

__all__ = [
    "ChunkType",
    "CodeChunk",
    "ConstructType",
    "PathOutsideRepositoryError",
    "PythonConstruct",
    "PythonParseResult",
    "PythonSyntaxError",
    "RepositoryChunkingResult",
    "build_code_chunks",
    "build_repository_chunks",
    "build_python_chunk",
    "extract_python_constructs",
    "parse_python_file",
]
