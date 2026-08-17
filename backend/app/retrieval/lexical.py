"""SQLite FTS5 indexing and BM25 retrieval for canonical CodeChunks."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3

from app.chunking import ChunkType, CodeChunk


_QUERY_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)

_CREATE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS lexical_chunks (
    chunk_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    language TEXT NOT NULL,
    chunk_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    qualified_symbol TEXT NOT NULL,
    parent_class TEXT,
    start_line INTEGER NOT NULL CHECK (start_line >= 1),
    end_line INTEGER NOT NULL CHECK (end_line >= start_line),
    source_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    imports_json TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS lexical_chunks_fts USING fts5(
    chunk_id UNINDEXED,
    source_text,
    symbol,
    qualified_symbol,
    path,
    chunk_type,
    imports,
    tokenize = 'unicode61'
);
"""

_INSERT_CHUNK_SQL = """
INSERT INTO lexical_chunks (
    chunk_id,
    path,
    language,
    chunk_type,
    symbol,
    qualified_symbol,
    parent_class,
    start_line,
    end_line,
    source_text,
    content_hash,
    imports_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_FTS_SQL = """
INSERT INTO lexical_chunks_fts (
    chunk_id,
    source_text,
    symbol,
    qualified_symbol,
    path,
    chunk_type,
    imports
) VALUES (?, ?, ?, ?, ?, ?, ?)
"""

_SEARCH_SQL = """
SELECT
    chunks.chunk_id,
    chunks.path,
    chunks.language,
    chunks.chunk_type,
    chunks.symbol,
    chunks.qualified_symbol,
    chunks.parent_class,
    chunks.start_line,
    chunks.end_line,
    chunks.source_text,
    chunks.content_hash,
    chunks.imports_json,
    bm25(
        lexical_chunks_fts,
        0.0,
        1.0,
        6.0,
        6.0,
        3.0,
        1.0,
        2.0
    ) AS bm25_score
FROM lexical_chunks_fts
JOIN lexical_chunks AS chunks
    ON chunks.chunk_id = lexical_chunks_fts.chunk_id
WHERE lexical_chunks_fts MATCH ?
ORDER BY bm25_score ASC, chunks.chunk_id ASC
LIMIT ?
"""


class FTS5UnavailableError(RuntimeError):
    """Raised when the active Python SQLite build cannot create FTS5 tables."""


class LexicalQueryError(ValueError):
    """Raised when a lexical query has no searchable terms."""


class DuplicateChunkIdError(ValueError):
    """Raised when one index rebuild receives duplicate canonical IDs."""


@dataclass(frozen=True, slots=True)
class LexicalSearchResult:
    """A ranked lexical hit mapped back to its canonical CodeChunk."""

    chunk: CodeChunk
    rank: int
    bm25_score: float

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id

    @property
    def path(self) -> str:
        return self.chunk.path

    @property
    def symbol(self) -> str:
        return self.chunk.symbol

    @property
    def qualified_symbol(self) -> str:
        return self.chunk.qualified_symbol

    @property
    def chunk_type(self) -> ChunkType:
        return self.chunk.chunk_type

    @property
    def start_line(self) -> int:
        return self.chunk.start_line

    @property
    def end_line(self) -> int:
        return self.chunk.end_line


class SQLiteLexicalIndex:
    """A bounded local CodeChunk store with an FTS5 search projection."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(str(database))
        self._connection.row_factory = sqlite3.Row
        try:
            _verify_fts5(self._connection)
            self._connection.executescript(_CREATE_SCHEMA_SQL)
        except Exception:
            self._connection.close()
            raise

    def __enter__(self) -> SQLiteLexicalIndex:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def chunk_count(self) -> int:
        row = self._connection.execute(
            "SELECT count(*) AS chunk_count FROM lexical_chunks"
        ).fetchone()
        if row is None:
            return 0
        return int(row["chunk_count"])

    def rebuild(self, chunks: Iterable[CodeChunk]) -> int:
        """Atomically replace the index contents with canonical chunks."""

        ordered_chunks = sorted(chunks, key=lambda chunk: chunk.chunk_id)
        _reject_duplicate_chunk_ids(ordered_chunks)

        with self._connection:
            self._connection.execute("DELETE FROM lexical_chunks_fts")
            self._connection.execute("DELETE FROM lexical_chunks")
            self._connection.executemany(
                _INSERT_CHUNK_SQL,
                (_canonical_row(chunk) for chunk in ordered_chunks),
            )
            self._connection.executemany(
                _INSERT_FTS_SQL,
                (_fts_row(chunk) for chunk in ordered_chunks),
            )

        return len(ordered_chunks)

    def search_lexical(
        self,
        query: str,
        *,
        k: int = 10,
    ) -> tuple[LexicalSearchResult, ...]:
        """Return up to k canonical chunks in ascending raw BM25 order."""

        if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
            raise ValueError("k must be a positive integer")

        match_query = _build_safe_match_query(query)
        rows = self._connection.execute(_SEARCH_SQL, (match_query, k)).fetchall()

        return tuple(
            LexicalSearchResult(
                chunk=_chunk_from_row(row),
                rank=rank,
                bm25_score=float(row["bm25_score"]),
            )
            for rank, row in enumerate(rows, start=1)
        )

    def close(self) -> None:
        self._connection.close()


def is_fts5_available() -> bool:
    """Probe actual FTS5 virtual-table creation in the active SQLite build."""

    with sqlite3.connect(":memory:") as connection:
        try:
            _verify_fts5(connection)
        except FTS5UnavailableError:
            return False
    return True


def _verify_fts5(connection: sqlite3.Connection) -> None:
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE temp.repopilot_fts5_probe USING fts5(value)"
        )
        connection.execute("DROP TABLE temp.repopilot_fts5_probe")
    except sqlite3.OperationalError as exc:
        raise FTS5UnavailableError(
            "SQLite FTS5 support is required for lexical retrieval"
        ) from exc


def _build_safe_match_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise LexicalQueryError("Lexical query must not be blank")

    tokens = tuple(dict.fromkeys(_QUERY_TOKEN_PATTERN.findall(query.casefold())))
    if not tokens:
        raise LexicalQueryError("Lexical query contains no searchable terms")

    return " OR ".join(f'"{token}"' for token in tokens)


def _reject_duplicate_chunk_ids(chunks: list[CodeChunk]) -> None:
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.chunk_id in seen:
            raise DuplicateChunkIdError(
                f"Duplicate chunk_id in lexical index rebuild: {chunk.chunk_id}"
            )
        seen.add(chunk.chunk_id)


def _canonical_row(chunk: CodeChunk) -> tuple[object, ...]:
    return (
        chunk.chunk_id,
        chunk.path,
        chunk.language,
        chunk.chunk_type.value,
        chunk.symbol,
        chunk.qualified_symbol,
        chunk.parent_class,
        chunk.start_line,
        chunk.end_line,
        chunk.source_text,
        chunk.content_hash,
        json.dumps(chunk.imports, ensure_ascii=False, separators=(",", ":")),
    )


def _fts_row(chunk: CodeChunk) -> tuple[str, ...]:
    return (
        chunk.chunk_id,
        chunk.source_text,
        chunk.symbol,
        chunk.qualified_symbol,
        chunk.path,
        chunk.chunk_type.value,
        " ".join(chunk.imports),
    )


def _chunk_from_row(row: sqlite3.Row) -> CodeChunk:
    return CodeChunk(
        chunk_id=str(row["chunk_id"]),
        path=str(row["path"]),
        language=str(row["language"]),
        chunk_type=ChunkType(str(row["chunk_type"])),
        symbol=str(row["symbol"]),
        qualified_symbol=str(row["qualified_symbol"]),
        parent_class=(
            str(row["parent_class"]) if row["parent_class"] is not None else None
        ),
        start_line=int(row["start_line"]),
        end_line=int(row["end_line"]),
        source_text=str(row["source_text"]),
        content_hash=str(row["content_hash"]),
        imports=tuple(json.loads(str(row["imports_json"]))),
    )
