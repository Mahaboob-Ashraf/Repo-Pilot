"""Serializable state and service schemas for the first human checkpoint."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.patching import PatchArtifact
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


class PlanReviewResult(WorkflowModel):
    """Stable application result that hides raw LangGraph mechanics."""

    thread_id: str = Field(min_length=1)
    status: WorkflowStatus
    plan: RepairPlan | None = None
    plan_hash: str | None = None
    approval_payload: ApprovalPayload | None = None
    approval_decision: ApprovalDecision | None = None
    approved_file_scope: tuple[str, ...] | None = None
    reviewer_comment: str | None = None
    patch: PatchArtifact | None = None
    test: TestRunResult | None = None
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
