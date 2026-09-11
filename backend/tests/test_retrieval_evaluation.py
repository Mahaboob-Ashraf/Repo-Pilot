import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from app.chunking import CodeChunk, build_repository_chunks
from app.evaluation import (
    DenseEvaluationRetriever,
    EvaluationHit,
    EvaluationRetrievalResponse,
    EvaluationVariant,
    HybridEvaluationRetriever,
    LexicalEvaluationRetriever,
    RetrievalCase,
    RetrievalEvaluationHarness,
    aggregate_case_results,
    load_retrieval_cases,
    score_case,
)
from app.providers import EmbeddingBatch, EmbeddingVector
from app.providers.embeddings import validate_embedding_batch
from app.retrieval import (
    ChromaVectorIndex,
    HybridRetriever,
    RetrievalSource,
    SQLiteLexicalIndex,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOY_REPOSITORY = REPOSITORY_ROOT / "fixtures" / "toy-repo"
CASES_PATH = Path(__file__).parent / "fixtures" / "retrieval_cases.json"


class SpyEvaluationRetriever:
    def __init__(
        self,
        response: EvaluationRetrievalResponse | None = None,
    ) -> None:
        self.response = response or EvaluationRetrievalResponse(())
        self.calls: list[tuple[str, int]] = []

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int,
    ) -> EvaluationRetrievalResponse:
        self.calls.append((query, top_k))
        return self.response


class ControlledEmbeddingProvider:
    provider_name = "controlled-evaluation-fake"
    model = "controlled-evaluation-v1"

    async def embed_text(self, text: str) -> EmbeddingVector:
        return (await self.embed_batch((text,)))[0]

    async def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch:
        vectors = [self._vector(text) for text in texts]
        return validate_embedding_batch(vectors, expected_count=len(vectors))

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.casefold()
        if lowered.strip() == "test_zero_percent_discount_keeps_price":
            # Intentionally differs from exact BM25 for modality-isolation proof.
            return [1.0, 0.0, 0.0]
        if "twenty percent reduction" in lowered or (
            "test_twenty_percent" in lowered
            or "apply_discount(100.0, 20.0)" in lowered
        ):
            return [0.0, 0.0, 1.0]
        if "test_zero_percent" in lowered or "apply_discount(50.0" in lowered:
            return [0.0, 1.0, 0.0]
        return [1.0, 0.0, 0.0]


def _case(*, symbols: tuple[str, ...] | None = ("target_symbol",)) -> RetrievalCase:
    return RetrievalCase(
        case_id="case-1",
        query="user issue text",
        repository_ref="fixtures/toy-repo",
        relevant_files=("target.py",),
        relevant_symbols=symbols,
    )


def _hit(
    rank: int,
    *,
    path: str = "other.py",
    symbol: str = "other_symbol",
) -> EvaluationHit:
    return EvaluationHit(
        chunk_id=f"{path}::function::{symbol}::{rank}-{rank}",
        rank=rank,
        path=path,
        symbol=symbol,
        qualified_symbol=symbol,
    )


def test_frozen_case_schema_validates_and_serializes() -> None:
    case = _case()

    assert json.loads(json.dumps(case.to_dict())) == case.to_dict()
    with pytest.raises(ValueError, match="normalized relative POSIX path"):
        RetrievalCase(
            case_id="bad",
            query="query",
            repository_ref="../outside",
            relevant_files=("target.py",),
        )
    with pytest.raises(ValueError, match="nonempty tuple"):
        RetrievalCase(
            case_id="bad",
            query="query",
            repository_ref="fixtures/toy-repo",
            relevant_files=(),
        )
    with pytest.raises(ValueError, match="JSON array"):
        RetrievalCase.from_dict(
            {
                "case_id": "bad",
                "query": "query",
                "repository_ref": "fixtures/toy-repo",
                "relevant_files": "target.py",
            }
        )


def test_controlled_case_file_loads_with_unique_frozen_cases() -> None:
    cases = load_retrieval_cases(CASES_PATH)

    assert len(cases) == 4
    assert len({case.case_id for case in cases}) == 4
    assert all(case.repository_ref == "fixtures/toy-repo" for case in cases)


def test_gold_labels_are_not_leaked_into_retrieval_query() -> None:
    spy = SpyEvaluationRetriever()
    harness = RetrievalEvaluationHarness({EvaluationVariant.AST_BM25: spy})
    case = RetrievalCase(
        case_id="no-leak",
        query="only this reaches retrieval",
        repository_ref="fixtures/toy-repo",
        relevant_files=("secret_gold_file.py",),
        relevant_symbols=("secret_gold_symbol",),
    )

    asyncio.run(harness.evaluate_case(case, EvaluationVariant.AST_BM25))

    assert spy.calls == [("only this reaches retrieval", 5)]


def test_file_hit_at_1_is_true_only_for_a_gold_file_at_rank_one() -> None:
    positive = score_case(
        _case(),
        EvaluationVariant.AST_BM25,
        EvaluationRetrievalResponse((_hit(1, path="target.py"),)),
        latency_ms=1.0,
    )
    negative = score_case(
        _case(),
        EvaluationVariant.AST_BM25,
        EvaluationRetrievalResponse(
            (_hit(1), _hit(2, path="target.py"))
        ),
        latency_ms=1.0,
    )

    assert positive.file_hit_at_1 is True
    assert negative.file_hit_at_1 is False


@pytest.mark.parametrize("rank,expected", [(5, True), (6, False)])
def test_file_hit_at_5_uses_the_inclusive_rank_cutoff(
    rank: int,
    expected: bool,
) -> None:
    result = score_case(
        _case(),
        EvaluationVariant.AST_BM25,
        EvaluationRetrievalResponse((_hit(rank, path="target.py"),)),
        latency_ms=1.0,
    )

    assert result.file_hit_at_5 is expected


@pytest.mark.parametrize("rank,expected", [(5, True), (6, False)])
def test_symbol_hit_at_5_uses_the_inclusive_rank_cutoff(
    rank: int,
    expected: bool,
) -> None:
    result = score_case(
        _case(),
        EvaluationVariant.AST_DENSE,
        EvaluationRetrievalResponse((_hit(rank, symbol="target_symbol"),)),
        latency_ms=1.0,
    )

    assert result.symbol_hit_at_5 is expected


def test_absent_symbol_ground_truth_produces_none_and_is_not_scored() -> None:
    result = score_case(
        _case(symbols=None),
        EvaluationVariant.AST_DENSE,
        EvaluationRetrievalResponse((_hit(1, symbol="target_symbol"),)),
        latency_ms=1.0,
    )

    assert result.symbol_hit_at_5 is None
    assert result.symbol_reciprocal_rank is None
    aggregate = aggregate_case_results((result,))
    assert aggregate.symbol_case_count == 0
    assert aggregate.symbol_hit_at_5_rate is None
    assert aggregate.mean_symbol_reciprocal_rank is None


def test_file_and_symbol_reciprocal_rank_use_first_relevant_result() -> None:
    result = score_case(
        _case(),
        EvaluationVariant.AST_HYBRID_RRF,
        EvaluationRetrievalResponse(
            (
                _hit(1),
                _hit(2, path="target.py", symbol="other_symbol"),
                _hit(3, path="target.py", symbol="target_symbol"),
            )
        ),
        latency_ms=1.0,
    )

    assert result.file_reciprocal_rank == 0.5
    assert result.symbol_reciprocal_rank == pytest.approx(1 / 3)


def test_per_case_record_preserves_ranked_chunk_ids_and_status() -> None:
    response = EvaluationRetrievalResponse(
        (_hit(2), _hit(1, path="target.py")),
        degraded=True,
        retrieval_mode="lexical_only_degraded",
    )

    result = score_case(
        _case(),
        EvaluationVariant.AST_HYBRID_RRF,
        response,
        latency_ms=2.5,
    )

    assert [hit.rank for hit in result.returned_hits] == [1, 2]
    assert result.returned_chunk_ids == tuple(
        hit.chunk_id for hit in result.returned_hits
    )
    assert result.degraded is True
    assert result.to_dict()["retrieval_mode"] == "lexical_only_degraded"


def test_per_case_scoring_rejects_duplicate_or_non_positive_ranks() -> None:
    with pytest.raises(ValueError, match="positive integers"):
        score_case(
            _case(),
            EvaluationVariant.AST_BM25,
            EvaluationRetrievalResponse((_hit(0),)),
            latency_ms=1.0,
        )
    with pytest.raises(ValueError, match="must be unique"):
        score_case(
            _case(),
            EvaluationVariant.AST_BM25,
            EvaluationRetrievalResponse((_hit(1), _hit(1, path="target.py"))),
            latency_ms=1.0,
        )


def test_variants_are_configured_and_scored_independently() -> None:
    retrievers = {
        variant: SpyEvaluationRetriever(
            EvaluationRetrievalResponse((_hit(1, path="target.py"),))
        )
        for variant in EvaluationVariant
    }
    harness = RetrievalEvaluationHarness(retrievers)

    report = asyncio.run(
        harness.evaluate((_case(),), tuple(EvaluationVariant), top_k=3)
    )

    assert [result.variant for result in report.case_results] == list(
        EvaluationVariant
    )
    assert all(retriever.calls == [("user issue text", 3)] for retriever in retrievers.values())


def test_aggregate_calculations_and_nearest_rank_percentiles_are_deterministic() -> None:
    results = tuple(
        score_case(
            _case(),
            EvaluationVariant.AST_BM25,
            EvaluationRetrievalResponse(
                (_hit(1 if index % 2 == 0 else 2, path="target.py", symbol="target_symbol"),)
            ),
            latency_ms=float(index),
        )
        for index in range(1, 6)
    )

    first = aggregate_case_results(results)
    second = aggregate_case_results(tuple(reversed(results)))

    assert first == second
    assert first.case_count == 5
    assert first.file_hit_at_1_rate == 0.4
    assert first.file_hit_at_5_rate == 1.0
    assert first.mean_file_reciprocal_rank == 0.7
    assert first.latency_p50_ms == 3.0
    assert first.latency_p95_ms == 5.0


def test_small_aggregate_does_not_overstate_latency_percentiles() -> None:
    result = score_case(
        _case(),
        EvaluationVariant.AST_BM25,
        EvaluationRetrievalResponse(()),
        latency_ms=1.0,
    )

    aggregate = aggregate_case_results((result,))

    assert aggregate.latency_p50_ms is None
    assert aggregate.latency_p95_ms is None


def test_controlled_toy_evaluation_runs_all_variants_end_to_end() -> None:
    chunks = build_repository_chunks(TOY_REPOSITORY).chunks
    lexical = SQLiteLexicalIndex()
    lexical.rebuild(chunks)
    vector = ChromaVectorIndex(ControlledEmbeddingProvider())
    asyncio.run(vector.rebuild(chunks))
    hybrid = HybridRetriever(lexical, vector, candidate_k=1)
    harness = RetrievalEvaluationHarness(
        {
            EvaluationVariant.AST_BM25: LexicalEvaluationRetriever(lexical),
            EvaluationVariant.AST_DENSE: DenseEvaluationRetriever(vector),
            EvaluationVariant.AST_HYBRID_RRF: HybridEvaluationRetriever(hybrid),
        }
    )

    report = asyncio.run(
        harness.evaluate(
            load_retrieval_cases(CASES_PATH),
            tuple(EvaluationVariant),
            top_k=3,
        )
    )

    assert len(report.case_results) == 12
    assert len(report.aggregates) == 3
    assert all(result.returned_chunk_ids for result in report.case_results)
    assert all(result.degraded is False for result in report.case_results)
    divergent = asyncio.run(
        hybrid.search_hybrid("test_zero_percent_discount_keeps_price", top_k=3)
    )
    by_symbol = {result.qualified_symbol: result for result in divergent.results}
    assert by_symbol["test_zero_percent_discount_keeps_price"].retrieval_sources == (
        RetrievalSource.LEXICAL,
    )
    assert by_symbol["apply_discount"].retrieval_sources == (
        RetrievalSource.VECTOR,
    )
    json.dumps(report.to_dict())
    lexical.close()
