import asyncio
from pathlib import Path

import pytest

from app.chunking import CodeChunk, build_repository_chunks
from app.providers import EmbeddingUnavailableError
from app.retrieval import (
    HybridRetrievalMode,
    HybridRetriever,
    LexicalSearchResult,
    RetrievalSource,
    VectorRetrievalError,
    VectorSearchResult,
    reciprocal_rank_fusion,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOY_REPOSITORY = REPOSITORY_ROOT / "fixtures" / "toy-repo"


def _chunks() -> tuple[CodeChunk, ...]:
    return build_repository_chunks(TOY_REPOSITORY).chunks


def _lexical(
    chunk: CodeChunk,
    rank: int,
    score: float = -1.0,
) -> LexicalSearchResult:
    return LexicalSearchResult(chunk=chunk, rank=rank, bm25_score=score)


def _vector(
    chunk: CodeChunk,
    rank: int,
    distance: float = 0.5,
) -> VectorSearchResult:
    return VectorSearchResult(chunk=chunk, rank=rank, cosine_distance=distance)


class StaticLexicalRetriever:
    def __init__(self, results: tuple[LexicalSearchResult, ...]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []

    def search_lexical(
        self,
        query: str,
        *,
        k: int = 10,
    ) -> tuple[LexicalSearchResult, ...]:
        self.calls.append((query, k))
        return self.results[:k]


class StaticVectorRetriever:
    def __init__(self, results: tuple[VectorSearchResult, ...]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []

    async def search_vector(
        self,
        query: str,
        *,
        k: int = 10,
    ) -> tuple[VectorSearchResult, ...]:
        self.calls.append((query, k))
        return self.results[:k]


class UnavailableVectorRetriever:
    async def search_vector(
        self,
        query: str,
        *,
        k: int = 10,
    ) -> tuple[VectorSearchResult, ...]:
        provider_error = EmbeddingUnavailableError(
            "local embedding service unavailable"
        )
        raise VectorRetrievalError(
            "Dense embedding failed: EmbeddingUnavailableError: "
            "local embedding service unavailable"
        ) from provider_error


class FailedChromaVectorRetriever:
    async def search_vector(
        self,
        query: str,
        *,
        k: int = 10,
    ) -> tuple[VectorSearchResult, ...]:
        raise VectorRetrievalError(
            "Chroma vector query failed: InternalError: storage unavailable"
        )


class BuggyVectorRetriever:
    async def search_vector(
        self,
        query: str,
        *,
        k: int = 10,
    ) -> tuple[VectorSearchResult, ...]:
        raise RuntimeError("unexpected programming failure")


def test_rrf_formula_matches_hand_calculated_ranks() -> None:
    first, second, third = _chunks()

    results = reciprocal_rank_fusion(
        (_lexical(first, 1), _lexical(second, 2)),
        (_vector(first, 2), _vector(third, 1)),
        k_rrf=60,
        top_k=3,
    )

    by_id = {result.chunk_id: result for result in results}
    assert by_id[first.chunk_id].rrf_score == pytest.approx(1 / 61 + 1 / 62)
    assert by_id[second.chunk_id].rrf_score == pytest.approx(1 / 62)
    assert by_id[third.chunk_id].rrf_score == pytest.approx(1 / 61)


def test_rrf_rejects_non_positive_input_ranks() -> None:
    chunk = _chunks()[0]

    with pytest.raises(ValueError, match="lexical rank must be a positive integer"):
        reciprocal_rank_fusion((_lexical(chunk, 0),), (), top_k=1)


def test_item_in_both_rankings_gets_both_contributions() -> None:
    chunk = _chunks()[0]

    result = reciprocal_rank_fusion(
        (_lexical(chunk, 3),),
        (_vector(chunk, 4),),
        k_rrf=10,
        top_k=1,
    )[0]

    assert result.rrf_score == pytest.approx(1 / 13 + 1 / 14)
    assert result.retrieval_sources == (
        RetrievalSource.LEXICAL,
        RetrievalSource.VECTOR,
    )


def test_lexical_only_item_has_no_fake_vector_values() -> None:
    chunk = _chunks()[0]

    result = reciprocal_rank_fusion(
        (_lexical(chunk, 1, -9.5),),
        (),
        top_k=1,
    )[0]

    assert result.lexical_rank == 1
    assert result.lexical_bm25_score == -9.5
    assert result.vector_rank is None
    assert result.vector_cosine_distance is None
    assert result.retrieval_sources == (RetrievalSource.LEXICAL,)


def test_vector_only_item_has_no_fake_lexical_values() -> None:
    chunk = _chunks()[0]

    result = reciprocal_rank_fusion(
        (),
        (_vector(chunk, 1, 0.125),),
        top_k=1,
    )[0]

    assert result.vector_rank == 1
    assert result.vector_cosine_distance == 0.125
    assert result.lexical_rank is None
    assert result.lexical_bm25_score is None
    assert result.retrieval_sources == (RetrievalSource.VECTOR,)


def test_equal_rrf_scores_tie_break_by_canonical_chunk_id() -> None:
    first, second = sorted(_chunks()[:2], key=lambda chunk: chunk.chunk_id)

    results = reciprocal_rank_fusion(
        (_lexical(second, 1),),
        (_vector(first, 1),),
        top_k=2,
    )

    assert [result.chunk_id for result in results] == [
        first.chunk_id,
        second.chunk_id,
    ]


def test_top_k_is_enforced_independently_of_candidate_count() -> None:
    first, second, third = _chunks()

    results = reciprocal_rank_fusion(
        (_lexical(first, 1), _lexical(second, 2)),
        (_vector(third, 1),),
        top_k=2,
    )

    assert len(results) == 2


def test_hybrid_retriever_passes_configurable_candidate_depth_to_each_list() -> None:
    first, second = _chunks()[:2]
    lexical = StaticLexicalRetriever((_lexical(first, 1),))
    vector = StaticVectorRetriever((_vector(second, 1),))
    retriever = HybridRetriever(lexical, vector, candidate_k=7)

    response = asyncio.run(retriever.search_hybrid("issue", top_k=1))

    assert lexical.calls == [("issue", 7)]
    assert vector.calls == [("issue", 7)]
    assert len(response.results) == 1


def test_per_query_candidate_depth_override_is_separate_from_top_k() -> None:
    first, second = _chunks()[:2]
    lexical = StaticLexicalRetriever((_lexical(first, 1),))
    vector = StaticVectorRetriever((_vector(second, 1),))
    retriever = HybridRetriever(lexical, vector, candidate_k=20)

    asyncio.run(retriever.search_hybrid("issue", top_k=2, candidate_k=4))

    assert lexical.calls == [("issue", 4)]
    assert vector.calls == [("issue", 4)]


@pytest.mark.parametrize("name,value", [("top_k", 0), ("candidate_k", 0)])
def test_hybrid_depths_are_validated(name: str, value: int) -> None:
    retriever = HybridRetriever(
        StaticLexicalRetriever(()),
        StaticVectorRetriever(()),
    )

    kwargs = {name: value}
    with pytest.raises(ValueError, match=f"{name} must be a positive integer"):
        asyncio.run(retriever.search_hybrid("issue", **kwargs))


def test_raw_scores_are_metadata_and_never_combined_into_rrf_math() -> None:
    first, second = _chunks()[:2]

    ordinary = reciprocal_rank_fusion(
        (_lexical(first, 1, -1.0), _lexical(second, 2, -2.0)),
        (_vector(first, 2, 0.9), _vector(second, 1, 0.1)),
        top_k=2,
    )
    extreme = reciprocal_rank_fusion(
        (_lexical(first, 1, -1e100), _lexical(second, 2, 1e100)),
        (_vector(first, 2, -1e100), _vector(second, 1, 1e100)),
        top_k=2,
    )

    assert [(hit.chunk_id, hit.rrf_score) for hit in ordinary] == [
        (hit.chunk_id, hit.rrf_score) for hit in extreme
    ]


def test_canonical_provenance_survives_fusion() -> None:
    chunk = _chunks()[0]

    result = reciprocal_rank_fusion(
        (_lexical(chunk, 1),),
        (_vector(chunk, 1),),
        top_k=1,
    )[0]

    assert result.chunk is chunk
    assert result.path == "pricing.py"
    assert result.qualified_symbol == "apply_discount"


def test_dense_provider_failure_falls_back_and_marks_degraded_mode() -> None:
    first, second = _chunks()[:2]
    retriever = HybridRetriever(
        StaticLexicalRetriever(
            (_lexical(first, 1, -2.0), _lexical(second, 2, -1.0))
        ),
        UnavailableVectorRetriever(),
    )

    response = asyncio.run(retriever.search_hybrid("apply_discount", top_k=2))

    assert response.mode is HybridRetrievalMode.LEXICAL_ONLY_DEGRADED
    assert response.degraded is True
    assert response.degradation_reason is not None
    assert "EmbeddingUnavailableError" in response.degradation_reason
    assert [result.chunk_id for result in response.results] == [
        first.chunk_id,
        second.chunk_id,
    ]
    assert all(
        result.retrieval_sources == (RetrievalSource.LEXICAL,)
        and result.vector_rank is None
        and result.vector_cosine_distance is None
        for result in response.results
    )


def test_chroma_query_failure_falls_back_and_marks_degraded_mode() -> None:
    chunk = _chunks()[0]
    retriever = HybridRetriever(
        StaticLexicalRetriever((_lexical(chunk, 1, -2.0),)),
        FailedChromaVectorRetriever(),
    )

    response = asyncio.run(retriever.search_hybrid("apply_discount", top_k=1))

    assert response.mode is HybridRetrievalMode.LEXICAL_ONLY_DEGRADED
    assert response.degraded is True
    assert response.degradation_reason is not None
    assert "Chroma vector query failed" in response.degradation_reason
    assert response.results[0].retrieval_sources == (RetrievalSource.LEXICAL,)
    assert response.results[0].vector_rank is None
    assert response.results[0].vector_cosine_distance is None


def test_unexpected_vector_programming_error_is_not_swallowed() -> None:
    chunk = _chunks()[0]
    retriever = HybridRetriever(
        StaticLexicalRetriever((_lexical(chunk, 1),)),
        BuggyVectorRetriever(),
    )

    with pytest.raises(RuntimeError, match="unexpected programming failure"):
        asyncio.run(retriever.search_hybrid("apply_discount", top_k=1))


def test_successful_dense_retrieval_marks_normal_hybrid_mode() -> None:
    chunk = _chunks()[0]
    retriever = HybridRetriever(
        StaticLexicalRetriever((_lexical(chunk, 1),)),
        StaticVectorRetriever((_vector(chunk, 1),)),
    )

    response = asyncio.run(retriever.search_hybrid("apply_discount", top_k=1))

    assert response.mode is HybridRetrievalMode.HYBRID
    assert response.degraded is False
    assert response.degradation_reason is None
