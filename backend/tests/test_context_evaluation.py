import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from app.chunking import CodeChunk, build_repository_chunks
from app.context_packing import ContextPack, ContextPacker, StructuralContextPipeline
from app.evaluation import (
    ContextEvaluationHarness,
    ContextEvaluationVariant,
    RetrievalCase,
    aggregate_context_results,
    load_retrieval_cases,
    score_context_pack,
)
from app.providers import EmbeddingBatch, EmbeddingVector
from app.providers.embeddings import validate_embedding_batch
from app.retrieval import (
    ChromaVectorIndex,
    HybridRetriever,
    SQLiteLexicalIndex,
    StructuralExpander,
    StructuralIndex,
)


STRUCTURE_REPOSITORY = Path(__file__).parent / "fixtures" / "structure_repo"
CASES_PATH = Path(__file__).parent / "fixtures" / "structure_cases.json"


class ExactCharacterCounter:
    def count_tokens(self, text: str) -> int:
        return len(text)


class SpyContextPipeline:
    def __init__(self, pack: ContextPack) -> None:
        self.pack = pack
        self.calls: list[tuple[str, int]] = []

    async def build_context(self, query: str, *, top_k: int) -> ContextPack:
        self.calls.append((query, top_k))
        return self.pack


class ControlledStructureEmbeddingProvider:
    provider_name = "controlled-structure-fake"
    model = "controlled-structure-v1"

    async def embed_text(self, text: str) -> EmbeddingVector:
        return (await self.embed_batch((text,)))[0]

    async def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch:
        vectors = [self._vector(text) for text in texts]
        return validate_embedding_batch(vectors, expected_count=len(vectors))

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.casefold()
        if "test_checkout" in lowered:
            return [0.0, 1.0, 0.0]
        if "checkout" in lowered:
            return [1.0, 0.0, 0.0]
        return [0.0, 0.0, 1.0]


def _chunks() -> tuple[CodeChunk, ...]:
    return build_repository_chunks(STRUCTURE_REPOSITORY).chunks


def _completed_pack() -> ContextPack:
    chunks = _chunks()
    checkout = next(chunk for chunk in chunks if chunk.symbol == "checkout")
    from app.retrieval import (
        HybridRetrievalMode,
        HybridSearchResponse,
        HybridSearchResult,
        RetrievalSource,
    )

    response = HybridSearchResponse(
        results=(
            HybridSearchResult(
                chunk=checkout,
                rank=1,
                rrf_score=1 / 61,
                lexical_rank=1,
                vector_rank=None,
                lexical_bm25_score=-1.0,
                vector_cosine_distance=None,
                retrieval_sources=(RetrievalSource.LEXICAL,),
            ),
        ),
        mode=HybridRetrievalMode.HYBRID,
    )
    expansion = StructuralExpander(StructuralIndex(chunks)).expand(response)
    return ContextPacker(ExactCharacterCounter()).pack(
        "checkout calculation", expansion, budget=100_000
    )


def _case(*, symbols: tuple[str, ...] | None = ("checkout",)) -> RetrievalCase:
    return RetrievalCase(
        case_id="context-case",
        query="checkout calculation",
        repository_ref="backend/tests/fixtures/structure_repo",
        relevant_files=("service.py",),
        relevant_symbols=symbols,
    )


def test_file_and_symbol_context_coverage_use_completed_pack() -> None:
    result = score_context_pack(
        _case(),
        ContextEvaluationVariant.HYBRID_STRUCTURE,
        _completed_pack(),
        latency_ms=1.0,
    )

    assert result.file_context_coverage is True
    assert result.symbol_context_coverage is True


def test_context_chunk_precision_is_explicit_at_file_and_symbol_levels() -> None:
    pack = _completed_pack()
    result = score_context_pack(
        _case(),
        ContextEvaluationVariant.HYBRID_STRUCTURE,
        pack,
        latency_ms=1.0,
    )
    file_matches = sum(item.chunk.path == "service.py" for item in pack.included_chunks)
    symbol_matches = sum(item.chunk.symbol == "checkout" for item in pack.included_chunks)

    assert result.file_context_chunk_precision == pytest.approx(
        file_matches / len(pack.included_chunks)
    )
    assert result.symbol_context_chunk_precision == pytest.approx(
        symbol_matches / len(pack.included_chunks)
    )


def test_context_token_waste_uses_included_chunk_costs_not_framing() -> None:
    pack = _completed_pack()
    result = score_context_pack(
        _case(),
        ContextEvaluationVariant.HYBRID_STRUCTURE,
        pack,
        latency_ms=1.0,
    )
    total = sum(item.token_cost for item in pack.included_chunks)
    file_waste = sum(
        item.token_cost for item in pack.included_chunks if item.chunk.path != "service.py"
    )
    symbol_waste = sum(
        item.token_cost for item in pack.included_chunks if item.chunk.symbol != "checkout"
    )

    assert result.file_context_token_waste == pytest.approx(file_waste / total)
    assert result.symbol_context_token_waste == pytest.approx(symbol_waste / total)


def test_budget_utilization_uses_complete_pack_cost_over_configured_budget() -> None:
    pack = _completed_pack()
    result = score_context_pack(
        _case(),
        ContextEvaluationVariant.HYBRID_STRUCTURE,
        pack,
        latency_ms=1.0,
    )

    assert result.budget_utilization == pytest.approx(
        pack.total_token_cost / pack.configured_budget
    )


def test_absent_symbol_labels_produce_none_for_all_symbol_context_metrics() -> None:
    result = score_context_pack(
        _case(symbols=None),
        ContextEvaluationVariant.HYBRID_STRUCTURE,
        _completed_pack(),
        latency_ms=1.0,
    )

    assert result.symbol_context_coverage is None
    assert result.symbol_context_chunk_precision is None
    assert result.symbol_context_token_waste is None


def test_gold_labels_never_reach_retriever_expander_or_packer_boundary() -> None:
    spy = SpyContextPipeline(_completed_pack())
    harness = ContextEvaluationHarness(
        {ContextEvaluationVariant.HYBRID_STRUCTURE: spy}
    )
    case = RetrievalCase(
        case_id="no-context-gold-leak",
        query="only issue text crosses the boundary",
        repository_ref="backend/tests/fixtures/structure_repo",
        relevant_files=("secret_gold_file.py",),
        relevant_symbols=("secret_gold_symbol",),
    )

    asyncio.run(
        harness.evaluate_case(
            case,
            ContextEvaluationVariant.HYBRID_STRUCTURE,
            top_k=3,
        )
    )

    assert spy.calls == [("only issue text crosses the boundary", 3)]


def test_context_aggregate_calculations_are_order_independent() -> None:
    first = score_context_pack(
        _case(),
        ContextEvaluationVariant.HYBRID_STRUCTURE,
        _completed_pack(),
        latency_ms=1.0,
    )
    second = score_context_pack(
        _case(symbols=None),
        ContextEvaluationVariant.HYBRID_STRUCTURE,
        _completed_pack(),
        latency_ms=2.0,
    )

    assert aggregate_context_results((first, second)) == aggregate_context_results(
        (second, first)
    )


def test_controlled_context_evaluation_runs_end_to_end_without_ollama() -> None:
    chunks = _chunks()
    lexical = SQLiteLexicalIndex()
    lexical.rebuild(chunks)
    vector = ChromaVectorIndex(
        ControlledStructureEmbeddingProvider(),
        collection_name="task012_controlled_structure",
    )
    asyncio.run(vector.rebuild(chunks))
    hybrid = HybridRetriever(lexical, vector, candidate_k=5)
    pipeline = StructuralContextPipeline(
        hybrid,
        StructuralExpander(StructuralIndex(chunks)),
        ContextPacker(ExactCharacterCounter()),
        budget=100_000,
    )
    harness = ContextEvaluationHarness(
        {ContextEvaluationVariant.HYBRID_STRUCTURE: pipeline}
    )

    case = load_retrieval_cases(CASES_PATH)[0]
    result = asyncio.run(
        harness.evaluate_case(
            case,
            ContextEvaluationVariant.HYBRID_STRUCTURE,
            top_k=1,
        )
    )

    assert result.included_chunk_ids
    assert result.file_context_coverage is True
    assert result.symbol_context_coverage is True
    assert result.degraded is False
    json.dumps(result.to_dict())
    lexical.close()
