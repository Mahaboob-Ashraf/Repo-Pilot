from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.chunking import build_repository_chunks
from app.context_packing import ContextPacker
from app.evaluation import (
    EvaluationHit,
    EvaluationRetrievalResponse,
    EvaluationVariant,
    FROZEN_SAFETY_SCENARIOS,
    RetrievalCase,
    aggregate_structural_results,
    load_retrieval_cases,
    run_safety_evaluation,
    score_case,
    score_structural_expansion,
)
from app.evaluation.m8 import (
    DEFAULT_CASES,
    REPOSITORY_ROOT,
    _artifact_identity,
    _fixture_fingerprint,
    render_markdown_report,
    run_m8,
    _run_context_budget_scenarios,
    _run_degraded_structure,
)
from app.retrieval import (
    HybridRetrievalMode,
    HybridSearchResponse,
    HybridSearchResult,
    RetrievalSource,
    StructuralExpander,
    StructuralIndex,
)


def test_frozen_m8_cases_are_deterministic_and_varied() -> None:
    first = load_retrieval_cases(DEFAULT_CASES)
    second = load_retrieval_cases(DEFAULT_CASES)

    assert first == second
    assert len(first) == 10
    assert len({case.case_id for case in first}) == 10
    assert len({case.repository_ref for case in first}) == 4
    assert all("evaluation/fixtures/m8/repositories/" in case.repository_ref for case in first)


def test_duplicate_case_ids_and_malformed_gold_paths_are_rejected(tmp_path: Path) -> None:
    duplicate = {
        "case_id": "duplicate",
        "query": "query",
        "repository_ref": "evaluation/fixtures/m8/repositories/commerce",
        "relevant_files": ["pricing.py"],
    }
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps([duplicate, duplicate]), encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_retrieval_cases(path)

    with pytest.raises(ValueError, match="normalized relative POSIX"):
        RetrievalCase(
            case_id="bad-path",
            query="query",
            repository_ref="evaluation/fixtures/m8/repositories/commerce",
            relevant_files=("../secret.py",),
        )


def test_symbol_hit_at_1_and_unlabeled_symbol_metrics_are_honest() -> None:
    labeled = RetrievalCase(
        case_id="labeled", query="q", repository_ref="repo",
        relevant_files=("target.py",), relevant_symbols=("target",),
    )
    hit = EvaluationHit("id", 1, "target.py", "target", "target")
    result = score_case(
        labeled, EvaluationVariant.AST_BM25,
        EvaluationRetrievalResponse((hit,)), latency_ms=1.0,
    )
    assert result.symbol_hit_at_1 is True

    unlabeled = RetrievalCase(
        case_id="unlabeled", query="q", repository_ref="repo",
        relevant_files=("target.py",), relevant_symbols=None,
    )
    no_symbol = score_case(
        unlabeled, EvaluationVariant.AST_BM25,
        EvaluationRetrievalResponse((hit,)), latency_ms=1.0,
    )
    assert no_symbol.symbol_hit_at_1 is None
    assert no_symbol.symbol_hit_at_5 is None
    assert no_symbol.symbol_reciprocal_rank is None


def test_structural_effect_accounting_identifies_gold_and_noise() -> None:
    repository = REPOSITORY_ROOT / "evaluation/fixtures/m8/repositories/structure"
    chunks = build_repository_chunks(repository).chunks
    checkout = next(chunk for chunk in chunks if chunk.symbol == "checkout_total")
    direct = HybridSearchResponse(
        results=(
            HybridSearchResult(
                chunk=checkout, rank=1, rrf_score=1 / 61,
                lexical_rank=1, vector_rank=None, lexical_bm25_score=-1.0,
                vector_cosine_distance=None,
                retrieval_sources=(RetrievalSource.LEXICAL,),
            ),
        ),
        mode=HybridRetrievalMode.HYBRID,
    )
    expansion = StructuralExpander(StructuralIndex(chunks)).expand(direct)
    case = next(
        item for item in load_retrieval_cases(DEFAULT_CASES)
        if item.case_id == "structure-adds-checkout-test"
    )

    result = score_structural_expansion(case, direct, expansion)
    aggregate = aggregate_structural_results((result,))

    assert result.expansion_added_gold is True
    assert any("related_test" in item.causes for item in result.added_chunks)
    assert aggregate.cases_helped == 1
    assert aggregate.mean_additional_chunks == len(result.added_chunks)


def test_context_pack_exclusions_record_relevant_budget_loss() -> None:
    repository = REPOSITORY_ROOT / "evaluation/fixtures/m8/repositories/commerce"
    chunks = build_repository_chunks(repository).chunks
    target = next(chunk for chunk in chunks if chunk.symbol == "discounted_total")
    response = HybridSearchResponse(
        results=(
            HybridSearchResult(
                chunk=target, rank=1, rrf_score=1 / 61,
                lexical_rank=1, vector_rank=None, lexical_bm25_score=-1.0,
                vector_cosine_distance=None,
                retrieval_sources=(RetrievalSource.LEXICAL,),
            ),
        ), mode=HybridRetrievalMode.HYBRID,
    )
    expansion = StructuralExpander(StructuralIndex(chunks)).expand(response)
    full = ContextPacker().pack("discount", expansion, budget=100_000)
    boundary_budget = full.base_token_cost + full.included_chunks[0].token_cost - 1
    limited = ContextPacker().pack("discount", expansion, budget=boundary_budget)

    from app.evaluation.context import ContextEvaluationVariant, score_context_pack

    case = RetrievalCase(
        case_id="budget", query="discount", repository_ref="repo",
        relevant_files=("pricing.py",), relevant_symbols=("discounted_total",),
    )
    scored = score_context_pack(
        case, ContextEvaluationVariant.HYBRID_STRUCTURE, limited, latency_ms=1.0
    )
    assert scored.pack_status.value == "oversized_highest_priority"
    assert scored.gold_file_coverage == 0.0
    assert scored.relevant_evidence_excluded_by_budget is True
    assert scored.excluded_candidates[0].reason == "budget_exceeded"


def test_production_budget_scenarios_cover_fit_competition_boundary_and_oversize() -> None:
    report = _run_context_budget_scenarios()
    cases = {item["case_id"]: item for item in report["cases"]}

    assert cases["all_evidence_fits"]["pack_status"] == "complete"
    assert cases["useful_evidence_competes"]["relevant_evidence_excluded_by_budget"] is True
    assert cases["highest_priority_near_boundary"]["used_units"] <= 16_384
    assert cases["oversized_highest_priority"]["pack_status"] == "oversized_highest_priority"


def test_degraded_structure_uses_production_lexical_fallback_without_fake_embeddings() -> None:
    report = asyncio.run(_run_degraded_structure(load_retrieval_cases(DEFAULT_CASES)))

    assert report["status"] == "measured_degraded"
    assert report["retrieval_mode"] == "lexical_only_degraded"
    assert report["structure_aggregate"]["case_count"] == 10
    assert report["context_aggregate"]["degraded_case_count"] == 10


def test_safety_matrix_runs_every_frozen_scenario_and_keeps_failures_visible() -> None:
    report = run_safety_evaluation()

    assert len(FROZEN_SAFETY_SCENARIOS) == 33
    assert len(report.scenarios) == 33
    assert sum(row.scenarios for row in report.scorecard) == 33
    assert report.passed is True, [
        (item.scenario_id, item.observed_outcome, item.safe_error_classification)
        for item in report.scenarios
        if not item.passed
    ]
    assert all(not item.canonical_repository_changed for item in report.scenarios)


def test_one_critical_failed_safety_proof_fails_the_report() -> None:
    report = run_safety_evaluation(
        proof_overrides={
            "S01": lambda: (False, "unsafe action accepted", "missing_rejection")
        }
    )

    assert report.passed is False
    assert next(item for item in report.scenarios if item.scenario_id == "S01").passed is False
    assert next(row for row in report.scorecard if row.category == "Scope authority").failed == 1


def test_fixture_and_artifact_identity_are_path_and_time_independent() -> None:
    cases = load_retrieval_cases(DEFAULT_CASES)
    first = _fixture_fingerprint(cases, DEFAULT_CASES)
    second = _fixture_fingerprint(cases, DEFAULT_CASES)

    assert first == second
    assert _artifact_identity(first) == _artifact_identity(second)
    assert str(REPOSITORY_ROOT) not in first


def test_safety_only_artifact_is_json_safe_and_contains_no_absolute_host_path() -> None:
    artifact = asyncio.run(run_m8(mode="safety"))
    serialized = json.dumps(artifact, sort_keys=True)

    assert artifact["schema_version"] == "repopilot.m8.v1"
    assert str(REPOSITORY_ROOT) not in serialized
    assert "C:\\Users" not in serialized
    assert "traceback" not in serialized.casefold()
    report = render_markdown_report(artifact)
    assert "Safety scorecard" in report
    assert "not SWE-bench" in report


def test_runner_contains_no_download_or_pull_operation() -> None:
    source = (REPOSITORY_ROOT / "backend/app/evaluation/m8.py").read_text(encoding="utf-8")

    assert "ollama pull" not in source
    assert "docker pull" not in source
    assert "snapshot_download" not in source
