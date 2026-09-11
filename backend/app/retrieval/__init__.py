"""Local retrieval foundations."""

from app.retrieval.lexical import (
    DuplicateChunkIdError,
    FTS5UnavailableError,
    LexicalQueryError,
    LexicalSearchResult,
    SQLiteLexicalIndex,
    is_fts5_available,
)
from app.retrieval.vector import (
    DEFAULT_VECTOR_COLLECTION_NAME,
    EMBEDDING_DOCUMENT_FORMAT,
    VECTOR_DISTANCE_SPACE,
    ChromaVectorIndex,
    DuplicateVectorChunkIdError,
    EmbeddingModelMismatchError,
    VectorCollectionError,
    VectorQueryError,
    VectorSearchResult,
    chunk_to_embedding_document,
)

__all__ = [
    "DuplicateChunkIdError",
    "DuplicateVectorChunkIdError",
    "DEFAULT_VECTOR_COLLECTION_NAME",
    "EMBEDDING_DOCUMENT_FORMAT",
    "EmbeddingModelMismatchError",
    "FTS5UnavailableError",
    "LexicalQueryError",
    "LexicalSearchResult",
    "SQLiteLexicalIndex",
    "ChromaVectorIndex",
    "VECTOR_DISTANCE_SPACE",
    "VectorCollectionError",
    "VectorQueryError",
    "VectorSearchResult",
    "chunk_to_embedding_document",
    "is_fts5_available",
]
