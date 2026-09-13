"""Strict public models for the local human review workspace."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.workflow.application import WorkflowReview


HASH_PATTERN = r"^[0-9a-f]{64}$"
THREAD_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateWorkflowRequest(ApiModel):
    repository_path: str = Field(min_length=1, max_length=4096)
    issue: str = Field(min_length=1, max_length=100_000)
    thread_id: str | None = Field(default=None, pattern=THREAD_PATTERN)

    @field_validator("repository_path", "issue")
    @classmethod
    def values_must_be_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must be nonblank")
        return value


class PlanDecisionRequest(ApiModel):
    decision: Literal["approve", "reject"]
    plan_hash: str = Field(pattern=HASH_PATTERN)
    comment: str | None = Field(default=None, max_length=4000)


class FinalDecisionRequest(ApiModel):
    decision: Literal["approve", "reject"]
    patch_hash: str = Field(pattern=HASH_PATTERN)
    comment: str | None = Field(default=None, max_length=4000)


class RepositoryView(ApiModel):
    name: str
    path: str


class RetrievalView(ApiModel):
    mode: str | None
    degraded: bool
    degradation_reason: str | None
    context_status: str | None
    evidence_count: int = Field(ge=0)


class EvidenceView(ApiModel):
    chunk_id: str
    path: str
    symbol: str
    chunk_type: str
    start_line: int
    end_line: int
    origin: str
    retrieval_rank: int | None
    structural_causes: tuple[str, ...]
    source_text: str | None


class RepairStepView(ApiModel):
    order: int = Field(ge=1)
    description: str
    affected_files: tuple[str, ...]
    evidence_chunk_ids: tuple[str, ...]


class RepairPlanView(ApiModel):
    summary: str
    diagnosis: str
    proposed_files: tuple[str, ...]
    steps: tuple[RepairStepView, ...]
    suggested_tests: tuple[str, ...]


class AttemptView(ApiModel):
    attempt_number: int = Field(ge=1, le=2)
    patch_hash: str
    changed_files: tuple[str, ...]
    patch_status: str
    test_status: str | None
    test_run_id: str | None


class PatchView(ApiModel):
    patch_hash: str = Field(pattern=HASH_PATTERN)
    changed_files: tuple[str, ...]
    canonical_unified_diff: str
    attempt_number: int = Field(ge=1, le=2)


class TestResultView(ApiModel):
    test_run_id: str
    tested_patch_hash: str = Field(pattern=HASH_PATTERN)
    mode: str
    selectors: tuple[str, ...]
    status: str
    exit_code: int | None
    duration_ms: int
    stdout: str
    stderr: str
    output_truncated: bool
    image_reference: str
    image_id: str | None
    failure_classification: str | None
    failure_message: str | None


class RetryInstructionView(ApiModel):
    description: str
    affected_files: tuple[str, ...]


class CriticView(ApiModel):
    summary: str
    failure_diagnosis: str
    retry_recommended: bool
    retry_instructions: tuple[RetryInstructionView, ...]
    evidence_chunk_ids: tuple[str, ...]


class DecisionView(ApiModel):
    decision: Literal["approve", "reject"]
    comment: str | None


class FinalReviewView(ApiModel):
    awaiting_decision: bool
    plan_summary: str
    approved_file_scope: tuple[str, ...]
    final_changed_files: tuple[str, ...]
    final_patch_hash: str
    tested_patch_hash: str
    attempt_number: int
    decision: DecisionView | None


class ExportView(ApiModel):
    artifact_id: str
    filename: str
    patch_hash: str
    changed_files: tuple[str, ...]
    test_run_id: str


class SafeErrorView(ApiModel):
    code: str
    message: str
    stage: str
    classification: str | None = None


class WorkflowView(ApiModel):
    thread_id: str
    status: str
    issue: str
    repository: RepositoryView
    retrieval: RetrievalView
    evidence: tuple[EvidenceView, ...]
    plan: RepairPlanView | None
    plan_hash: str | None
    approved_file_scope: tuple[str, ...] | None
    reviewer_comment: str | None
    attempts: tuple[AttemptView, ...]
    patch: PatchView | None
    test: TestResultView | None
    critic: CriticView | None
    final_review: FinalReviewView | None
    export: ExportView | None
    error: SafeErrorView | None

    @classmethod
    def from_review(cls, review: WorkflowReview) -> WorkflowView:
        result = review.result
        plan = None
        if result.plan is not None:
            plan = RepairPlanView(
                summary=result.plan.summary,
                diagnosis=result.plan.diagnosis,
                proposed_files=result.plan.proposed_files,
                steps=tuple(
                    RepairStepView(
                        order=index,
                        description=step.description,
                        affected_files=step.affected_files,
                        evidence_chunk_ids=step.evidence_chunk_ids,
                    )
                    for index, step in enumerate(result.plan.steps, start=1)
                ),
                suggested_tests=result.plan.suggested_tests,
            )
        evidence = tuple(
            EvidenceView(
                chunk_id=item.chunk_id,
                path=item.path,
                symbol=item.qualified_symbol,
                chunk_type=item.chunk_type,
                start_line=item.start_line,
                end_line=item.end_line,
                origin=item.origin,
                retrieval_rank=item.source_retrieval_rank,
                structural_causes=item.structural_causes,
                source_text=item.source_text,
            )
            for item in result.evidence
        )
        patch = (
            PatchView(
                patch_hash=result.patch.patch_hash,
                changed_files=result.patch.changed_files,
                canonical_unified_diff=result.patch.unified_diff,
                attempt_number=result.attempt_number,
            )
            if result.patch is not None
            else None
        )
        test = (
            TestResultView(
                test_run_id=result.test.test_run_id,
                tested_patch_hash=result.test.patch_hash,
                mode=result.test.mode.value,
                selectors=result.test.validated_selectors,
                status=result.test.status.value,
                exit_code=result.test.exit_code,
                duration_ms=result.test.duration_ms,
                stdout=result.test.stdout,
                stderr=result.test.stderr,
                output_truncated=result.test.output_truncated,
                image_reference=result.test.image_reference,
                image_id=result.test.image_id,
                failure_classification=result.test.failure_classification,
                failure_message=result.test.failure_message,
            )
            if result.test is not None
            else None
        )
        critic = (
            CriticView(
                summary=result.critic_assessment.summary,
                failure_diagnosis=result.critic_assessment.failure_diagnosis,
                retry_recommended=result.critic_assessment.retry_recommended,
                retry_instructions=tuple(
                    RetryInstructionView(
                        description=item.description,
                        affected_files=item.affected_files,
                    )
                    for item in result.critic_assessment.retry_instructions
                ),
                evidence_chunk_ids=result.critic_assessment.evidence_chunk_ids,
            )
            if result.critic_assessment is not None
            else None
        )
        final_decision = (
            DecisionView(
                decision=result.final_approval_decision.decision,
                comment=result.final_approval_decision.comment,
            )
            if result.final_approval_decision is not None
            else None
        )
        final_review = None
        if (
            plan is not None
            and patch is not None
            and test is not None
            and test.status == "passed"
            and result.final_candidate_patch_hash == patch.patch_hash
        ):
            final_review = FinalReviewView(
                awaiting_decision=result.status.value == "awaiting_final_approval",
                plan_summary=plan.summary,
                approved_file_scope=result.approved_file_scope or (),
                final_changed_files=patch.changed_files,
                final_patch_hash=patch.patch_hash,
                tested_patch_hash=test.tested_patch_hash,
                attempt_number=result.attempt_number,
                decision=final_decision,
            )
        exported = (
            ExportView(
                artifact_id=result.export.artifact_id,
                filename=result.export.filename,
                patch_hash=result.export.patch_hash,
                changed_files=result.export.changed_files,
                test_run_id=result.export.test_run_id,
            )
            if result.export is not None
            else None
        )
        return cls(
            thread_id=result.thread_id,
            status=result.status.value,
            issue=review.metadata.issue,
            repository=RepositoryView(
                name=review.metadata.repository_name,
                path=review.metadata.repository_path,
            ),
            retrieval=RetrievalView(
                mode=result.retrieval_mode,
                degraded=result.retrieval_degraded,
                degradation_reason=result.degradation_reason,
                context_status=result.context_status,
                evidence_count=len(evidence),
            ),
            evidence=evidence,
            plan=plan,
            plan_hash=result.plan_hash,
            approved_file_scope=result.approved_file_scope,
            reviewer_comment=result.reviewer_comment,
            attempts=tuple(
                AttemptView(
                    attempt_number=item.attempt_number,
                    patch_hash=item.patch_hash,
                    changed_files=item.changed_files,
                    patch_status=item.patch_status,
                    test_status=item.test_status,
                    test_run_id=item.test_run_id,
                )
                for item in result.attempts
            ),
            patch=patch,
            test=test,
            critic=critic,
            final_review=final_review,
            export=exported,
            error=_safe_error(result),
        )


class ErrorBody(ApiModel):
    code: str
    message: str
    stage: str | None = None


def _safe_error(result) -> SafeErrorView | None:
    if result.error is None:
        return None
    status = result.status.value
    if status == "planner_failed":
        stage = "plan"
    elif status == "patch_failed":
        stage = "patch"
    elif status in {"tests_failed", "test_infrastructure_failed"}:
        stage = "tests"
    elif status in {"critic_failed", "repair_failed"}:
        stage = "critic"
    elif status == "export_failed":
        stage = "export"
    else:
        stage = "workflow"
    return SafeErrorView(
        code=status,
        message=result.error.message,
        stage=stage,
        classification=result.error.error_type,
    )


__all__ = [
    "CreateWorkflowRequest",
    "ErrorBody",
    "FinalDecisionRequest",
    "PlanDecisionRequest",
    "WorkflowView",
]
