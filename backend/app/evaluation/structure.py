"""Evaluation-only accounting for production one-hop structural expansion."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from app.context_packing import ConservativeTokenEstimator
from app.evaluation.cases import RetrievalCase
from app.retrieval import EvidenceOrigin, HybridSearchResponse, StructuralExpansionResult


@dataclass(frozen=True, slots=True)
class StructuralAddedChunk:
    chunk_id: str
    path: str
    symbol: str
    causes: tuple[str, ...]
    adds_gold_evidence: bool
    estimated_source_units: int

    def to_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "path": self.path,
            "symbol": self.symbol,
            "causes": list(self.causes),
            "adds_gold_evidence": self.adds_gold_evidence,
            "estimated_source_units": self.estimated_source_units,
        }


@dataclass(frozen=True, slots=True)
class PerCaseStructuralResult:
    case_id: str
    direct_chunk_ids: tuple[str, ...]
    added_chunks: tuple[StructuralAddedChunk, ...]
    expansion_added_gold: bool
    expansion_added_non_gold: bool
    direct_file_precision: float | None
    expanded_file_precision: float | None
    direct_source_waste: float | None
    expanded_source_waste: float | None
    additional_estimated_source_units: int

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "direct_chunk_ids": list(self.direct_chunk_ids),
            "added_chunks": [item.to_dict() for item in self.added_chunks],
            "expansion_added_gold": self.expansion_added_gold,
            "expansion_added_non_gold": self.expansion_added_non_gold,
            "direct_file_precision": self.direct_file_precision,
            "expanded_file_precision": self.expanded_file_precision,
            "direct_source_waste": self.direct_source_waste,
            "expanded_source_waste": self.expanded_source_waste,
            "additional_estimated_source_units": (
                self.additional_estimated_source_units
            ),
        }


@dataclass(frozen=True, slots=True)
class AggregateStructuralResult:
    case_count: int
    cases_helped: int
    cases_unchanged: int
    cases_only_noise: int
    mean_additional_chunks: float
    mean_additional_estimated_source_units: float
    added_cause_counts: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "case_count": self.case_count,
            "cases_helped": self.cases_helped,
            "cases_unchanged": self.cases_unchanged,
            "cases_only_noise": self.cases_only_noise,
            "mean_additional_chunks": self.mean_additional_chunks,
            "mean_additional_estimated_source_units": (
                self.mean_additional_estimated_source_units
            ),
            "added_cause_counts": dict(sorted(self.added_cause_counts.items())),
        }


def score_structural_expansion(
    case: RetrievalCase,
    direct: HybridSearchResponse,
    expansion: StructuralExpansionResult,
) -> PerCaseStructuralResult:
    """Apply gold labels only after production retrieval and expansion finish."""

    direct_ids = tuple(result.chunk_id for result in direct.results)
    direct_id_set = set(direct_ids)
    estimator = ConservativeTokenEstimator()
    added = tuple(
        StructuralAddedChunk(
            chunk_id=candidate.chunk_id,
            path=candidate.chunk.path,
            symbol=candidate.chunk.qualified_symbol,
            causes=tuple(
                sorted({cause.relation.value for cause in candidate.structural_causes})
            ),
            adds_gold_evidence=_is_gold(
                candidate.chunk.path,
                candidate.chunk.symbol,
                candidate.chunk.qualified_symbol,
                case,
            ),
            estimated_source_units=estimator.count_tokens(candidate.chunk.source_text),
        )
        for candidate in expansion.candidates
        if candidate.origin is EvidenceOrigin.STRUCTURAL
        and candidate.chunk_id not in direct_id_set
    )
    expanded_chunks = tuple(candidate.chunk for candidate in expansion.candidates)
    direct_chunks = tuple(result.chunk for result in direct.results)
    return PerCaseStructuralResult(
        case_id=case.case_id,
        direct_chunk_ids=direct_ids,
        added_chunks=added,
        expansion_added_gold=any(item.adds_gold_evidence for item in added),
        expansion_added_non_gold=any(not item.adds_gold_evidence for item in added),
        direct_file_precision=_file_precision(direct_chunks, case),
        expanded_file_precision=_file_precision(expanded_chunks, case),
        direct_source_waste=_source_waste(direct_chunks, case, estimator),
        expanded_source_waste=_source_waste(expanded_chunks, case, estimator),
        additional_estimated_source_units=sum(
            item.estimated_source_units for item in added
        ),
    )


def aggregate_structural_results(
    results: Sequence[PerCaseStructuralResult],
) -> AggregateStructuralResult:
    if not results:
        raise ValueError("At least one structural result is required")
    causes: Counter[str] = Counter(
        cause
        for result in results
        for item in result.added_chunks
        for cause in item.causes
    )
    return AggregateStructuralResult(
        case_count=len(results),
        cases_helped=sum(result.expansion_added_gold for result in results),
        cases_unchanged=sum(not result.added_chunks for result in results),
        cases_only_noise=sum(
            bool(result.added_chunks) and not result.expansion_added_gold
            for result in results
        ),
        mean_additional_chunks=(
            sum(len(result.added_chunks) for result in results) / len(results)
        ),
        mean_additional_estimated_source_units=(
            sum(result.additional_estimated_source_units for result in results)
            / len(results)
        ),
        added_cause_counts=dict(causes),
    )


def _is_gold(path: str, symbol: str, qualified_symbol: str, case: RetrievalCase) -> bool:
    if path in case.relevant_files:
        return True
    return case.relevant_symbols is not None and (
        symbol in case.relevant_symbols or qualified_symbol in case.relevant_symbols
    )


def _file_precision(chunks, case: RetrievalCase) -> float | None:
    return (
        None
        if not chunks
        else sum(chunk.path in case.relevant_files for chunk in chunks) / len(chunks)
    )


def _source_waste(chunks, case: RetrievalCase, estimator) -> float | None:
    costs = tuple(estimator.count_tokens(chunk.source_text) for chunk in chunks)
    total = sum(costs)
    if total == 0:
        return None
    wasted = sum(
        cost
        for chunk, cost in zip(chunks, costs, strict=True)
        if chunk.path not in case.relevant_files
    )
    return wasted / total


__all__ = [
    "AggregateStructuralResult",
    "PerCaseStructuralResult",
    "StructuralAddedChunk",
    "aggregate_structural_results",
    "score_structural_expansion",
]
