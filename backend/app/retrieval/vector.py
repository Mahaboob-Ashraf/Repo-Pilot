"""Chroma cosine retrieval over explicitly embedded canonical CodeChunks."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings as ChromaSettings
from chromadb.errors import ChromaError

from app.chunking import ChunkType, CodeChunk
from app.providers.embeddings import (
    EmbeddingProvider,
    EmbeddingProviderError,
    validate_embedding_batch,
)


DEFAULT_VECTOR_COLLECTION_NAME = "repopilot_code_chunks"
DEFAULT_EMBEDDING_BATCH_SIZE = 32
EMBEDDING_DOCUMENT_FORMAT = "codechunk-source-text-v1"
VECTOR_DISTANCE_SPACE = "cosine"


class EmbeddingModelMismatchError(ValueError):
    """Raised when a collection and query provider use different identities."""


class DuplicateVectorChunkIdError(ValueError):
    """Raised when a vector rebuild receives duplicate canonical IDs."""


class VectorRetrievalError(RuntimeError):
    """Expected dense-path failure that permits explicit lexical fallback."""


class VectorCollectionError(VectorRetrievalError):
    """Raised when Chroma collection data/configuration is unusable."""


class VectorQueryError(ValueError):
    """Raised when a vector query is empty or otherwise invalid."""


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    """A ranked vector hit mapped back to its canonical CodeChunk."""

    chunk: CodeChunk
    rank: int
    cosine_distance: float

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id

    @property
    def path(self) -> str:
        return self.chunk.path

    @property
    def qualified_symbol(self) -> str:
        return self.chunk.qualified_symbol


@dataclass(frozen=True, slots=True)
class VectorRebuildMetrics:
    """Bounded setup timings retained for evaluation diagnostics."""

    chunk_count: int
    embedding_batch_size: int
    embedding_batch_durations_ms: tuple[float, ...]
    embedding_total_ms: float
    chroma_write_ms: float
    total_ms: float


class ChromaVectorIndex:
    """A local cosine collection using only RepoPilot-supplied embeddings."""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        *,
        client: ClientAPI | None = None,
        persist_directory: str | Path | None = None,
        collection_name: str = DEFAULT_VECTOR_COLLECTION_NAME,
        embedding_batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE,
    ) -> None:
        if client is not None and persist_directory is not None:
            raise ValueError("Provide either a Chroma client or persist_directory")
        if (
            isinstance(embedding_batch_size, bool)
            or not isinstance(embedding_batch_size, int)
            or embedding_batch_size <= 0
        ):
            raise ValueError("embedding_batch_size must be a positive integer")

        self._embedding_provider = embedding_provider
        self._embedding_batch_size = embedding_batch_size
        self._collection_name = collection_name
        self._last_rebuild_metrics: VectorRebuildMetrics | None = None
        chroma_settings = ChromaSettings(anonymized_telemetry=False)
        if client is not None:
            self._client = client
        elif persist_directory is not None:
            self._client = chromadb.PersistentClient(
                path=str(persist_directory),
                settings=chroma_settings,
            )
        else:
            self._client = chromadb.EphemeralClient(settings=chroma_settings)

        self._collection = self._get_or_create_collection()
        self._validate_collection_identity()

    @property
    def count(self) -> int:
        return self._collection.count()

    @property
    def collection_metadata(self) -> Mapping[str, Any]:
        return dict(self._collection.metadata or {})

    @property
    def collection_configuration(self) -> Mapping[str, Any]:
        vector_config = self._vector_config()
        return {
            "hnsw": {"space": vector_config.space},
            "embedding_function": vector_config.embedding_function,
        }

    @property
    def last_rebuild_metrics(self) -> VectorRebuildMetrics | None:
        return self._last_rebuild_metrics

    def indexed_chunk_ids(self) -> tuple[str, ...]:
        records = self._collection.get(include=[])
        return tuple(sorted(str(record_id) for record_id in records["ids"]))

    async def rebuild(self, chunks: Iterable[CodeChunk]) -> int:
        """Replace the collection with exactly the supplied canonical chunks."""

        ordered_chunks = sorted(chunks, key=lambda chunk: chunk.chunk_id)
        _reject_duplicate_chunk_ids(ordered_chunks)
        documents = tuple(chunk_to_embedding_document(chunk) for chunk in ordered_chunks)
        rebuild_started = perf_counter()
        embedding_durations: list[float] = []

        if documents:
            collected_embeddings = []
            for offset in range(0, len(documents), self._embedding_batch_size):
                batch = documents[offset : offset + self._embedding_batch_size]
                embedding_started = perf_counter()
                collected_embeddings.extend(
                    validate_embedding_batch(
                        await self._embedding_provider.embed_batch(batch),
                        expected_count=len(batch),
                    )
                )
                embedding_durations.append(
                    (perf_counter() - embedding_started) * 1000
                )
            embeddings = tuple(collected_embeddings)
        else:
            embeddings = ()

        write_started = perf_counter()
        self._client.delete_collection(self._collection_name)
        self._collection = self._create_collection()

        if ordered_chunks:
            self._collection.add(
                ids=[chunk.chunk_id for chunk in ordered_chunks],
                embeddings=[list(vector) for vector in embeddings],
                documents=list(documents),
                metadatas=[_chunk_metadata(chunk) for chunk in ordered_chunks],
            )

        write_ms = (perf_counter() - write_started) * 1000
        self._last_rebuild_metrics = VectorRebuildMetrics(
            chunk_count=len(ordered_chunks),
            embedding_batch_size=self._embedding_batch_size,
            embedding_batch_durations_ms=tuple(embedding_durations),
            embedding_total_ms=sum(embedding_durations),
            chroma_write_ms=write_ms,
            total_ms=(perf_counter() - rebuild_started) * 1000,
        )

        return len(ordered_chunks)

    async def search_vector(
        self,
        query: str,
        *,
        k: int = 10,
    ) -> tuple[VectorSearchResult, ...]:
        """Embed one query and return canonical chunks by cosine distance."""

        if not isinstance(query, str) or not query.strip():
            raise VectorQueryError("Vector query must not be blank")
        if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
            raise ValueError("k must be a positive integer")

        self._validate_collection_identity()
        try:
            collection_count = self.count
        except ChromaError as exc:
            raise VectorRetrievalError(
                f"Chroma vector count failed: {type(exc).__name__}: {exc}"
            ) from exc
        if collection_count == 0:
            return ()

        try:
            query_embedding = validate_embedding_batch(
                (await self._embedding_provider.embed_text(query),),
                expected_count=1,
            )[0]
        except EmbeddingProviderError as exc:
            raise VectorRetrievalError(
                f"Dense embedding failed: {type(exc).__name__}: {exc}"
            ) from exc

        try:
            raw_result = self._collection.query(
                query_embeddings=[list(query_embedding)],
                n_results=min(k, collection_count),
                include=["documents", "metadatas", "distances"],
            )
        except ChromaError as exc:
            raise VectorRetrievalError(
                f"Chroma vector query failed: {type(exc).__name__}: {exc}"
            ) from exc
        hits = _read_query_hits(raw_result)
        ordered_hits = sorted(hits, key=lambda hit: (hit[2], hit[0]))

        return tuple(
            VectorSearchResult(
                chunk=_chunk_from_record(record_id, document, metadata),
                rank=rank,
                cosine_distance=distance,
            )
            for rank, (record_id, document, distance, metadata) in enumerate(
                ordered_hits,
                start=1,
            )
        )

    def _get_or_create_collection(self) -> Collection:
        return self._client.get_or_create_collection(
            name=self._collection_name,
            metadata=_collection_metadata(self._embedding_provider),
            embedding_function=None,
            configuration={"hnsw": {"space": VECTOR_DISTANCE_SPACE}},
        )

    def _create_collection(self) -> Collection:
        return self._client.create_collection(
            name=self._collection_name,
            metadata=_collection_metadata(self._embedding_provider),
            embedding_function=None,
            configuration={"hnsw": {"space": VECTOR_DISTANCE_SPACE}},
        )

    def _validate_collection_identity(self) -> None:
        metadata = self.collection_metadata
        expected = _collection_metadata(self._embedding_provider)
        for key, value in expected.items():
            if metadata.get(key) != value:
                raise EmbeddingModelMismatchError(
                    "Vector collection embedding identity did not match the "
                    f"configured provider ({key})"
                )

        vector_config = self._vector_config()
        if vector_config.space != VECTOR_DISTANCE_SPACE:
            raise VectorCollectionError(
                "Vector collection must use Chroma cosine distance"
            )
        if vector_config.embedding_function is not None:
            raise VectorCollectionError(
                "Vector collection must not configure a Chroma embedding function"
            )

    def _vector_config(self) -> Any:
        try:
            embedding_key = self._collection.schema.keys["#embedding"]
            return embedding_key.float_list.vector_index.config
        except (AttributeError, KeyError, TypeError) as exc:
            raise VectorCollectionError(
                "Vector collection did not expose an embedding index schema"
            ) from exc


def chunk_to_embedding_document(chunk: CodeChunk) -> str:
    """Return the deterministic M2.2 embedding document for one chunk."""

    return chunk.source_text


def _collection_metadata(provider: EmbeddingProvider) -> dict[str, str]:
    return {
        "embedding_provider": provider.provider_name,
        "embedding_model": provider.model,
        "embedding_document_format": EMBEDDING_DOCUMENT_FORMAT,
        "distance_space": VECTOR_DISTANCE_SPACE,
    }


def _chunk_metadata(chunk: CodeChunk) -> dict[str, str | int]:
    metadata: dict[str, str | int] = {
        "path": chunk.path,
        "language": chunk.language,
        "chunk_type": chunk.chunk_type.value,
        "symbol": chunk.symbol,
        "qualified_symbol": chunk.qualified_symbol,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "content_hash": chunk.content_hash,
        "imports_json": json.dumps(
            chunk.imports,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    if chunk.parent_class is not None:
        metadata["parent_class"] = chunk.parent_class
    return metadata


def _reject_duplicate_chunk_ids(chunks: list[CodeChunk]) -> None:
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.chunk_id in seen:
            raise DuplicateVectorChunkIdError(
                f"Duplicate chunk_id in vector index rebuild: {chunk.chunk_id}"
            )
        seen.add(chunk.chunk_id)


def _read_query_hits(
    result: Mapping[str, Any],
) -> tuple[tuple[str, str, float, Mapping[str, Any]], ...]:
    try:
        ids = result["ids"][0]
        documents = result["documents"][0]
        distances = result["distances"][0]
        metadatas = result["metadatas"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise VectorCollectionError("Chroma returned a malformed query result") from exc

    if not (
        len(ids) == len(documents) == len(distances) == len(metadatas)
    ):
        raise VectorCollectionError("Chroma query result cardinality was inconsistent")

    hits: list[tuple[str, str, float, Mapping[str, Any]]] = []
    for record_id, document, distance, metadata in zip(
        ids,
        documents,
        distances,
        metadatas,
        strict=True,
    ):
        if (
            not isinstance(record_id, str)
            or not isinstance(document, str)
            or isinstance(distance, bool)
            or not isinstance(distance, (int, float))
            or not math.isfinite(float(distance))
            or not isinstance(metadata, Mapping)
        ):
            raise VectorCollectionError("Chroma returned an invalid vector hit")
        hits.append((record_id, document, float(distance), metadata))
    return tuple(hits)


def _chunk_from_record(
    chunk_id: str,
    document: str,
    metadata: Mapping[str, Any],
) -> CodeChunk:
    try:
        parent_class = metadata.get("parent_class")
        return CodeChunk(
            chunk_id=chunk_id,
            path=str(metadata["path"]),
            language=str(metadata["language"]),
            chunk_type=ChunkType(str(metadata["chunk_type"])),
            symbol=str(metadata["symbol"]),
            qualified_symbol=str(metadata["qualified_symbol"]),
            parent_class=str(parent_class) if parent_class is not None else None,
            start_line=int(metadata["start_line"]),
            end_line=int(metadata["end_line"]),
            source_text=document,
            content_hash=str(metadata["content_hash"]),
            imports=tuple(json.loads(str(metadata["imports_json"]))),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise VectorCollectionError(
            f"Chroma metadata could not reconstruct chunk {chunk_id}"
        ) from exc
