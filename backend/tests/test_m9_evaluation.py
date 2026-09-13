from __future__ import annotations

import asyncio
from copy import deepcopy
import inspect
import json
from pathlib import Path

import pytest

from app.evaluation.m9 import (
    DEFAULT_MANIFEST,
    REPOSITORY_ROOT,
    build_artifact,
    render_report,
    run_fake_evaluation,
    verify_fixture_tests,
)
from app.evaluation.m9_models import (
    AttemptClassification,
    AttemptRecord,
    ExecutionObservation,
    M9Manifest,
    ProductionCaseInput,
    StageLatencies,
    aggregate_scores,
    assert_artifact_has_no_absolute_paths,
    benchmark_final_decision,
    benchmark_plan_decision,
    classify_attempt,
    load_m9_manifest,
    repair_succeeded,
    score_case,
)
from app.patching import PatchArtifact
from app.planning import PlanningEvidence, RepairPlan, RepairStep
from app.sandbox import (
    TestMode as SandboxTestMode,
    TestResourcePolicy as SandboxResourcePolicy,
    TestRunResult as SandboxRunResult,
    TestStatus as SandboxTestStatus,
)
from app.workflow import ApprovalPayload, PlanReviewResult, WorkflowStatus


@pytest.fixture(scope="module")
def manifest() -> M9Manifest:
    return load_m9_manifest(DEFAULT_MANIFEST)


def _payload() -> dict:
    return json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))


def _v2_manifest() -> M9Manifest:
    return load_m9_manifest(
        REPOSITORY_ROOT / "evaluation/fixtures/m9/manifest-v2.json"
    )


def test_manifest_requires_pinned_full_sha() -> None:
    payload = _payload()
    payload["repositories"][0]["commit_sha"] = "main"
    with pytest.raises(ValueError):
        M9Manifest.model_validate(payload)


def test_duplicate_case_id_is_rejected() -> None:
    payload = _payload()
    payload["cases"].append(deepcopy(payload["cases"][0]))
    with pytest.raises(ValueError, match="case IDs must be unique"):
        M9Manifest.model_validate(payload)


def test_malformed_repository_provenance_is_rejected() -> None:
    payload = _payload()
    payload["repositories"][0]["upstream_url"] = "https://example.test/mutable.zip"
    with pytest.raises(ValueError):
        M9Manifest.model_validate(payload)


def test_manifest_is_three_external_repositories_and_six_controlled_cases(manifest: M9Manifest) -> None:
    assert len(manifest.repositories) == 3
    assert len(manifest.cases) == 6
    assert all(case.case_type == "external-repository controlled-defect case" for case in manifest.cases)
    assert all(repository.license_identifier in {"MIT", "BSD-3-Clause"} for repository in manifest.repositories)


def test_v1_invalid_case_is_preserved_and_v2_replaces_it_under_a_new_identity(
    manifest: M9Manifest,
) -> None:
    v1_case = next(
        case for case in manifest.cases
        if case.case_id == "boltons-floor-upper-choice"
    )
    v2 = _v2_manifest()
    v2_case = next(
        case for case in v2.cases
        if case.case_id == "boltons-floor-exact-option"
    )

    assert manifest.schema_version == "repopilot.m9.manifest.v1"
    assert manifest.benchmark_id == "m9-external-controlled-v1"
    assert v1_case.required_test_selectors == (
        "tests/test_mathutils.py::test_floor_sorted",
    )
    assert v2.schema_version == "repopilot.m9.manifest.v2"
    assert v2.benchmark_id == "m9-external-controlled-v2"
    assert len(v2.cases) == len(manifest.cases) == 6
    assert "boltons-floor-upper-choice" not in {
        case.case_id for case in v2.cases
    }
    assert v2_case.required_test_selectors == (
        "tests/test_mathutils.py::test_floor_basic",
    )
    assert v2_case.controlled_mutation == v1_case.controlled_mutation
    assert v2_case.evaluation_oracle == v1_case.evaluation_oracle
    assert v2_case.fixture_fingerprint == v1_case.fixture_fingerprint
    assert v2.fingerprint != manifest.fingerprint


def test_gold_patch_and_files_do_not_enter_production_case_input(manifest: M9Manifest, tmp_path: Path) -> None:
    case = manifest.cases[0]
    fixture = tmp_path / case.case_id
    fixture.mkdir()
    production = ProductionCaseInput.from_case(case, fixture_root=tmp_path)
    serialized = production.model_dump_json()

    assert case.evaluation_oracle.repair.replacement_text not in case.issue_description
    assert case.evaluation_oracle.repair.expected_old_text not in case.issue_description
    assert case.evaluation_oracle.gold_changed_files[0] not in serialized
    assert "evaluation_oracle" not in serialized
    assert "controlled_mutation" not in serialized


def test_execution_boundary_cannot_accept_gold(manifest: M9Manifest) -> None:
    fields = set(ProductionCaseInput.model_fields)
    assert fields == {"case_id", "repository_id", "repository_root", "issue", "test_selectors"}
    assert "gold" not in inspect.signature(benchmark_plan_decision).parameters
    assert "gold" not in inspect.signature(benchmark_final_decision).parameters


def test_fixture_test_selection_must_be_an_exact_loaded_manifest_case(
    manifest: M9Manifest, tmp_path: Path
) -> None:
    case = manifest.cases[0]
    altered = case.model_copy(
        update={"issue_description": "different untrusted issue text"}
    )

    with pytest.raises(
        ValueError, match="selection must belong to the loaded manifest"
    ):
        asyncio.run(
            verify_fixture_tests(
                manifest,
                fixture_root=tmp_path,
                cases=(altered,),
            )
        )


def _review_objects() -> tuple[PlanningEvidence, RepairPlan, ApprovalPayload]:
    evidence = PlanningEvidence(
        chunk_id="target.py::function::repair::1-2", path="target.py",
        qualified_symbol="repair", chunk_type="function", start_line=1,
        end_line=2, content_hash="a" * 64, source_text="def repair():\n    pass",
        origin="retrieved", source_retrieval_rank=1,
    )
    plan = RepairPlan(
        summary="repair behavior", diagnosis="bounded diagnosis",
        proposed_files=("target.py",),
        steps=(RepairStep(description="fix", affected_files=("target.py",), evidence_chunk_ids=(evidence.chunk_id,)),),
        suggested_tests=("tests/test_target.py",),
    )
    payload = ApprovalPayload(
        question="approve?", plan=plan, plan_hash="b" * 64,
        proposed_file_scope=("target.py",), evidence=(evidence,),
    )
    return evidence, plan, payload


def test_benchmark_approval_one_uses_only_grounded_workflow_artifact() -> None:
    evidence, plan, payload = _review_objects()
    result = PlanReviewResult(
        thread_id="thread", status=WorkflowStatus.AWAITING_APPROVAL,
        evidence=(evidence,), plan=plan, plan_hash="b" * 64, approval_payload=payload,
    )
    decision = benchmark_plan_decision(result)
    assert decision is not None
    assert decision.plan_hash == "b" * 64


def _passing_test(patch_hash: str = "c" * 64) -> SandboxRunResult:
    return SandboxRunResult(
        test_run_id="d" * 64, patch_hash=patch_hash, workspace_id="workspace",
        mode=SandboxTestMode.TARGETED, validated_selectors=("tests/test_target.py",),
        status=SandboxTestStatus.PASSED, exit_code=0, duration_ms=1, stdout="", stderr="",
        output_truncated=False, image_reference="repopilot-python-test:3.11-pytest9",
        image_id="sha256:test", resource_policy=SandboxResourcePolicy(),
    )


def test_benchmark_final_approval_uses_only_passing_hash_bound_artifact() -> None:
    patch = PatchArtifact(
        workspace_id="workspace", source_plan_hash="b" * 64,
        changed_files=("target.py",), unified_diff="diff", patch_hash="c" * 64,
    )
    result = PlanReviewResult(
        thread_id="thread", status=WorkflowStatus.AWAITING_FINAL_APPROVAL,
        approved_file_scope=("target.py",), patch=patch, test=_passing_test(),
        final_candidate_patch_hash="c" * 64,
    )
    decision = benchmark_final_decision(result)
    assert decision is not None
    assert decision.patch_hash == "c" * 64


def _success_observation(*, attempts: int = 1, exact_diff: str = "different valid diff") -> ExecutionObservation:
    history = [AttemptRecord(attempt_number=1, patch_hash="a" * 64, changed_files=("target.py",), test_status="failed" if attempts == 2 else "passed", test_run_id="1" * 64)]
    if attempts == 2:
        history.append(AttemptRecord(attempt_number=2, patch_hash="b" * 64, changed_files=("target.py",), test_status="passed", test_run_id="2" * 64))
    patch_hash = history[-1].patch_hash
    return ExecutionObservation(
        case_id="case", terminal_status="completed", patch_produced=True,
        patch_hash=patch_hash, actual_changed_files=("target.py",), tests_passed=True,
        final_approval_completed=True, export_completed=True, exported_patch_hash=patch_hash,
        attempts=tuple(history), candidate_diff=exact_diff,
    )


def test_successful_workflow_is_classified_correctly() -> None:
    observation = _success_observation()
    assert repair_succeeded(observation)
    assert classify_attempt(observation) is AttemptClassification.SOLVED_ATTEMPT_1


def test_attempt_one_failure_attempt_two_success_is_classified() -> None:
    assert classify_attempt(_success_observation(attempts=2)) is AttemptClassification.SOLVED_ATTEMPT_2


def test_two_attempt_failure_is_classified() -> None:
    observation = ExecutionObservation(
        case_id="case", terminal_status="repair_failed",
        attempts=(
            AttemptRecord(attempt_number=1, patch_hash="a" * 64, test_status="failed"),
            AttemptRecord(attempt_number=2, patch_hash="b" * 64, test_status="failed"),
        ),
    )
    assert classify_attempt(observation) is AttemptClassification.FAILED_ATTEMPT_2


def test_infrastructure_blocked_is_separate() -> None:
    observation = ExecutionObservation(case_id="case", terminal_status="infrastructure_blocked", blocked_reason="docker unavailable")
    assert classify_attempt(observation) is AttemptClassification.INFRASTRUCTURE_BLOCKED
    assert not repair_succeeded(observation)


def test_invalid_frozen_fixture_is_not_infrastructure_blocked() -> None:
    observation = ExecutionObservation(
        case_id="case",
        terminal_status="benchmark_fixture_invalid",
        failure_stage="fixture validation",
        blocked_reason="configured selector passed",
    )

    assert (
        classify_attempt(observation)
        is AttemptClassification.BENCHMARK_FIXTURE_INVALID
    )


@pytest.mark.parametrize("missing", ["tests", "final", "export"])
def test_repair_success_requires_tests_final_approval_and_export(missing: str) -> None:
    values = _success_observation().model_dump()
    if missing == "tests":
        values["tests_passed"] = False
    elif missing == "final":
        values["final_approval_completed"] = False
    else:
        values["export_completed"] = False
    assert not repair_succeeded(ExecutionObservation.model_validate(values))


def test_retrieval_only_success_cannot_count_as_repair_success() -> None:
    observation = ExecutionObservation(case_id="case", terminal_status="planner_failed", ranked_files=("target.py",), context_files=("target.py",))
    assert not repair_succeeded(observation)


def test_alternate_valid_patch_can_succeed_without_exact_gold_diff(manifest: M9Manifest) -> None:
    case = manifest.cases[0]
    observation = _success_observation(exact_diff="alternate but safe implementation")
    values = observation.model_dump()
    values.update({"case_id": case.case_id, "actual_changed_files": case.evaluation_oracle.gold_changed_files})
    score = score_case(case, ExecutionObservation.model_validate(values))
    assert score["repair_success"] is True
    assert score["patch_quality"]["exact_patch_match"] is False
    assert score["patch_quality"]["behavioral_success"] is True


def test_scope_violation_is_a_critical_failure(manifest: M9Manifest) -> None:
    case = manifest.cases[0]
    observation = ExecutionObservation(case_id=case.case_id, terminal_status="patch_failed", failure_stage="patch validation", scope_violation_attempts=1)
    score = score_case(case, observation)
    assert score["safety"]["critical_failure"] is True
    assert aggregate_scores([score])["critical_safety_failure"] is True


def test_stage_failure_accounting(manifest: M9Manifest) -> None:
    scores = [score_case(manifest.cases[0], ExecutionObservation(case_id=manifest.cases[0].case_id, terminal_status="planner_failed", failure_stage="planner"))]
    assert aggregate_scores(scores)["failure_stage_counts"] == {"planner": 1}


def test_aggregate_retains_typed_planner_patch_and_safety_counts(
    manifest: M9Manifest,
) -> None:
    observations = (
        ExecutionObservation(
            case_id=manifest.cases[0].case_id,
            terminal_status="planner_failed",
            failure_stage="planner",
            failure_error_type="PlannerOutputError",
        ),
        ExecutionObservation(
            case_id=manifest.cases[1].case_id,
            terminal_status="planner_failed",
            failure_stage="planner",
            failure_error_type="PlanValidationError",
        ),
        ExecutionObservation(
            case_id=manifest.cases[2].case_id,
            terminal_status="patch_failed",
            failure_stage="patch validation",
            plan_generated=True,
            approval_1_completed=True,
            patch_validation_failures=1,
            retrieval_mode="hybrid",
            ranked_files=(manifest.cases[2].evaluation_oracle.gold_changed_files[0],),
        ),
    )
    scores = [
        score_case(case, observation)
        for case, observation in zip(manifest.cases[:3], observations, strict=True)
    ]

    aggregate = aggregate_scores(scores)

    assert aggregate["valid_case_count"] == 3
    assert aggregate["planner_outcomes"] == {
        "valid_grounded_plans": 1,
        "output_parse_failures": 1,
        "grounding_failures": 1,
        "provider_failures": 0,
    }
    assert aggregate["patch_test"]["cases_reaching_patch_generation"] == 1
    assert aggregate["patch_test"]["cases_producing_valid_patches"] == 0
    assert aggregate["retrieval_mode_counts"] == {"hybrid": 1}
    assert aggregate["safety"]["retry_limit_violation_count"] == 0


def test_typed_failure_evidence_is_retained(manifest: M9Manifest) -> None:
    case = manifest.cases[0]
    observation = ExecutionObservation(
        case_id=case.case_id,
        terminal_status="planner_failed",
        failure_stage="planner",
        failure_error_type="PlannerOutputError",
        failure_message="inference output is not a valid structured RepairPlan",
    )

    score = score_case(case, observation)

    assert score["failure_error_type"] == "PlannerOutputError"
    assert score["failure_message"] == observation.failure_message


def test_latency_accounting_has_median_and_only_adequate_p95(manifest: M9Manifest) -> None:
    scores = []
    for index in range(5):
        observation = ExecutionObservation(
            case_id=manifest.cases[index].case_id, terminal_status="planner_failed",
            latencies=StageLatencies(retrieval_ms=float(index + 1)),
        )
        scores.append(score_case(manifest.cases[index], observation))
    latency = aggregate_scores(scores)["latency_ms"]["retrieval_ms"]
    assert latency == {"count": 5, "median": 3.0, "p95": 5.0}


def test_aggregate_metrics_are_correct(manifest: M9Manifest) -> None:
    observations = [
        _success_observation(),
        _success_observation(attempts=2),
        ExecutionObservation(case_id="blocked", terminal_status="infrastructure_blocked", blocked_reason="docker"),
    ]
    scores = []
    for case, observation in zip(manifest.cases[:3], observations, strict=True):
        values = observation.model_dump()
        values["case_id"] = case.case_id
        scores.append(score_case(case, ExecutionObservation.model_validate(values)))
    aggregate = aggregate_scores(scores)
    assert aggregate["cases_attempted"] == 2
    assert aggregate["cases_completed"] == 2
    assert aggregate["repair_success_rate"] == 1.0
    assert aggregate["infrastructure_blocked_count"] == 1
    assert aggregate["patch_quality"]["cases_with_changed_files"] == 2
    assert aggregate["patch_quality"]["behavioral_success_count"] == 2
    assert aggregate["safety"]["scope_violation_attempts"] == 0


def test_artifacts_reject_absolute_paths(manifest: M9Manifest) -> None:
    artifact = run_fake_evaluation(manifest)
    assert_artifact_has_no_absolute_paths(artifact)
    artifact["bad"] = "C:\\Users\\someone\\secret"
    with pytest.raises(ValueError, match="absolute host path"):
        assert_artifact_has_no_absolute_paths(artifact)


def test_artifact_identity_is_deterministic_where_intended(manifest: M9Manifest) -> None:
    first = run_fake_evaluation(manifest)
    second = run_fake_evaluation(manifest)
    assert first["artifact_identity"] == second["artifact_identity"]
    assert first["manifest_fingerprint"] == second["manifest_fingerprint"]


def test_runner_never_downloads_models_images_or_tools() -> None:
    source = (REPOSITORY_ROOT / "backend/app/evaluation/m9.py").read_text(encoding="utf-8").casefold()
    assert "ollama pull" not in source
    assert "docker pull" not in source
    assert "pip install" not in source
    assert "npm install" not in source
    assert "snapshot_download" not in source


def test_dry_run_artifact_and_report_are_clearly_non_real(manifest: M9Manifest) -> None:
    artifact = run_fake_evaluation(manifest)
    report = render_report(artifact)
    assert artifact["schema_version"] == "repopilot.m9.v1"
    assert artifact["evaluation_mode"] == "deterministic_fake"
    assert "not SWE-bench" in report
    assert "controlled-defect" in report


def test_report_keeps_post_run_infrastructure_diagnosis_separate(
    manifest: M9Manifest,
) -> None:
    artifact = run_fake_evaluation(manifest)
    diagnosis = {
        "original_five_attempts": {
            "post_hoc_classification": "infrastructure_invalid",
        },
        "confirmation_diagnostic": {
            "grounding_error_type": "PlanValidationError",
            "failure_message": "repair step 1 cites an unknown chunk: N/A",
        },
    }

    report = render_report(artifact, diagnosis=diagnosis)

    assert "historical 0/5 artifact is preserved" in report
    assert "infrastructure_invalid" in report
    assert "PlanValidationError" in report
    assert "clean full M9" in report
