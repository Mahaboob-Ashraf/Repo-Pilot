"""Evaluation-only comparison of completed ContextPacks with frozen gold labels."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import math
from time import perf_counter
from typing import Protocol

from app.context_packing import ContextPack, ContextPackStatus
from app.evaluation.cases import RetrievalCase
from app.retrieval import EvidenceOrigin


class ContextEvaluationVariant(StrEnum):
    """Implemented post-retrieval context variant."""

    HYBRID_STRUCTURE = "hybrid_structure"


@dataclass(frozen=True, slots=True)
class ContextEvaluationHit:
    """Inspectable final pack order and provenance for one included chunk."""

    chunk_id: str
    position: int
    path: str
    symbol: str
    qualified_symbol: str
    origin: EvidenceOrigin
    token_cost: int

    def to_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "position": self.position,
            "path": self.path,
            "symbol": self.symbol,
            "qualified_symbol": self.qualified_symbol,
            "origin": self.origin.value,
            "token_cost": self.token_cost,
        }


class ContextEvaluationPipeline(Protocol):
    """Gold-free boundary from an issue query to a completed ContextPack."""

    async def build_context(self, query: str, *, top_k: int) -> ContextPack:
        """Build context using only the query and ordinary pipeline config."""


@dataclass(frozen=True, slots=True)
class PerCaseContextEvaluationResult:
    """Frozen-label metrics computed only after context construction completes."""

    case_id: str
    variant: ContextEvaluationVariant
    included_hits: tuple[ContextEvaluationHit, ...]
    relevant_files: tuple[str, ...]
    relevant_symbols: tuple[str, ...] | None
    file_context_coverage: bool
    symbol_context_coverage: bool | None
    file_context_chunk_precision: float | None
    symbol_context_chunk_precision: float | None
    file_context_token_waste: float | None
    symbol_context_token_waste: float | None
    budget_utilization: float
    total_token_cost: int
    configured_budget: int
    latency_ms: float
    degraded: bool
    retrieval_mode: str
    pack_status: ContextPackStatus

    @property
    def included_chunk_ids(self) -> tuple[str, ...]:
        return tuple(hit.chunk_id for hit in self.included_hits)

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "variant": self.variant.value,
            "included_hits": [hit.to_dict() for hit in self.included_hits],
            "included_chunk_ids": list(self.included_chunk_ids),
            "relevant_files": list(self.relevant_files),
            "relevant_symbols": (
                list(self.relevant_symbols)
                if self.relevant_symbols is not None
                else None
            ),
            "file_context_coverage": self.file_context_coverage,
            "symbol_context_coverage": self.symbol_context_coverage,
            "file_context_chunk_precision": self.file_context_chunk_precision,
            "symbol_context_chunk_precision": self.symbol_context_chunk_precision,
            "file_context_token_waste": self.file_context_token_waste,
            "symbol_context_token_waste": self.symbol_context_token_waste,
            "budget_utilization": self.budget_utilization,
            "total_token_cost": self.total_token_cost,
            "configured_budget": self.configured_budget,
            "latency_ms": self.latency_ms,
            "degraded": self.degraded,
            "retrieval_mode": self.retrieval_mode,
            "pack_status": self.pack_status.value,
        }


@dataclass(frozen=True, slots=True)
class AggregateContextEvaluationResult:
    """Deterministic mean context metrics for one configured variant."""

    variant: ContextEvaluationVariant
    case_count: int
    symbol_case_count: int
    file_context_coverage_rate: float
    symbol_context_coverage_rate: float | None
    mean_file_context_chunk_precision: float | None
    mean_symbol_context_chunk_precision: float | None
    mean_file_context_token_waste: float | None
    mean_symbol_context_token_waste: float | None
    mean_budget_utilization: float
    degraded_case_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "variant": self.variant.value,
            "case_count": self.case_count,
            "symbol_case_count": self.symbol_case_count,
            "file_context_coverage_rate": self.file_context_coverage_rate,
            "symbol_context_coverage_rate": self.symbol_context_coverage_rate,
            "mean_file_context_chunk_precision": (
                self.mean_file_context_chunk_precision
            ),
            "mean_symbol_context_chunk_precision": (
                self.mean_symbol_context_chunk_precision
            ),
            "mean_file_context_token_waste": self.mean_file_context_token_waste,
            "mean_symbol_context_token_waste": (
                self.mean_symbol_context_token_waste
            ),
            "mean_budget_utilization": self.mean_budget_utilization,
            "degraded_case_count": self.degraded_case_count,
        }


@dataclass(frozen=True, slots=True)
class ContextEvaluationReport:
    """Serializable per-case and aggregate context-evaluation records."""

    case_results: tuple[PerCaseContextEvaluationResult, ...]
    aggregates: tuple[AggregateContextEvaluationResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "case_results": [result.to_dict() for result in self.case_results],
            "aggregates": [aggregate.to_dict() for aggregate in self.aggregates],
        }


class ContextEvaluationHarness:
    """Build gold-free packs, then score them against hidden frozen labels."""

    def __init__(
        self,
        pipelines: Mapping[ContextEvaluationVariant, ContextEvaluationPipeline],
    ) -> None:
        self._pipelines = dict(pipelines)

    async def evaluate_case(
        self,
        case: RetrievalCase,
        variant: ContextEvaluationVariant,
        *,
        top_k: int = 5,
    ) -> PerCaseContextEvaluationResult:
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        try:
            pipeline = self._pipelines[variant]
        except KeyError as exc:
            raise ValueError(f"No context pipeline configured for {variant.value}") from exc

        started = perf_counter()
        # Gold labels deliberately do not cross this pipeline boundary.
        pack = await pipeline.build_context(case.query, top_k=top_k)
        latency_ms = (perf_counter() - started) * 1000.0
        return score_context_pack(case, variant, pack, latency_ms=latency_ms)

    async def evaluate(
        self,
        cases: Sequence[RetrievalCase],
        variants: Sequence[ContextEvaluationVariant],
        *,
        top_k: int = 5,
    ) -> ContextEvaluationReport:
        results = tuple(
            [
                await self.evaluate_case(case, variant, top_k=top_k)
                for variant in variants
                for case in cases
            ]
        )
        aggregates = tuple(
            aggregate_context_results(
                tuple(result for result in results if result.variant is variant)
            )
            for variant in variants
        )
        return ContextEvaluationReport(
            case_results=results,
            aggregates=aggregates,
        )


def score_context_pack(
    case: RetrievalCase,
    variant: ContextEvaluationVariant,
    pack: ContextPack,
    *,
    latency_ms: float,
) -> PerCaseContextEvaluationResult:
    """Compare a completed ContextPack to labels that did not influence it."""

    if not math.isfinite(latency_ms) or latency_ms < 0:
        raise ValueError("latency_ms must be finite and nonnegative")

    hits = tuple(
        ContextEvaluationHit(
            chunk_id=item.chunk_id,
            position=position,
            path=item.chunk.path,
            symbol=item.chunk.symbol,
            qualified_symbol=item.chunk.qualified_symbol,
            origin=item.origin,
            token_cost=item.token_cost,
        )
        for position, item in enumerate(pack.included_chunks, start=1)
    )
    file_matches = tuple(hit.path in case.relevant_files for hit in hits)
    symbol_matches = (
        tuple(
            hit.symbol in case.relevant_symbols
            or hit.qualified_symbol in case.relevant_symbols
            for hit in hits
        )
        if case.relevant_symbols is not None
        else None
    )

    return PerCaseContextEvaluationResult(
        case_id=case.case_id,
        variant=variant,
        included_hits=hits,
        relevant_files=case.relevant_files,
        relevant_symbols=case.relevant_symbols,
        file_context_coverage=any(file_matches),
        symbol_context_coverage=(
            any(symbol_matches) if symbol_matches is not None else None
        ),
        file_context_chunk_precision=_precision(file_matches),
        symbol_context_chunk_precision=(
            _precision(symbol_matches) if symbol_matches is not None else None
        ),
        file_context_token_waste=_token_waste(hits, file_matches),
        symbol_context_token_waste=(
            _token_waste(hits, symbol_matches)
            if symbol_matches is not None
            else None
        ),
        budget_utilization=pack.total_token_cost / pack.configured_budget,
        total_token_cost=pack.total_token_cost,
        configured_budget=pack.configured_budget,
        latency_ms=latency_ms,
        degraded=pack.degraded,
        retrieval_mode=pack.retrieval_mode.value,
        pack_status=pack.status,
    )


def aggregate_context_results(
    results: Sequence[PerCaseContextEvaluationResult],
) -> AggregateContextEvaluationResult:
    if not results:
        raise ValueError("At least one per-case result is required")
    variant = results[0].variant
    if any(result.variant is not variant for result in results):
        raise ValueError("Aggregate inputs must have one evaluation variant")
    symbol_results = tuple(
        result for result in results if result.symbol_context_coverage is not None
    )
    return AggregateContextEvaluationResult(
        variant=variant,
        case_count=len(results),
        symbol_case_count=len(symbol_results),
        file_context_coverage_rate=_mean(
            result.file_context_coverage for result in results
        ),
        symbol_context_coverage_rate=(
            _mean(result.symbol_context_coverage for result in symbol_results)
            if symbol_results
            else None
        ),
        mean_file_context_chunk_precision=_optional_mean(
            result.file_context_chunk_precision for result in results
        ),
        mean_symbol_context_chunk_precision=_optional_mean(
            result.symbol_context_chunk_precision for result in symbol_results
        ),
        mean_file_context_token_waste=_optional_mean(
            result.file_context_token_waste for result in results
        ),
        mean_symbol_context_token_waste=_optional_mean(
            result.symbol_context_token_waste for result in symbol_results
        ),
        mean_budget_utilization=_mean(
            result.budget_utilization for result in results
        ),
        degraded_case_count=sum(result.degraded for result in results),
    )


def _precision(matches: Sequence[bool]) -> float | None:
    return None if not matches else sum(matches) / len(matches)


def _token_waste(
    hits: Sequence[ContextEvaluationHit],
    matches: Sequence[bool],
) -> float | None:
    total = sum(hit.token_cost for hit in hits)
    if total == 0:
        return None
    wasted = sum(
        hit.token_cost for hit, relevant in zip(hits, matches, strict=True)
        if not relevant
    )
    return wasted / total


def _optional_mean(values: Sequence[float | None]) -> float | None:
    present = tuple(value for value in values if value is not None)
    return _mean(present) if present else None


def _mean(values: Sequence[float | bool | None]) -> float:
    numeric = tuple(sorted(float(value) for value in values if value is not None))
    if not numeric:
        raise ValueError("Mean requires at least one numeric value")
    return math.fsum(numeric) / len(numeric)
