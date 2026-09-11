"""Frozen retrieval evaluation cases, adapters, metrics, and reports."""

from app.evaluation.cases import RetrievalCase, load_retrieval_cases
from app.evaluation.harness import (
    MIN_CASES_FOR_LATENCY_PERCENTILES,
    AggregateEvaluationResult,
    DenseEvaluationRetriever,
    EvaluationHit,
    EvaluationReport,
    EvaluationRetrievalResponse,
    EvaluationVariant,
    HybridEvaluationRetriever,
    LexicalEvaluationRetriever,
    PerCaseEvaluationResult,
    RetrievalEvaluationHarness,
    aggregate_case_results,
    score_case,
)

__all__ = [
    "MIN_CASES_FOR_LATENCY_PERCENTILES",
    "AggregateEvaluationResult",
    "DenseEvaluationRetriever",
    "EvaluationHit",
    "EvaluationReport",
    "EvaluationRetrievalResponse",
    "EvaluationVariant",
    "HybridEvaluationRetriever",
    "LexicalEvaluationRetriever",
    "PerCaseEvaluationResult",
    "RetrievalCase",
    "RetrievalEvaluationHarness",
    "aggregate_case_results",
    "load_retrieval_cases",
    "score_case",
]
