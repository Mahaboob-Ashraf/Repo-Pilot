"""Variant-neutral retrieval evaluation with explicit, inspectable metrics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import math
from time import perf_counter
from typing import Protocol

from app.chunking import CodeChunk
from app.evaluation.cases import RetrievalCase
from app.retrieval import (
    HybridRetriever,
    SQLiteLexicalIndex,
)
from app.retrieval.vector import ChromaVectorIndex


MIN_CASES_FOR_LATENCY_PERCENTILES = 5


class EvaluationVariant(StrEnum):
    """Implemented AST retrieval variants; later variants can extend this enum."""

    AST_BM25 = "ast_bm25"
    AST_DENSE = "ast_dense"
    AST_HYBRID_RRF = "ast_hybrid_rrf"


@dataclass(frozen=True, slots=True)
class EvaluationHit:
    """Minimal ranked provenance needed to score and inspect retrieval."""

    chunk_id: str
    rank: int
    path: str
    symbol: str
    qualified_symbol: str

    @classmethod
    def from_chunk(cls, chunk: CodeChunk, *, rank: int) -> EvaluationHit:
        return cls(
            chunk_id=chunk.chunk_id,
            rank=rank,
            path=chunk.path,
            symbol=chunk.symbol,
            qualified_symbol=chunk.qualified_symbol,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "rank": self.rank,
            "path": self.path,
            "symbol": self.symbol,
            "qualified_symbol": self.qualified_symbol,
        }


@dataclass(frozen=True, slots=True)
class EvaluationRetrievalResponse:
    """Adapter response shared by BM25, dense, and hybrid variants."""

    hits: tuple[EvaluationHit, ...]
    degraded: bool = False
    retrieval_mode: str = "normal"


class EvaluationRetriever(Protocol):
    async def retrieve(
        self,
        query: str,
        *,
        top_k: int,
    ) -> EvaluationRetrievalResponse:
        """Retrieve using query text only; evaluation labels are never accepted."""


class LexicalEvaluationRetriever:
    def __init__(self, index: SQLiteLexicalIndex) -> None:
        self._index = index

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int,
    ) -> EvaluationRetrievalResponse:
        results = self._index.search_lexical(query, k=top_k)
        return EvaluationRetrievalResponse(
            hits=tuple(
                EvaluationHit.from_chunk(result.chunk, rank=result.rank)
                for result in results
            ),
            retrieval_mode=EvaluationVariant.AST_BM25.value,
        )


class DenseEvaluationRetriever:
    def __init__(self, index: ChromaVectorIndex) -> None:
        self._index = index

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int,
    ) -> EvaluationRetrievalResponse:
        results = await self._index.search_vector(query, k=top_k)
        return EvaluationRetrievalResponse(
            hits=tuple(
                EvaluationHit.from_chunk(result.chunk, rank=result.rank)
                for result in results
            ),
            retrieval_mode=EvaluationVariant.AST_DENSE.value,
        )


class HybridEvaluationRetriever:
    def __init__(self, retriever: HybridRetriever) -> None:
        self._retriever = retriever

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int,
    ) -> EvaluationRetrievalResponse:
        response = await self._retriever.search_hybrid(query, top_k=top_k)
        return EvaluationRetrievalResponse(
            hits=tuple(
                EvaluationHit.from_chunk(result.chunk, rank=result.rank)
                for result in response.results
            ),
            degraded=response.degraded,
            retrieval_mode=response.mode.value,
        )


@dataclass(frozen=True, slots=True)
class PerCaseEvaluationResult:
    """Inspectable result and metrics for one case/variant execution."""

    case_id: str
    variant: EvaluationVariant
    returned_hits: tuple[EvaluationHit, ...]
    relevant_files: tuple[str, ...]
    relevant_symbols: tuple[str, ...] | None
    file_hit_at_1: bool
    file_hit_at_5: bool
    symbol_hit_at_1: bool | None
    symbol_hit_at_5: bool | None
    file_reciprocal_rank: float
    symbol_reciprocal_rank: float | None
    latency_ms: float
    degraded: bool
    retrieval_mode: str

    @property
    def returned_chunk_ids(self) -> tuple[str, ...]:
        return tuple(hit.chunk_id for hit in self.returned_hits)

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "variant": self.variant.value,
            "returned_hits": [hit.to_dict() for hit in self.returned_hits],
            "returned_chunk_ids": list(self.returned_chunk_ids),
            "relevant_files": list(self.relevant_files),
            "relevant_symbols": (
                list(self.relevant_symbols)
                if self.relevant_symbols is not None
                else None
            ),
            "file_hit_at_1": self.file_hit_at_1,
            "file_hit_at_5": self.file_hit_at_5,
            "symbol_hit_at_1": self.symbol_hit_at_1,
            "symbol_hit_at_5": self.symbol_hit_at_5,
            "file_reciprocal_rank": self.file_reciprocal_rank,
            "symbol_reciprocal_rank": self.symbol_reciprocal_rank,
            "latency_ms": self.latency_ms,
            "degraded": self.degraded,
            "retrieval_mode": self.retrieval_mode,
        }


@dataclass(frozen=True, slots=True)
class AggregateEvaluationResult:
    """Deterministic metric aggregates for one retrieval variant."""

    variant: EvaluationVariant
    case_count: int
    symbol_case_count: int
    file_hit_at_1_rate: float
    file_hit_at_5_rate: float
    symbol_hit_at_1_rate: float | None
    symbol_hit_at_5_rate: float | None
    mean_file_reciprocal_rank: float
    mean_symbol_reciprocal_rank: float | None
    degraded_case_count: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "variant": self.variant.value,
            "case_count": self.case_count,
            "symbol_case_count": self.symbol_case_count,
            "file_hit_at_1_rate": self.file_hit_at_1_rate,
            "file_hit_at_5_rate": self.file_hit_at_5_rate,
            "symbol_hit_at_1_rate": self.symbol_hit_at_1_rate,
            "symbol_hit_at_5_rate": self.symbol_hit_at_5_rate,
            "mean_file_reciprocal_rank": self.mean_file_reciprocal_rank,
            "mean_symbol_reciprocal_rank": self.mean_symbol_reciprocal_rank,
            "degraded_case_count": self.degraded_case_count,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
        }


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    case_results: tuple[PerCaseEvaluationResult, ...]
    aggregates: tuple[AggregateEvaluationResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "case_results": [result.to_dict() for result in self.case_results],
            "aggregates": [aggregate.to_dict() for aggregate in self.aggregates],
        }


class RetrievalEvaluationHarness:
    """Run frozen cases against explicitly selected retrieval variants."""

    def __init__(
        self,
        retrievers: Mapping[EvaluationVariant, EvaluationRetriever],
    ) -> None:
        self._retrievers = dict(retrievers)

    async def evaluate_case(
        self,
        case: RetrievalCase,
        variant: EvaluationVariant,
        *,
        top_k: int = 5,
    ) -> PerCaseEvaluationResult:
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        try:
            retriever = self._retrievers[variant]
        except KeyError as exc:
            raise ValueError(f"No retriever configured for {variant.value}") from exc

        started = perf_counter()
        response = await retriever.retrieve(case.query, top_k=top_k)
        latency_ms = (perf_counter() - started) * 1000.0
        return score_case(
            case,
            variant,
            response,
            latency_ms=latency_ms,
        )

    async def evaluate(
        self,
        cases: Sequence[RetrievalCase],
        variants: Sequence[EvaluationVariant],
        *,
        top_k: int = 5,
    ) -> EvaluationReport:
        results = tuple(
            [
                await self.evaluate_case(case, variant, top_k=top_k)
                for variant in variants
                for case in cases
            ]
        )
        aggregates = tuple(
            aggregate_case_results(
                tuple(result for result in results if result.variant is variant)
            )
            for variant in variants
        )
        return EvaluationReport(case_results=results, aggregates=aggregates)


def score_case(
    case: RetrievalCase,
    variant: EvaluationVariant,
    response: EvaluationRetrievalResponse,
    *,
    latency_ms: float,
) -> PerCaseEvaluationResult:
    """Score file and optional symbol relevance over one ranked response."""

    if not math.isfinite(latency_ms) or latency_ms < 0:
        raise ValueError("latency_ms must be finite and nonnegative")
    ranked_hits = tuple(sorted(response.hits, key=lambda hit: hit.rank))
    ranks = tuple(hit.rank for hit in ranked_hits)
    if any(
        isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0
        for rank in ranks
    ):
        raise ValueError("Evaluation hit ranks must be positive integers")
    if len(set(ranks)) != len(ranks):
        raise ValueError("Evaluation hit ranks must be unique")
    file_ranks = tuple(
        hit.rank for hit in ranked_hits if hit.path in case.relevant_files
    )
    symbol_ranks = (
        tuple(
            hit.rank
            for hit in ranked_hits
            if hit.symbol in case.relevant_symbols
            or hit.qualified_symbol in case.relevant_symbols
        )
        if case.relevant_symbols is not None
        else None
    )

    return PerCaseEvaluationResult(
        case_id=case.case_id,
        variant=variant,
        returned_hits=ranked_hits,
        relevant_files=case.relevant_files,
        relevant_symbols=case.relevant_symbols,
        file_hit_at_1=1 in file_ranks,
        file_hit_at_5=any(rank <= 5 for rank in file_ranks),
        symbol_hit_at_1=(
            1 in symbol_ranks if symbol_ranks is not None else None
        ),
        symbol_hit_at_5=(
            any(rank <= 5 for rank in symbol_ranks)
            if symbol_ranks is not None
            else None
        ),
        file_reciprocal_rank=_reciprocal_rank(file_ranks),
        symbol_reciprocal_rank=(
            _reciprocal_rank(symbol_ranks) if symbol_ranks is not None else None
        ),
        latency_ms=latency_ms,
        degraded=response.degraded,
        retrieval_mode=response.retrieval_mode,
    )


def aggregate_case_results(
    results: Sequence[PerCaseEvaluationResult],
) -> AggregateEvaluationResult:
    """Aggregate one variant, excluding absent symbol labels from symbol metrics."""

    if not results:
        raise ValueError("At least one per-case result is required")
    variant = results[0].variant
    if any(result.variant is not variant for result in results):
        raise ValueError("Aggregate inputs must have one evaluation variant")

    symbol_results = tuple(
        result for result in results if result.symbol_hit_at_5 is not None
    )
    latencies = tuple(result.latency_ms for result in results)
    include_percentiles = len(latencies) >= MIN_CASES_FOR_LATENCY_PERCENTILES
    return AggregateEvaluationResult(
        variant=variant,
        case_count=len(results),
        symbol_case_count=len(symbol_results),
        file_hit_at_1_rate=_mean(result.file_hit_at_1 for result in results),
        file_hit_at_5_rate=_mean(result.file_hit_at_5 for result in results),
        symbol_hit_at_1_rate=(
            _mean(result.symbol_hit_at_1 for result in symbol_results)
            if symbol_results
            else None
        ),
        symbol_hit_at_5_rate=(
            _mean(result.symbol_hit_at_5 for result in symbol_results)
            if symbol_results
            else None
        ),
        mean_file_reciprocal_rank=_mean(
            result.file_reciprocal_rank for result in results
        ),
        mean_symbol_reciprocal_rank=(
            _mean(result.symbol_reciprocal_rank for result in symbol_results)
            if symbol_results
            else None
        ),
        degraded_case_count=sum(result.degraded for result in results),
        latency_p50_ms=(
            _nearest_rank_percentile(latencies, 0.50)
            if include_percentiles
            else None
        ),
        latency_p95_ms=(
            _nearest_rank_percentile(latencies, 0.95)
            if include_percentiles
            else None
        ),
    )


def _reciprocal_rank(ranks: Sequence[int]) -> float:
    return 0.0 if not ranks else 1.0 / min(ranks)


def _mean(values: Sequence[float | bool | None]) -> float:
    numeric = tuple(sorted(float(value) for value in values if value is not None))
    if not numeric:
        raise ValueError("Mean requires at least one numeric value")
    return math.fsum(numeric) / len(numeric)


def _nearest_rank_percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]
