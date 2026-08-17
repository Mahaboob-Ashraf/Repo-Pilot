"""Local retrieval foundations."""

from app.retrieval.lexical import (
    DuplicateChunkIdError,
    FTS5UnavailableError,
    LexicalQueryError,
    LexicalSearchResult,
    SQLiteLexicalIndex,
    is_fts5_available,
)

__all__ = [
    "DuplicateChunkIdError",
    "FTS5UnavailableError",
    "LexicalQueryError",
    "LexicalSearchResult",
    "SQLiteLexicalIndex",
    "is_fts5_available",
]
