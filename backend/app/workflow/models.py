"""Serializable state and service schemas for the first human checkpoint."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.patching import PatchArtifact
from app.critic import CriticAssessment
from app.exporting import (
    FinalReviewDecision,
    FinalReviewPayload,
    PatchExportArtifact,
)
from app.planning import PlanningEvidence, RepairPlan
from app.sandbox import TestRunResult


class WorkflowModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class WorkflowStatus(StrEnum):
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVAL_RECORDED = "approval_recorded"
    APPROVED_FOR_PATCH = "approved_for_patch"
    PATCH_READY = "patch_ready"
    PATCH_FAILED = "patch_failed"
    TESTS_PASSED = "tests_passed"
    TESTS_FAILED = "tests_failed"
    TEST_INFRASTRUCTURE_FAILED = "test_infrastructure_failed"
    CRITIC_COMPLETE = "critic_complete"
    CRITIC_FAILED = "critic_failed"
    REPAIR_FAILED = "repair_failed"
    AWAITING_FINAL_APPROVAL = "awaiting_final_approval"
    FINAL_APPROVAL_RECORDED = "final_approval_recorded"
    FINAL_APPROVED = "final_approved"
    FINAL_REJECTED = "final_rejected"
    EXPORT_FAILED = "export_failed"
    COMPLETED = "completed"
    REJECTED = "rejected"
    PLANNER_FAILED = "planner_failed"
    VALIDATION_FAILED = "validation_failed"


class ApprovalDecision(WorkflowModel):
    """Explicit human decision bound to the exact reviewed plan hash."""

    decision: Literal["approve", "reject"]
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    comment: str | None = None

    @field_validator("comment")
    @classmethod
    def blank_comment_becomes_none(cls, value: str | None) -> str | None:
        return value or None


class ApprovalPayload(WorkflowModel):
    """JSON-serializable material shown at the first human checkpoint."""

    question: str = Field(min_length=1)
    plan: RepairPlan
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposed_file_scope: tuple[str, ...]
    evidence: tuple[PlanningEvidence, ...]


class WorkflowErrorRecord(WorkflowModel):
    error_type: str = Field(min_length=1)
    message: str = Field(min_length=1)
    provider_error_type: str | None = None
    provider_error_classification: str | None = None
    provider_error_message: str | None = None
    model: str | None = None


class AttemptSummary(WorkflowModel):
    attempt_number: int = Field(ge=1, le=2)
    workspace_id: str
    patch_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    changed_files: tuple[str, ...]
    patch_status: str
    test_status: str | None = None
    test_run_id: str | None = None


class PlanReviewResult(WorkflowModel):
    """Stable application result that hides raw LangGraph mechanics."""

    thread_id: str = Field(min_length=1)
    status: WorkflowStatus
    issue_text: str | None = None
    evidence: tuple[PlanningEvidence, ...] = ()
    context_status: str | None = None
    retrieval_mode: str | None = None
    retrieval_degraded: bool = False
    degradation_reason: str | None = None
    plan: RepairPlan | None = None
    plan_hash: str | None = None
    approval_payload: ApprovalPayload | None = None
    approval_decision: ApprovalDecision | None = None
    approved_file_scope: tuple[str, ...] | None = None
    reviewer_comment: str | None = None
    patch: PatchArtifact | None = None
    test: TestRunResult | None = None
    attempt_number: int = 1
    attempts: tuple[AttemptSummary, ...] = ()
    critic_assessment: CriticAssessment | None = None
    final_approval_payload: FinalReviewPayload | None = None
    final_approval_decision: FinalReviewDecision | None = None
    final_candidate_patch_hash: str | None = None
    export: PatchExportArtifact | None = None
    error: WorkflowErrorRecord | None = None


class PlanReviewState(TypedDict, total=False):
    """Checkpoint-friendly graph state containing only serializable values."""

    thread_id: str
    issue_text: str
    rendered_context: str
    evidence: list[dict[str, Any]]
    context_status: str
    retrieval_mode: str
    retrieval_degraded: bool
    degradation_reason: str | None
    plan: dict[str, Any] | None
    plan_hash: str | None
    status: str
    approval_decision: dict[str, Any] | None
    approved_file_scope: list[str] | None
    reviewer_comment: str | None
    planner_error: dict[str, str | None] | None
    workspace_id: str | None
    source_plan_hash: str | None
    changed_files: list[str] | None
    unified_diff: str | None
    patch_hash: str | None
    patch_error: dict[str, str | None] | None
    test_status: str | None
    tested_patch_hash: str | None
    test_mode: str | None
    test_selectors: list[str] | None
    test_result: dict[str, Any] | None
    test_error: dict[str, str | None] | None
    attempt_number: int
    attempts: list[dict[str, Any]]
    retry_consumed: bool
    critic_assessment_id: str | None
    critic_assessment: dict[str, Any] | None
    critic_error: dict[str, str | None] | None
    final_candidate_patch_hash: str | None
    final_candidate_test_run_id: str | None
    final_approval_decision: dict[str, Any] | None
    final_reviewer_comment: str | None
    final_approved_patch_hash: str | None
    export_status: str | None
    export_artifact: dict[str, Any] | None
    export_error: dict[str, str | None] | None


class ApprovalDecisionError(ValueError):
    """Raised when approval input is invalid, stale, or targets no pause."""


def build_approval_payload(state: PlanReviewState) -> ApprovalPayload:
    plan_data = state.get("plan")
    plan_hash = state.get("plan_hash")
    if not isinstance(plan_data, dict) or not isinstance(plan_hash, str):
        raise ApprovalDecisionError("workflow has no validated plan to approve")
    plan = RepairPlan.model_validate(plan_data)
    cited_ids = {
        chunk_id for step in plan.steps for chunk_id in step.evidence_chunk_ids
    }
    evidence = tuple(
        PlanningEvidence.model_validate(item)
        for item in state.get("evidence", [])
        if item.get("chunk_id") in cited_ids
    )
    return ApprovalPayload(
        question=(
            "Approve this exact evidence-grounded repair plan and proposed file "
            "scope for the later M4 patch stage, or reject it?"
        ),
        plan=plan,
        plan_hash=plan_hash,
        proposed_file_scope=plan.proposed_files,
        evidence=evidence,
    )


def build_final_review_payload(state: PlanReviewState) -> FinalReviewPayload:
    plan_data = state.get("plan")
    plan_hash = state.get("plan_hash")
    patch_hash = state.get("final_candidate_patch_hash")
    approved_files = state.get("approved_file_scope")
    changed_files = state.get("changed_files")
    unified_diff = state.get("unified_diff")
    test_data = state.get("test_result")
    attempt_number = state.get("attempt_number")
    if not all(
        (
            isinstance(plan_data, dict),
            isinstance(plan_hash, str),
            isinstance(patch_hash, str),
            isinstance(approved_files, list),
            isinstance(changed_files, list),
            isinstance(unified_diff, str),
            isinstance(test_data, dict),
            isinstance(attempt_number, int),
        )
    ):
        raise ApprovalDecisionError("workflow has no complete passing patch to review")
    plan = RepairPlan.model_validate(plan_data)
    test_result = TestRunResult.model_validate(test_data)
    if (
        test_result.patch_hash != patch_hash
        or test_result.status.value != "passed"
        or state.get("final_candidate_test_run_id") != test_result.test_run_id
    ):
        raise ApprovalDecisionError("final candidate lacks exact successful test evidence")
    cited_ids = {
        chunk_id for step in plan.steps for chunk_id in step.evidence_chunk_ids
    }
    critic = (
        CriticAssessment.model_validate(state["critic_assessment"])
        if isinstance(state.get("critic_assessment"), dict)
        else None
    )
    return FinalReviewPayload(
        question=(
            "Approve export of this exact tested patch hash, or reject it? "
            "Approval exports a patch file only; it does not apply or commit it."
        ),
        issue=state["issue_text"],
        plan_summary=plan.summary,
        approved_plan_hash=plan_hash,
        final_attempt_number=attempt_number,
        final_patch_hash=patch_hash,
        approved_files=tuple(approved_files),
        changed_files=tuple(changed_files),
        canonical_unified_diff=unified_diff,
        test_result=test_result,
        evidence=tuple(
            PlanningEvidence.model_validate(item)
            for item in state.get("evidence", [])
            if item.get("chunk_id") in cited_ids
        ),
        critic_assessment=critic,
    )
