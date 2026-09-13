"""Frozen M9 manifest, contamination boundary, and scoring models."""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from math import ceil
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.exporting import FinalReviewDecision
from app.sandbox import TestStatus
from app.workflow import ApprovalDecision, PlanReviewResult, WorkflowStatus


SHA_PATTERN = r"^[0-9a-f]{40}$"
DIGEST_PATTERN = r"^[0-9a-f]{64}$"
CASE_TYPE = "external-repository controlled-defect case"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _relative_path(value: str) -> str:
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        not value
        or "\\" in value
        or posix.is_absolute()
        or windows.is_absolute()
        or any(part in {"", ".", ".."} for part in posix.parts)
        or posix.as_posix() != value
    ):
        raise ValueError("path must be a normalized relative POSIX path")
    return value


class ExactReplacement(FrozenModel):
    path: str
    expected_old_text: str = Field(min_length=1)
    replacement_text: str = Field(min_length=1)

    _validate_path = field_validator("path")(_relative_path)

    @model_validator(mode="after")
    def changes_text(self) -> ExactReplacement:
        if self.expected_old_text == self.replacement_text:
            raise ValueError("replacement must change text")
        return self


class EvaluationOracle(FrozenModel):
    """Scoring-only labels that must never cross the execution boundary."""

    gold_changed_files: tuple[str, ...] = Field(min_length=1)
    gold_symbols: tuple[str, ...] = Field(min_length=1)
    repair: ExactReplacement

    @field_validator("gold_changed_files")
    @classmethod
    def validate_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("gold changed files must be unique")
        return tuple(_relative_path(item) for item in values)


class ExternalRepository(FrozenModel):
    repository_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1)
    upstream_url: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+\.git$")
    commit_sha: str = Field(pattern=SHA_PATTERN)
    license_identifier: Literal["MIT", "BSD-3-Clause", "Apache-2.0"]
    fixture_paths: tuple[str, ...] = Field(min_length=1)
    source_fingerprint: str = Field(pattern=DIGEST_PATTERN)
    acquisition_provenance: str = Field(min_length=1)

    @field_validator("fixture_paths")
    @classmethod
    def validate_fixture_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("fixture paths must be unique")
        return tuple(_relative_path(item) for item in values)


class M9Case(FrozenModel):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,95}$")
    repository_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    case_type: Literal[CASE_TYPE]
    issue_description: str = Field(min_length=1, max_length=10_000)
    expected_failing_tests: tuple[str, ...] = Field(min_length=1)
    required_test_selectors: tuple[str, ...] = Field(min_length=1)
    evaluation_mode: Literal["targeted"]
    acquisition_provenance: str = Field(min_length=1)
    fixture_fingerprint: str = Field(pattern=DIGEST_PATTERN)
    controlled_mutation: ExactReplacement
    evaluation_oracle: EvaluationOracle

    @model_validator(mode="after")
    def validate_case(self) -> M9Case:
        if len(self.required_test_selectors) != len(set(self.required_test_selectors)):
            raise ValueError("required test selectors must be unique")
        if self.controlled_mutation.path not in self.evaluation_oracle.gold_changed_files:
            raise ValueError("controlled mutation must target a gold changed file")
        if self.evaluation_oracle.repair.path != self.controlled_mutation.path:
            raise ValueError("repair oracle and mutation must target the same path")
        if self.evaluation_oracle.repair.expected_old_text != self.controlled_mutation.replacement_text:
            raise ValueError("repair oracle must start from the controlled mutation")
        if self.evaluation_oracle.repair.replacement_text != self.controlled_mutation.expected_old_text:
            raise ValueError("repair oracle must reverse the controlled mutation")
        issue_folded = self.issue_description.casefold()
        if self.evaluation_oracle.repair.expected_old_text.casefold() in issue_folded:
            raise ValueError("gold repair text must not be included in the issue")
        return self


class M9Manifest(FrozenModel):
    schema_version: Literal[
        "repopilot.m9.manifest.v1", "repopilot.m9.manifest.v2"
    ]
    benchmark_id: str = Field(min_length=1)
    repositories: tuple[ExternalRepository, ...] = Field(min_length=1)
    cases: tuple[M9Case, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest(self) -> M9Manifest:
        repository_ids = [item.repository_id for item in self.repositories]
        case_ids = [item.case_id for item in self.cases]
        if len(repository_ids) != len(set(repository_ids)):
            raise ValueError("repository IDs must be unique")
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case IDs must be unique")
        known = set(repository_ids)
        missing = sorted({item.repository_id for item in self.cases} - known)
        if missing:
            raise ValueError(f"cases reference unknown repositories: {missing}")
        return self

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def repository(self, repository_id: str) -> ExternalRepository:
        return next(item for item in self.repositories if item.repository_id == repository_id)


def load_m9_manifest(path: Path) -> M9Manifest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return M9Manifest.model_validate(payload)


class ProductionCaseInput(FrozenModel):
    """The only case data permitted to enter retrieval and workflow services."""

    case_id: str
    repository_id: str
    repository_root: Path
    issue: str
    test_selectors: tuple[str, ...]

    @classmethod
    def from_case(cls, case: M9Case, *, fixture_root: Path) -> ProductionCaseInput:
        return cls(
            case_id=case.case_id,
            repository_id=case.repository_id,
            repository_root=(fixture_root / case.case_id).resolve(strict=True),
            issue=case.issue_description,
            test_selectors=case.required_test_selectors,
        )


class AttemptRecord(FrozenModel):
    attempt_number: int = Field(ge=1, le=2)
    patch_hash: str | None = None
    changed_files: tuple[str, ...] = ()
    test_status: str | None = None
    test_run_id: str | None = None


class StageLatencies(FrozenModel):
    repository_indexing_ms: float | None = Field(default=None, ge=0)
    embedding_index_setup_ms: float | None = Field(default=None, ge=0)
    retrieval_ms: float | None = Field(default=None, ge=0)
    planning_generation_ms: float | None = Field(default=None, ge=0)
    patch_generation_ms: float | None = Field(default=None, ge=0)
    docker_testing_ms: float | None = Field(default=None, ge=0)
    critic_generation_ms: float | None = Field(default=None, ge=0)
    retry_patch_generation_ms: float | None = Field(default=None, ge=0)
    total_workflow_ms: float | None = Field(default=None, ge=0)


class ExecutionObservation(FrozenModel):
    case_id: str
    terminal_status: str
    failure_stage: str | None = None
    blocked_reason: str | None = None
    failure_error_type: str | None = None
    failure_message: str | None = None
    provider_error_type: str | None = None
    provider_error_classification: str | None = None
    provider_error_message: str | None = None
    retrieval_mode: str | None = None
    retrieval_degraded: bool = False
    degradation_reason: str | None = None
    context_status: str | None = None
    ranked_files: tuple[str, ...] = ()
    ranked_symbols: tuple[str | None, ...] = ()
    context_files: tuple[str, ...] = ()
    context_symbols: tuple[str | None, ...] = ()
    plan_generated: bool = False
    plan_proposed_files: tuple[str, ...] = ()
    approval_1_completed: bool = False
    approved_file_scope: tuple[str, ...] = ()
    patch_produced: bool = False
    patch_hash: str | None = None
    actual_changed_files: tuple[str, ...] = ()
    tests_passed: bool = False
    final_approval_completed: bool = False
    export_completed: bool = False
    exported_patch_hash: str | None = None
    attempts: tuple[AttemptRecord, ...] = ()
    critic_declined_retry: bool = False
    scope_violation_attempts: int = Field(default=0, ge=0)
    stale_hash_failures: int = Field(default=0, ge=0)
    patch_validation_failures: int = Field(default=0, ge=0)
    canonical_repository_mutated: bool = False
    export_only_after_final_approval: bool = True
    candidate_diff: str | None = None
    latencies: StageLatencies = StageLatencies()


class AttemptClassification(StrEnum):
    SOLVED_ATTEMPT_1 = "solved_on_attempt_1"
    SOLVED_ATTEMPT_2 = "solved_on_attempt_2"
    FAILED_ATTEMPT_2 = "failed_after_attempt_2"
    CRITIC_DECLINED = "critic_declined_retry"
    FAILED_BEFORE_TESTING = "failed_before_testing"
    INFRASTRUCTURE_BLOCKED = "infrastructure_blocked"
    BENCHMARK_FIXTURE_INVALID = "benchmark_fixture_invalid"


def benchmark_plan_decision(result: PlanReviewResult) -> ApprovalDecision | None:
    """Procedural approval #1. This function has no oracle parameter."""

    if (
        result.status is not WorkflowStatus.AWAITING_APPROVAL
        or result.plan is None
        or result.plan_hash is None
        or result.approval_payload is None
        or not result.plan.proposed_files
    ):
        return None
    evidence_paths = {item.path for item in result.evidence}
    if any(_relative_path(path) not in evidence_paths for path in result.plan.proposed_files):
        return None
    if tuple(result.plan.proposed_files) != result.approval_payload.proposed_file_scope:
        return None
    return ApprovalDecision(
        decision="approve",
        plan_hash=result.plan_hash,
        comment="M9 procedural plan approval; no gold labels consulted.",
    )


def benchmark_final_decision(result: PlanReviewResult) -> FinalReviewDecision | None:
    """Procedural approval #2. Tests and normal invariants are the only oracle."""

    if (
        result.status is not WorkflowStatus.AWAITING_FINAL_APPROVAL
        or result.patch is None
        or result.test is None
        or result.test.status is not TestStatus.PASSED
        or result.patch.patch_hash != result.test.patch_hash
        or result.patch.patch_hash != result.final_candidate_patch_hash
        or result.approved_file_scope is None
        or not set(result.patch.changed_files).issubset(result.approved_file_scope)
    ):
        return None
    return FinalReviewDecision(
        decision="approve",
        patch_hash=result.patch.patch_hash,
        comment="M9 procedural final approval; only passing bound evidence consulted.",
    )


def classify_attempt(observation: ExecutionObservation) -> AttemptClassification:
    if observation.terminal_status == "benchmark_fixture_invalid":
        return AttemptClassification.BENCHMARK_FIXTURE_INVALID
    if observation.blocked_reason is not None:
        return AttemptClassification.INFRASTRUCTURE_BLOCKED
    if observation.critic_declined_retry:
        return AttemptClassification.CRITIC_DECLINED
    tested = [item for item in observation.attempts if item.test_status is not None]
    if observation.export_completed and len(tested) == 1 and tested[0].test_status == "passed":
        return AttemptClassification.SOLVED_ATTEMPT_1
    if observation.export_completed and len(tested) == 2 and tested[-1].test_status == "passed":
        return AttemptClassification.SOLVED_ATTEMPT_2
    if len(tested) >= 2:
        return AttemptClassification.FAILED_ATTEMPT_2
    return AttemptClassification.FAILED_BEFORE_TESTING


def repair_succeeded(observation: ExecutionObservation) -> bool:
    return bool(
        observation.patch_produced
        and observation.tests_passed
        and observation.final_approval_completed
        and observation.export_completed
        and observation.patch_hash
        and observation.patch_hash == observation.exported_patch_hash
        and not observation.canonical_repository_mutated
        and observation.scope_violation_attempts == 0
        and observation.export_only_after_final_approval
    )


def _first_rank(values: tuple[str | None, ...], gold: set[str]) -> int | None:
    for index, value in enumerate(values, start=1):
        if value in gold:
            return index
    return None


def score_case(case: M9Case, observation: ExecutionObservation) -> dict[str, Any]:
    gold_files = set(case.evaluation_oracle.gold_changed_files)
    gold_symbols = set(case.evaluation_oracle.gold_symbols)
    file_rank = _first_rank(observation.ranked_files, gold_files)
    symbol_rank = _first_rank(observation.ranked_symbols, gold_symbols)
    actual = set(observation.actual_changed_files)
    exact_patch_match = (
        observation.candidate_diff is not None
        and case.evaluation_oracle.repair.expected_old_text in observation.candidate_diff
        and case.evaluation_oracle.repair.replacement_text in observation.candidate_diff
    )
    return {
        "case_id": case.case_id,
        "repository_id": case.repository_id,
        "case_type": case.case_type,
        "terminal_status": observation.terminal_status,
        "failure_stage": observation.failure_stage,
        "blocked_reason": observation.blocked_reason,
        "failure_error_type": observation.failure_error_type,
        "failure_message": observation.failure_message,
        "provider_error_type": observation.provider_error_type,
        "provider_error_classification": observation.provider_error_classification,
        "provider_error_message": observation.provider_error_message,
        "repair_success": repair_succeeded(observation),
        "attempt_classification": classify_attempt(observation).value,
        "plan_generated": observation.plan_generated,
        "plan_proposed_files": list(observation.plan_proposed_files),
        "approval_1_completed": observation.approval_1_completed,
        "approved_file_scope": list(observation.approved_file_scope),
        "patch_produced": observation.patch_produced,
        "patch_hash": observation.patch_hash,
        "tests_passed": observation.tests_passed,
        "final_approval_completed": observation.final_approval_completed,
        "export_completed": observation.export_completed,
        "attempts": [item.model_dump(mode="json") for item in observation.attempts],
        "critic_declined_retry": observation.critic_declined_retry,
        "retrieval": {
            "measured": bool(observation.ranked_files or observation.context_files),
            "mode": observation.retrieval_mode,
            "degraded": observation.retrieval_degraded,
            "degradation_reason": observation.degradation_reason,
            "context_status": observation.context_status,
            "gold_file_hit_at_1": file_rank == 1,
            "gold_file_hit_at_5": file_rank is not None and file_rank <= 5,
            "file_reciprocal_rank": 0.0 if file_rank is None else 1.0 / file_rank,
            "gold_symbol_coverage": bool(set(observation.context_symbols) & gold_symbols),
            "gold_file_context_coverage": bool(set(observation.context_files) & gold_files),
        },
        "patch_quality": {
            "changed_files": sorted(actual),
            "gold_changed_files": sorted(gold_files),
            "extra_changed_files": sorted(actual - gold_files),
            "missing_gold_files": sorted(gold_files - actual),
            "exact_patch_match": exact_patch_match,
            "behavioral_success": observation.tests_passed,
        },
        "safety": {
            "scope_violation_attempts": observation.scope_violation_attempts,
            "stale_hash_failures": observation.stale_hash_failures,
            "patch_validation_failures": observation.patch_validation_failures,
            "canonical_repository_mutated": observation.canonical_repository_mutated,
            "export_only_after_final_approval": observation.export_only_after_final_approval,
            "critical_failure": bool(
                observation.scope_violation_attempts
                or observation.canonical_repository_mutated
                or not observation.export_only_after_final_approval
            ),
        },
        "latency_ms": observation.latencies.model_dump(mode="json"),
    }


def aggregate_scores(cases: list[dict[str, Any]]) -> dict[str, Any]:
    attempted = [item for item in cases if item["blocked_reason"] is None]
    successful = [item for item in attempted if item["repair_success"]]
    classifications = Counter(item["attempt_classification"] for item in cases)
    stages = Counter(
        item["failure_stage"] for item in cases if item["failure_stage"] is not None
    )
    retrieval_denominator = [item for item in cases if item["retrieval"]["measured"]]
    test_attempts = [
        attempt
        for item in attempted
        for attempt in item["attempts"]
        if attempt.get("test_status") is not None
    ]
    valid_case_count = len(cases) - classifications[
        AttemptClassification.BENCHMARK_FIXTURE_INVALID.value
    ]
    return {
        "case_count": len(cases),
        "valid_case_count": valid_case_count,
        "cases_attempted": len(attempted),
        "cases_completed": len(successful),
        "repair_success_count": len(successful),
        "repair_success_rate": len(successful) / len(attempted) if attempted else None,
        "attempt_1_success_rate": classifications[AttemptClassification.SOLVED_ATTEMPT_1.value] / len(attempted) if attempted else None,
        "retry_used_rate": sum(len(item["attempts"]) == 2 for item in attempted) / len(attempted) if attempted else None,
        "attempt_2_success_rate": classifications[AttemptClassification.SOLVED_ATTEMPT_2.value] / len(attempted) if attempted else None,
        "terminal_repair_failure_rate": sum(not item["repair_success"] for item in attempted) / len(attempted) if attempted else None,
        "infrastructure_blocked_count": classifications[AttemptClassification.INFRASTRUCTURE_BLOCKED.value],
        "benchmark_fixture_invalid_count": classifications[
            AttemptClassification.BENCHMARK_FIXTURE_INVALID.value
        ],
        "attempt_classifications": dict(sorted(classifications.items())),
        "failure_stage_counts": dict(sorted(stages.items())),
        "planner_outcomes": {
            "valid_grounded_plans": sum(item["plan_generated"] for item in attempted),
            "output_parse_failures": sum(
                item["failure_error_type"] == "PlannerOutputError"
                for item in attempted
            ),
            "grounding_failures": sum(
                item["failure_error_type"] == "PlanValidationError"
                for item in attempted
            ),
            "provider_failures": sum(
                item["failure_error_type"] == "PlannerInferenceError"
                or item["provider_error_type"] is not None
                for item in attempted
            ),
        },
        "patch_test": {
            "cases_reaching_patch_generation": sum(
                item["approval_1_completed"]
                or item["latency_ms"].get("patch_generation_ms") is not None
                for item in attempted
            ),
            "cases_producing_valid_patches": sum(
                item["patch_produced"] for item in attempted
            ),
            "docker_test_passes": sum(
                attempt["test_status"] == "passed" for attempt in test_attempts
            ),
            "docker_test_failures": sum(
                attempt["test_status"] == "failed" for attempt in test_attempts
            ),
        },
        "retrieval_mode_counts": dict(
            sorted(
                Counter(
                    item["retrieval"]["mode"]
                    for item in retrieval_denominator
                    if item["retrieval"].get("mode") is not None
                ).items()
            )
        ),
        "retrieval": {
            "gold_file_hit_at_1": _mean(retrieval_denominator, "gold_file_hit_at_1"),
            "gold_file_hit_at_5": _mean(retrieval_denominator, "gold_file_hit_at_5"),
            "file_mrr": _mean(retrieval_denominator, "file_reciprocal_rank"),
            "gold_symbol_context_coverage": _mean(retrieval_denominator, "gold_symbol_coverage"),
            "gold_file_context_coverage": _mean(retrieval_denominator, "gold_file_context_coverage"),
        },
        "patch_quality": {
            "cases_with_changed_files": sum(
                bool(item["patch_quality"]["changed_files"]) for item in attempted
            ),
            "exact_gold_file_scope_count": sum(
                item["patch_quality"]["changed_files"]
                == item["patch_quality"]["gold_changed_files"]
                for item in attempted
                if item["patch_quality"]["changed_files"]
            ),
            "extra_changed_file_count": sum(
                len(item["patch_quality"]["extra_changed_files"]) for item in attempted
            ),
            "missing_gold_file_count": sum(
                len(item["patch_quality"]["missing_gold_files"]) for item in attempted
            ),
            "exact_patch_match_count": sum(
                item["patch_quality"]["exact_patch_match"] for item in attempted
            ),
            "behavioral_success_count": sum(
                item["patch_quality"]["behavioral_success"] for item in attempted
            ),
        },
        "safety": {
            "scope_violation_attempts": sum(
                item["safety"]["scope_violation_attempts"] for item in cases
            ),
            "stale_hash_failures": sum(
                item["safety"]["stale_hash_failures"] for item in cases
            ),
            "patch_validation_failures": sum(
                item["safety"]["patch_validation_failures"] for item in cases
            ),
            "canonical_repository_mutation_count": sum(
                item["safety"]["canonical_repository_mutated"] for item in cases
            ),
            "export_order_failure_count": sum(
                not item["safety"]["export_only_after_final_approval"]
                for item in cases
            ),
            "retry_limit_violation_count": sum(
                len(item["attempts"]) > 2 for item in cases
            ),
        },
        "critical_safety_failure": any(item["safety"]["critical_failure"] for item in cases),
        "latency_ms": aggregate_latencies(cases),
    }


def _mean(cases: list[dict[str, Any]], metric: str) -> float | None:
    values = [float(item["retrieval"][metric]) for item in cases]
    return sum(values) / len(values) if values else None


def aggregate_latencies(cases: list[dict[str, Any]]) -> dict[str, Any]:
    names = StageLatencies.model_fields
    result: dict[str, Any] = {}
    for name in names:
        values = sorted(
            float(item["latency_ms"][name])
            for item in cases
            if item["latency_ms"].get(name) is not None
        )
        result[name] = {
            "count": len(values),
            "median": _nearest(values, 0.5),
            "p95": _nearest(values, 0.95) if len(values) >= 5 else None,
        }
    return result


def _nearest(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    index = max(0, min(len(values) - 1, ceil(len(values) * quantile) - 1))
    return values[index]


def assert_artifact_has_no_absolute_paths(artifact: dict[str, Any]) -> None:
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                visit(key)
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)
        elif isinstance(value, str) and not value.startswith(("http://", "https://")):
            if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
                raise ValueError("M9 artifact contains an absolute host path")

    visit(artifact)


__all__ = [
    "AttemptClassification", "AttemptRecord", "CASE_TYPE", "ExecutionObservation",
    "M9Case", "M9Manifest", "ProductionCaseInput", "StageLatencies",
    "aggregate_scores", "assert_artifact_has_no_absolute_paths",
    "benchmark_final_decision", "benchmark_plan_decision", "classify_attempt",
    "load_m9_manifest", "repair_succeeded", "score_case",
]
