import asyncio
from collections.abc import Sequence
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.errors import InternalError
import pytest

from app.chunking import CodeChunk, build_repository_chunks
from app.providers import (
    EmbeddingBatch,
    EmbeddingUnavailableError,
    EmbeddingVector,
)
from app.providers.embeddings import validate_embedding_batch
from app.retrieval import (
    ChromaVectorIndex,
    DuplicateVectorChunkIdError,
    EmbeddingModelMismatchError,
    VectorQueryError,
    VectorRetrievalError,
    chunk_to_embedding_document,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOY_REPOSITORY = REPOSITORY_ROOT / "fixtures" / "toy-repo"


class FakeSemanticEmbeddingProvider:
    provider_name = "deterministic-fake"

    def __init__(self, model: str = "fake-semantic-v1") -> None:
        self.model = model
        self.batch_inputs: list[tuple[str, ...]] = []

    async def embed_text(self, text: str) -> EmbeddingVector:
        return (await self.embed_batch((text,)))[0]

    async def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch:
        requested = tuple(texts)
        self.batch_inputs.append(requested)
        vectors = [self._vector(text) for text in requested]
        return validate_embedding_batch(vectors, expected_count=len(requested))

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.casefold()
        semantic = any(
            term in lowered
            for term in ("discount", "reduction", "price", "applied")
        )
        testing = any(
            term in lowered for term in ("test", "check", "assert")
        )
        twenty = any(
            term in lowered for term in ("twenty", "20.0", "reduces")
        )
        zero = any(term in lowered for term in ("zero", "0.0", "keeps"))
        return [
            float(semantic),
            float(testing),
            float(twenty),
            float(zero),
            0.25,
        ]


class EqualEmbeddingProvider(FakeSemanticEmbeddingProvider):
    @staticmethod
    def _vector(text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


class ToggleEmbeddingProvider(FakeSemanticEmbeddingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.available = True

    async def embed_text(self, text: str) -> EmbeddingVector:
        if not self.available:
            raise EmbeddingUnavailableError("local embedding service unavailable")
        return await super().embed_text(text)


def _toy_chunks() -> tuple[CodeChunk, ...]:
    return build_repository_chunks(TOY_REPOSITORY).chunks


def _client(path: Path):
    return chromadb.PersistentClient(
        path=str(path),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def test_collection_uses_cosine_and_no_chroma_embedding_function(
    tmp_path: Path,
) -> None:
    provider = FakeSemanticEmbeddingProvider()
    index = ChromaVectorIndex(provider, client=_client(tmp_path / "chroma"))

    assert index.collection_metadata == {
        "embedding_provider": "deterministic-fake",
        "embedding_model": "fake-semantic-v1",
        "embedding_document_format": "codechunk-source-text-v1",
        "distance_space": "cosine",
    }
    assert index.collection_configuration["hnsw"]["space"] == "cosine"
    assert index.collection_configuration["embedding_function"] is None
    assert provider.batch_inputs == []


def test_embedding_document_is_exact_canonical_source_text() -> None:
    function = _toy_chunks()[0]

    assert chunk_to_embedding_document(function) == function.source_text
    assert function.path not in chunk_to_embedding_document(function)


def test_canonical_chunks_are_indexed_with_supplied_embeddings(
    tmp_path: Path,
) -> None:
    chunks = _toy_chunks()
    provider = FakeSemanticEmbeddingProvider()
    index = ChromaVectorIndex(provider, client=_client(tmp_path / "chroma"))

    indexed_count = asyncio.run(index.rebuild(chunks))

    assert indexed_count == 3
    assert index.count == 3
    assert index.indexed_chunk_ids() == tuple(
        sorted(chunk.chunk_id for chunk in chunks)
    )
    assert provider.batch_inputs[0] == tuple(
        chunk.source_text for chunk in sorted(chunks, key=lambda chunk: chunk.chunk_id)
    )


def test_vector_result_maps_to_exact_canonical_provenance(tmp_path: Path) -> None:
    chunks = _toy_chunks()
    function = chunks[0]
    index = ChromaVectorIndex(
        FakeSemanticEmbeddingProvider(),
        client=_client(tmp_path / "chroma"),
    )
    asyncio.run(index.rebuild(chunks))

    result = asyncio.run(index.search_vector("discount calculation", k=1))[0]

    assert result.chunk == function
    assert result.chunk_id == function.chunk_id
    assert result.path == "pricing.py"
    assert result.qualified_symbol == "apply_discount"
    assert result.rank == 1
    assert result.cosine_distance == pytest.approx(0.0, abs=1e-6)


def test_top_k_is_enforced_and_blank_queries_are_rejected(tmp_path: Path) -> None:
    index = ChromaVectorIndex(
        FakeSemanticEmbeddingProvider(),
        client=_client(tmp_path / "chroma"),
    )
    asyncio.run(index.rebuild(_toy_chunks()))

    assert len(asyncio.run(index.search_vector("discount", k=1))) == 1
    assert len(asyncio.run(index.search_vector("discount", k=2))) == 2
    with pytest.raises(VectorQueryError, match="must not be blank"):
        asyncio.run(index.search_vector("   "))
    with pytest.raises(ValueError, match="positive integer"):
        asyncio.run(index.search_vector("discount", k=0))


def test_fake_semantic_query_retrieves_twenty_percent_test(
    tmp_path: Path,
) -> None:
    index = ChromaVectorIndex(
        FakeSemanticEmbeddingProvider(),
        client=_client(tmp_path / "chroma"),
    )
    asyncio.run(index.rebuild(_toy_chunks()))

    results = asyncio.run(
        index.search_vector("test that checks twenty percent reduction")
    )

    assert results[0].qualified_symbol == (
        "test_twenty_percent_discount_reduces_price"
    )
    assert results[0].cosine_distance < results[1].cosine_distance


def test_rebuild_is_duplicate_free_and_removes_stale_records(
    tmp_path: Path,
) -> None:
    chunks = _toy_chunks()
    index = ChromaVectorIndex(
        FakeSemanticEmbeddingProvider(),
        client=_client(tmp_path / "chroma"),
    )

    asyncio.run(index.rebuild(chunks))
    asyncio.run(index.rebuild(reversed(chunks)))
    assert index.count == 3
    assert index.indexed_chunk_ids() == tuple(
        sorted(chunk.chunk_id for chunk in chunks)
    )

    asyncio.run(index.rebuild((chunks[0],)))
    assert index.count == 1
    assert index.indexed_chunk_ids() == (chunks[0].chunk_id,)


def test_duplicate_input_is_rejected_before_collection_mutation(
    tmp_path: Path,
) -> None:
    chunks = _toy_chunks()
    index = ChromaVectorIndex(
        FakeSemanticEmbeddingProvider(),
        client=_client(tmp_path / "chroma"),
    )
    asyncio.run(index.rebuild(chunks))

    with pytest.raises(DuplicateVectorChunkIdError, match="Duplicate chunk_id"):
        asyncio.run(index.rebuild((*chunks, chunks[0])))

    assert index.count == 3


def test_embedding_model_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    client = _client(tmp_path / "chroma")
    first = ChromaVectorIndex(FakeSemanticEmbeddingProvider("model-a"), client=client)
    asyncio.run(first.rebuild(_toy_chunks()))

    with pytest.raises(
        EmbeddingModelMismatchError,
        match="embedding identity did not match",
    ):
        ChromaVectorIndex(FakeSemanticEmbeddingProvider("model-b"), client=client)


def test_equal_distances_use_chunk_id_tie_breaking(tmp_path: Path) -> None:
    chunks = _toy_chunks()
    index = ChromaVectorIndex(
        EqualEmbeddingProvider(),
        client=_client(tmp_path / "chroma"),
    )
    asyncio.run(index.rebuild(reversed(chunks)))

    results = asyncio.run(index.search_vector("anything", k=3))

    assert [result.chunk_id for result in results] == sorted(
        chunk.chunk_id for chunk in chunks
    )
    assert len({result.cosine_distance for result in results}) == 1


def test_embedding_failure_surfaces_as_vector_retrieval_error(
    tmp_path: Path,
) -> None:
    provider = ToggleEmbeddingProvider()
    index = ChromaVectorIndex(provider, client=_client(tmp_path / "chroma"))
    asyncio.run(index.rebuild(_toy_chunks()))
    provider.available = False

    with pytest.raises(VectorRetrievalError, match="Dense embedding failed") as exc:
        asyncio.run(index.search_vector("discount"))

    assert isinstance(exc.value.__cause__, EmbeddingUnavailableError)


def test_chroma_query_failure_surfaces_as_vector_retrieval_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = ChromaVectorIndex(
        FakeSemanticEmbeddingProvider(),
        client=_client(tmp_path / "chroma"),
    )
    asyncio.run(index.rebuild(_toy_chunks()))

    def fail_query(*args: object, **kwargs: object) -> object:
        raise InternalError("storage unavailable")

    monkeypatch.setattr(index._collection, "query", fail_query)

    with pytest.raises(
        VectorRetrievalError,
        match="Chroma vector query failed: InternalError: storage unavailable",
    ) as exc:
        asyncio.run(index.search_vector("discount"))

    assert isinstance(exc.value.__cause__, InternalError)
