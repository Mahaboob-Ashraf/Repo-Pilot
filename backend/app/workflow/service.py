"""Application boundary around LangGraph start/resume and SQLite persistence."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from pydantic import ValidationError

from app.context_packing import ContextPack
from app.critic import CriticAssessment, CriticService
from app.exporting import (
    FinalReviewDecision,
    FinalReviewPayload,
    PatchExportArtifact,
    PatchExporter,
)
from app.patching import ApprovedPatchService, PatchArtifact
from app.planning import PlanningContextSnapshot, RepairPlan, StructuredPlanner
from app.sandbox import ApprovedPatchTestService, TestRunRequest, TestRunResult
from app.workflow.graph import build_plan_review_graph
from app.workflow.models import (
    ApprovalDecision,
    ApprovalDecisionError,
    ApprovalPayload,
    AttemptSummary,
    PlanReviewResult,
    PlanReviewState,
    WorkflowErrorRecord,
    WorkflowStatus,
    build_approval_payload,
)


class CheckpointConfigurationError(ValueError):
    """Raised for an unsafe or unusable local checkpoint path."""


class PlanReviewService:
    """Hide graph invocation, interrupt extraction, and thread semantics."""

    def __init__(
        self,
        planner: StructuredPlanner,
        checkpointer: BaseCheckpointSaver[Any],
        patch_service: ApprovedPatchService | None = None,
        test_service: ApprovedPatchTestService | None = None,
        test_request: TestRunRequest | None = None,
        critic_service: CriticService | None = None,
        patch_exporter: PatchExporter | None = None,
    ) -> None:
        self._graph = build_plan_review_graph(
            planner,
            checkpointer,
            patch_service,
            test_service,
            test_request,
            critic_service,
            patch_exporter,
        )

    async def start_plan_review(
        self,
        *,
        thread_id: str,
        context_pack: ContextPack,
    ) -> PlanReviewResult:
        thread_id = _validate_thread_id(thread_id)
        config = _config(thread_id)
        existing = await self._graph.aget_state(config)
        if existing.values:
            return _validation_failure(
                thread_id,
                existing.values,
                ApprovalDecisionError(
                    "thread_id already has checkpointed workflow state"
                ),
            )

        context = PlanningContextSnapshot.from_context_pack(context_pack)
        initial_state: PlanReviewState = {
            "thread_id": thread_id,
            **context.model_dump(mode="json"),
            "plan": None,
            "plan_hash": None,
            "status": WorkflowStatus.PLANNING.value,
            "approval_decision": None,
            "approved_file_scope": None,
            "reviewer_comment": None,
            "planner_error": None,
            "workspace_id": None,
            "source_plan_hash": None,
            "changed_files": None,
            "unified_diff": None,
            "patch_hash": None,
            "patch_error": None,
            "test_status": None,
            "tested_patch_hash": None,
            "test_mode": None,
            "test_selectors": None,
            "test_result": None,
            "test_error": None,
            "attempt_number": 1,
            "attempts": [],
            "retry_consumed": False,
            "critic_assessment_id": None,
            "critic_assessment": None,
            "critic_error": None,
            "final_candidate_patch_hash": None,
            "final_candidate_test_run_id": None,
            "final_approval_decision": None,
            "final_reviewer_comment": None,
            "final_approved_patch_hash": None,
            "export_status": None,
            "export_artifact": None,
            "export_error": None,
        }
        output = await self._graph.ainvoke(initial_state, config=config)
        return _result_from_output(thread_id, output)

    async def resume_final_review(
        self,
        *,
        thread_id: str,
        decision: FinalReviewDecision | Mapping[str, object],
    ) -> PlanReviewResult:
        """Resume only the second, exact-patch-hash-bound human checkpoint."""

        thread_id = _validate_thread_id(thread_id)
        config = _config(thread_id)
        snapshot = await self._graph.aget_state(config)
        state = snapshot.values
        if not state:
            return _validation_failure(
                thread_id, {}, ApprovalDecisionError(
                    "thread_id has no checkpointed final review to resume"
                )
            )
        if (
            state.get("status") != WorkflowStatus.AWAITING_FINAL_APPROVAL.value
            or "final_review" not in snapshot.next
        ):
            return _validation_failure(
                thread_id, state, ApprovalDecisionError(
                    "thread_id is not waiting at the final approval checkpoint"
                )
            )
        try:
            parsed = FinalReviewDecision.model_validate(decision)
        except ValidationError:
            return _validation_failure(
                thread_id, state, ApprovalDecisionError(
                    "invalid final review decision object"
                )
            )
        if parsed.patch_hash != state.get("final_candidate_patch_hash"):
            return _validation_failure(
                thread_id, state, ApprovalDecisionError(
                    "final approval patch hash does not match the tested candidate"
                )
            )
        output = await self._graph.ainvoke(
            Command(resume=parsed.model_dump(mode="json")), config=config
        )
        return _result_from_output(thread_id, output)

    async def resume_plan_review(
        self,
        *,
        thread_id: str,
        decision: ApprovalDecision | Mapping[str, object],
    ) -> PlanReviewResult:
        thread_id = _validate_thread_id(thread_id)
        config = _config(thread_id)
        snapshot = await self._graph.aget_state(config)
        state = snapshot.values
        if not state:
            return _validation_failure(
                thread_id,
                {},
                ApprovalDecisionError(
                    "thread_id has no checkpointed approval to resume"
                ),
            )
        if (
            state.get("status") != WorkflowStatus.AWAITING_APPROVAL.value
            or "approval" not in snapshot.next
        ):
            return _validation_failure(
                thread_id,
                state,
                ApprovalDecisionError(
                    "thread_id is not waiting at the plan approval checkpoint"
                ),
            )
        try:
            parsed_decision = ApprovalDecision.model_validate(decision)
        except ValidationError as exc:
            return _validation_failure(
                thread_id,
                state,
                ApprovalDecisionError("invalid approval decision object"),
            )
        if parsed_decision.plan_hash != state.get("plan_hash"):
            return _validation_failure(
                thread_id,
                state,
                ApprovalDecisionError(
                    "approval plan hash does not match the checkpointed plan"
                ),
            )

        output = await self._graph.ainvoke(
            Command(resume=parsed_decision.model_dump(mode="json")),
            config=config,
        )
        return _result_from_output(thread_id, output)


@asynccontextmanager
async def open_sqlite_plan_review_service(
    *,
    planner: StructuredPlanner,
    checkpoint_path: str | Path,
    patch_service: ApprovedPatchService | None = None,
    test_service: ApprovedPatchTestService | None = None,
    test_request: TestRunRequest | None = None,
    critic_service: CriticService | None = None,
    patch_exporter: PatchExporter | None = None,
) -> AsyncIterator[PlanReviewService]:
    """Open a durable local service; checkpoint DBs must live outside source."""

    path = Path(checkpoint_path).expanduser()
    if not path.is_absolute():
        raise CheckpointConfigurationError(
            "checkpoint_path must be an absolute path outside the repository"
        )
    resolved = path.resolve()
    repository_root = Path(__file__).resolve().parents[3]
    if resolved.is_relative_to(repository_root):
        raise CheckpointConfigurationError(
            "checkpoint database must not be stored inside the source repository"
        )
    resolved.parent.mkdir(parents=True, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(str(resolved)) as checkpointer:
        await checkpointer.setup()
        yield PlanReviewService(
            planner,
            checkpointer,
            patch_service,
            test_service,
            test_request,
            critic_service,
            patch_exporter,
        )


def _validate_thread_id(thread_id: str) -> str:
    if (
        not isinstance(thread_id, str)
        or not thread_id
        or thread_id != thread_id.strip()
        or len(thread_id) > 256
    ):
        raise ApprovalDecisionError(
            "thread_id must be a nonblank caller-supplied stable identifier"
        )
    return thread_id


def _config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def _result_from_output(
    thread_id: str,
    output: Mapping[str, Any],
) -> PlanReviewResult:
    state = dict(output)
    status = WorkflowStatus(state["status"])
    plan = (
        RepairPlan.model_validate(state["plan"])
        if isinstance(state.get("plan"), dict)
        else None
    )
    interrupt_payload = None
    final_interrupt_payload = None
    interrupts = state.get("__interrupt__", ())
    if interrupts:
        if status is WorkflowStatus.AWAITING_FINAL_APPROVAL:
            final_interrupt_payload = FinalReviewPayload.model_validate(
                interrupts[0].value
            )
        else:
            interrupt_payload = ApprovalPayload.model_validate(interrupts[0].value)
    decision = (
        ApprovalDecision.model_validate(state["approval_decision"])
        if isinstance(state.get("approval_decision"), dict)
        else None
    )
    raw_error = (
        state.get("export_error")
        or state.get("critic_error")
        or state.get("test_error")
        or state.get("patch_error")
        or state.get("planner_error")
    )
    error = (
        WorkflowErrorRecord.model_validate(raw_error)
        if isinstance(raw_error, dict)
        else None
    )
    approved = state.get("approved_file_scope")
    patch = _patch_artifact_from_state(state)
    test = (
        TestRunResult.model_validate(state["test_result"])
        if isinstance(state.get("test_result"), dict)
        else None
    )
    critic = (
        CriticAssessment.model_validate(state["critic_assessment"])
        if isinstance(state.get("critic_assessment"), dict)
        else None
    )
    final_decision = (
        FinalReviewDecision.model_validate(state["final_approval_decision"])
        if isinstance(state.get("final_approval_decision"), dict)
        else None
    )
    export = (
        PatchExportArtifact.model_validate(state["export_artifact"])
        if isinstance(state.get("export_artifact"), dict)
        else None
    )
    return PlanReviewResult(
        thread_id=thread_id,
        status=status,
        plan=plan,
        plan_hash=state.get("plan_hash"),
        approval_payload=interrupt_payload,
        approval_decision=decision,
        approved_file_scope=tuple(approved) if isinstance(approved, list) else None,
        reviewer_comment=state.get("reviewer_comment"),
        patch=patch,
        test=test,
        attempt_number=state.get("attempt_number", 1),
        attempts=tuple(
            AttemptSummary.model_validate(item) for item in state.get("attempts", [])
        ),
        critic_assessment=critic,
        final_approval_payload=final_interrupt_payload,
        final_approval_decision=final_decision,
        final_candidate_patch_hash=state.get("final_candidate_patch_hash"),
        export=export,
        error=error,
    )


def _validation_failure(
    thread_id: str,
    state: Mapping[str, Any],
    error: ApprovalDecisionError,
) -> PlanReviewResult:
    plan = (
        RepairPlan.model_validate(state["plan"])
        if isinstance(state.get("plan"), dict)
        else None
    )
    payload = None
    final_payload = None
    if state.get("status") == WorkflowStatus.AWAITING_APPROVAL.value:
        payload = build_approval_payload(dict(state))
    elif state.get("status") == WorkflowStatus.AWAITING_FINAL_APPROVAL.value:
        from app.workflow.models import build_final_review_payload

        final_payload = build_final_review_payload(dict(state))
    return PlanReviewResult(
        thread_id=thread_id,
        status=WorkflowStatus.VALIDATION_FAILED,
        plan=plan,
        plan_hash=state.get("plan_hash"),
        approval_payload=payload,
        patch=_patch_artifact_from_state(state),
        test=(
            TestRunResult.model_validate(state["test_result"])
            if isinstance(state.get("test_result"), dict)
            else None
        ),
        attempt_number=state.get("attempt_number", 1),
        attempts=tuple(
            AttemptSummary.model_validate(item) for item in state.get("attempts", [])
        ),
        critic_assessment=(
            CriticAssessment.model_validate(state["critic_assessment"])
            if isinstance(state.get("critic_assessment"), dict)
            else None
        ),
        final_approval_payload=final_payload,
        final_approval_decision=(
            FinalReviewDecision.model_validate(state["final_approval_decision"])
            if isinstance(state.get("final_approval_decision"), dict)
            else None
        ),
        final_candidate_patch_hash=state.get("final_candidate_patch_hash"),
        export=(
            PatchExportArtifact.model_validate(state["export_artifact"])
            if isinstance(state.get("export_artifact"), dict)
            else None
        ),
        error=WorkflowErrorRecord(
            error_type=type(error).__name__,
            message=str(error),
        ),
    )


def _patch_artifact_from_state(state: Mapping[str, Any]) -> PatchArtifact | None:
    fields = (
        state.get("workspace_id"),
        state.get("source_plan_hash"),
        state.get("changed_files"),
        state.get("unified_diff"),
        state.get("patch_hash"),
    )
    if not all(value is not None for value in fields):
        return None
    return PatchArtifact(
        workspace_id=fields[0],
        source_plan_hash=fields[1],
        changed_files=tuple(fields[2]),
        unified_diff=fields[3],
        patch_hash=fields[4],
    )
