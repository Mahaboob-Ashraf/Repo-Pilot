"""One bounded LangGraph workflow from planning through approved patch export."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from app.critic import CriticError, CriticInferenceError, CriticService
from app.exporting import FinalReviewDecision, PatchExportError, PatchExporter
from app.patching import ApprovedPatchService, PatchArtifact, PatchError, PatchInferenceError
from app.planning import (
    PlanningContextSnapshot,
    PlanValidationError,
    PlannerError,
    PlannerInferenceError,
    RepairPlan,
    StructuredPlanner,
)
from app.sandbox import ApprovedPatchTestService, TestRunRequest, TestRunResult, TestStatus
from app.workflow.models import (
    ApprovalDecision,
    ApprovalDecisionError,
    PlanReviewState,
    WorkflowStatus,
    build_approval_payload,
    build_final_review_payload,
)

MAX_PATCH_ATTEMPTS = 2


def build_plan_review_graph(
    planner: StructuredPlanner,
    checkpointer: BaseCheckpointSaver[Any],
    patch_service: ApprovedPatchService | None = None,
    test_service: ApprovedPatchTestService | None = None,
    test_request: TestRunRequest | None = None,
    critic_service: CriticService | None = None,
    patch_exporter: PatchExporter | None = None,
):
    """Compile M3–M6 compatibility modes around one bounded state graph."""

    if test_service is not None and patch_service is None:
        raise ValueError("M5 test execution requires the M4 patch service")
    if (critic_service is None) != (patch_exporter is None):
        raise ValueError("M6 requires both critic and patch export services")
    m6_enabled = critic_service is not None
    if m6_enabled and test_service is None:
        raise ValueError("M6 requires M4 patch and M5 test services")
    configured_test_request = test_request or TestRunRequest()

    async def planner_node(state: PlanReviewState) -> PlanReviewState:
        try:
            plan, plan_hash = await planner.create_plan_with_hash(
                _planning_context_from_state(state)
            )
        except (PlannerError, PlanValidationError) as exc:
            return {
                "status": WorkflowStatus.PLANNER_FAILED.value,
                "plan": None,
                "plan_hash": None,
                "approved_file_scope": None,
                "planner_error": _planner_error_record(exc),
            }
        return {
            "plan": plan.model_dump(mode="json"),
            "plan_hash": plan_hash,
            "status": WorkflowStatus.AWAITING_APPROVAL.value,
            "planner_error": None,
        }

    def approval_node(state: PlanReviewState) -> PlanReviewState:
        raw = interrupt(build_approval_payload(state).model_dump(mode="json"))
        try:
            decision = ApprovalDecision.model_validate(raw)
        except ValidationError as exc:
            raise ApprovalDecisionError("invalid approval decision object") from exc
        if decision.plan_hash != state.get("plan_hash"):
            raise ApprovalDecisionError(
                "approval plan hash does not match the checkpointed plan"
            )
        return {
            "approval_decision": decision.model_dump(mode="json"),
            "reviewer_comment": decision.comment,
            "status": WorkflowStatus.APPROVAL_RECORDED.value,
        }

    def approved_node(state: PlanReviewState) -> PlanReviewState:
        return {
            "approved_file_scope": list(_repair_plan_from_state(state).proposed_files),
            "attempt_number": 1,
            "attempts": [],
            "retry_consumed": False,
            "status": WorkflowStatus.APPROVED_FOR_PATCH.value,
        }

    async def run_patch(state: PlanReviewState, attempt_number: int) -> PlanReviewState:
        if patch_service is None:
            raise RuntimeError("patch node requires an ApprovedPatchService")
        if attempt_number > MAX_PATCH_ATTEMPTS:
            return _patch_failure(PatchError("maximum patch attempts exceeded"))
        approval_data = state.get("approval_decision")
        approved_files = state.get("approved_file_scope")
        if not isinstance(approval_data, dict) or not isinstance(approved_files, list):
            return _patch_failure(PatchError("approved patch authority is incomplete"))
        retry_context = None
        if attempt_number == 2:
            if not isinstance(state.get("critic_assessment"), dict):
                return _patch_failure(PatchError("validated critic advice is missing"))
            retry_context = {
                "previous_patch_hash": state.get("patch_hash"),
                "previous_unified_diff": state.get("unified_diff"),
                "previous_test_result": state.get("test_result"),
                "critic_assessment": state.get("critic_assessment"),
            }
        try:
            approval = ApprovalDecision.model_validate(approval_data)
            artifact = await patch_service.prepare_patch(
                thread_id=state["thread_id"],
                workflow_status=state["status"],
                approval_plan_hash=approval.plan_hash,
                approved_plan=_repair_plan_from_state(state),
                approved_plan_hash=state["plan_hash"],
                approved_files=tuple(approved_files),
                context=_planning_context_from_state(state),
                attempt_number=attempt_number,
                retry_context=retry_context,
            )
        except (PatchError, PlanValidationError, ValidationError) as exc:
            return _patch_failure(exc)
        return {
            "workspace_id": artifact.workspace_id,
            "source_plan_hash": artifact.source_plan_hash,
            "changed_files": list(artifact.changed_files),
            "unified_diff": artifact.unified_diff,
            "patch_hash": artifact.patch_hash,
            "patch_error": None,
            "test_status": None,
            "tested_patch_hash": None,
            "test_result": None,
            "test_error": None,
            "attempt_number": attempt_number,
            "status": WorkflowStatus.PATCH_READY.value,
        }

    async def patch_node(state: PlanReviewState) -> PlanReviewState:
        return await run_patch(state, 1)

    async def retry_patch_node(state: PlanReviewState) -> PlanReviewState:
        if state.get("retry_consumed") is not True or state.get("attempt_number") != 1:
            return _patch_failure(PatchError("retry authority is incomplete"))
        result = await run_patch(state, 2)
        if result.get("status") == WorkflowStatus.PATCH_FAILED.value:
            result.update({
                "attempt_number": 2,
                "test_status": None,
                "tested_patch_hash": None,
                "test_result": None,
                "test_error": None,
            })
        return result

    async def run_test(state: PlanReviewState) -> PlanReviewState:
        if test_service is None:
            raise RuntimeError("test node requires an ApprovedPatchTestService")
        patch = _patch_artifact_from_state(state)
        changed = state.get("changed_files")
        source_hash = state.get("source_plan_hash")
        if patch is None or not isinstance(changed, list) or not isinstance(source_hash, str):
            return _test_state_failure(
                "TestWorkspaceIntegrityError", "patch-ready state is incomplete"
            )
        result = await test_service.run_tests(
            thread_id=state["thread_id"],
            workflow_status=state["status"],
            approved_plan_hash=source_hash,
            changed_files=tuple(changed),
            patch=patch,
            request=configured_test_request,
        )
        return _test_result_state(result, state)

    async def test_node(state: PlanReviewState) -> PlanReviewState:
        return await run_test(state)

    async def retry_test_node(state: PlanReviewState) -> PlanReviewState:
        return await run_test(state)

    async def critic_node(state: PlanReviewState) -> PlanReviewState:
        if critic_service is None:
            raise RuntimeError("critic node requires CriticService")
        if state.get("attempt_number") != 1 or state.get("retry_consumed"):
            return _critic_failure(CriticError("critic retry eligibility is exhausted"))
        patch = _patch_artifact_from_state(state)
        test_data = state.get("test_result")
        approved_files = state.get("approved_file_scope")
        if patch is None or not isinstance(test_data, dict) or not isinstance(approved_files, list):
            return _critic_failure(CriticError("critic evidence is incomplete"))
        test_result = TestRunResult.model_validate(test_data)
        if test_result.status is not TestStatus.FAILED:
            return _critic_failure(CriticError("critic requires genuine test failure"))
        try:
            assessment_id, assessment = await critic_service.assess_failure(
                thread_id=state["thread_id"],
                context=_planning_context_from_state(state),
                approved_plan=_repair_plan_from_state(state),
                approved_plan_hash=state["plan_hash"],
                approved_files=tuple(approved_files),
                patch=patch,
                test_result=test_result,
                attempt_number=1,
            )
        except (CriticError, ValidationError) as exc:
            return _critic_failure(exc)
        return {
            "critic_assessment_id": assessment_id,
            "critic_assessment": assessment.model_dump(mode="json"),
            "critic_error": None,
            "retry_consumed": assessment.retry_recommended,
            "status": (
                WorkflowStatus.CRITIC_COMPLETE.value
                if assessment.retry_recommended
                else WorkflowStatus.REPAIR_FAILED.value
            ),
        }

    def final_review_node(state: PlanReviewState) -> PlanReviewState:
        raw = interrupt(build_final_review_payload(state).model_dump(mode="json"))
        try:
            decision = FinalReviewDecision.model_validate(raw)
        except ValidationError as exc:
            raise ApprovalDecisionError("invalid final review decision object") from exc
        if decision.patch_hash != state.get("final_candidate_patch_hash"):
            raise ApprovalDecisionError(
                "final approval patch hash does not match the tested candidate"
            )
        return {
            "final_approval_decision": decision.model_dump(mode="json"),
            "final_reviewer_comment": decision.comment,
            "final_approved_patch_hash": decision.patch_hash if decision.decision == "approve" else None,
            "status": WorkflowStatus.FINAL_APPROVAL_RECORDED.value,
        }

    def final_ready_node(_state: PlanReviewState) -> PlanReviewState:
        return {"status": WorkflowStatus.AWAITING_FINAL_APPROVAL.value}

    def export_node(state: PlanReviewState) -> PlanReviewState:
        if patch_exporter is None:
            raise RuntimeError("export node requires PatchExporter")
        decision_data, test_data = state.get("final_approval_decision"), state.get("test_result")
        patch = _patch_artifact_from_state(state)
        if not isinstance(decision_data, dict) or not isinstance(test_data, dict) or patch is None:
            return _export_failure(PatchExportError("final export state is incomplete"))
        try:
            test_result = TestRunResult.model_validate(test_data)
            if test_result.test_run_id != state.get("final_candidate_test_run_id"):
                raise PatchExportError("successful test evidence identity changed")
            artifact = patch_exporter.export(
                workflow_status=state["status"],
                decision=FinalReviewDecision.model_validate(decision_data),
                approved_plan_hash=state["plan_hash"],
                attempt_number=state["attempt_number"],
                patch=patch,
                test_result=test_result,
            )
        except (PatchExportError, ValidationError) as exc:
            return _export_failure(exc)
        return {
            "export_status": "exported",
            "export_artifact": artifact.model_dump(mode="json"),
            "export_error": None,
            "status": WorkflowStatus.COMPLETED.value,
        }

    builder = StateGraph(PlanReviewState)
    builder.add_node("planner", planner_node)
    builder.add_node("approval", approval_node)
    builder.add_node("approved", approved_node)
    builder.add_node("rejected", lambda _state: {"approved_file_scope": None, "status": WorkflowStatus.REJECTED.value})
    if patch_service is not None:
        builder.add_node("patch", patch_node)
    if test_service is not None:
        builder.add_node("test", test_node)
    if m6_enabled:
        builder.add_node("critic", critic_node)
        builder.add_node("retry_patch", retry_patch_node)
        builder.add_node("retry_test", retry_test_node)
        builder.add_node("repair_failed", lambda _state: {"status": WorkflowStatus.REPAIR_FAILED.value})
        builder.add_node("final_ready", final_ready_node)
        builder.add_node("final_review", final_review_node)
        builder.add_node("final_rejected", lambda _state: {"status": WorkflowStatus.FINAL_REJECTED.value, "export_status": None})
        builder.add_node("final_approved", lambda _state: {"status": WorkflowStatus.FINAL_APPROVED.value})
        builder.add_node("export", export_node)

    builder.add_edge(START, "planner")
    builder.add_conditional_edges("planner", _after_planner, {"approval": "approval", "end": END})
    builder.add_conditional_edges("approval", _after_approval, {"approved": "approved", "rejected": "rejected"})
    builder.add_edge("rejected", END)
    if patch_service is None:
        builder.add_edge("approved", END)
    else:
        builder.add_edge("approved", "patch")
        if test_service is None:
            builder.add_edge("patch", END)
        else:
            builder.add_conditional_edges("patch", _after_patch, {"test": "test", "end": END})
            if not m6_enabled:
                builder.add_edge("test", END)
            else:
                builder.add_conditional_edges("test", _after_first_test, {"final_review": "final_ready", "critic": "critic", "repair_failed": "repair_failed", "end": END})
                builder.add_conditional_edges("critic", _after_critic, {"retry": "retry_patch", "end": END})
                builder.add_conditional_edges("retry_patch", _after_patch, {"test": "retry_test", "end": END})
                builder.add_conditional_edges("retry_test", _after_retry_test, {"final_review": "final_ready", "repair_failed": "repair_failed", "end": END})
                builder.add_edge("final_ready", "final_review")
                builder.add_conditional_edges("final_review", _after_final_review, {"approved": "final_approved", "rejected": "final_rejected"})
                builder.add_edge("final_approved", "export")
                builder.add_edge("export", END)
                builder.add_edge("final_rejected", END)
                builder.add_edge("repair_failed", END)
    return builder.compile(checkpointer=checkpointer)


def _repair_plan_from_state(state: PlanReviewState) -> RepairPlan:
    data = state.get("plan")
    if not isinstance(data, dict):
        raise ApprovalDecisionError("workflow has no validated repair plan")
    return RepairPlan.model_validate(data)


def _planning_context_from_state(state: PlanReviewState) -> PlanningContextSnapshot:
    return PlanningContextSnapshot.model_validate({
        key: state.get(key) for key in (
            "issue_text", "rendered_context", "evidence", "context_status",
            "retrieval_mode", "retrieval_degraded", "degradation_reason",
        )
    })


def _after_planner(state: PlanReviewState) -> str:
    return "end" if state.get("status") == WorkflowStatus.PLANNER_FAILED.value else "approval"


def _after_approval(state: PlanReviewState) -> str:
    data = state.get("approval_decision")
    if not isinstance(data, Mapping):
        raise ApprovalDecisionError("approval node did not record a decision")
    decision = cast(str, data.get("decision"))
    if decision not in {"approve", "reject"}:
        raise ApprovalDecisionError("approval decision must be approve or reject")
    return "approved" if decision == "approve" else "rejected"


def _after_patch(state: PlanReviewState) -> str:
    return "test" if state.get("status") == WorkflowStatus.PATCH_READY.value else "end"


def _after_first_test(state: PlanReviewState) -> str:
    if state.get("status") == WorkflowStatus.TESTS_PASSED.value:
        return "final_review"
    if state.get("status") == WorkflowStatus.TESTS_FAILED.value:
        return "critic" if state.get("test_status") == TestStatus.FAILED.value else "repair_failed"
    return "end"


def _after_critic(state: PlanReviewState) -> str:
    return "retry" if state.get("status") == WorkflowStatus.CRITIC_COMPLETE.value else "end"


def _after_retry_test(state: PlanReviewState) -> str:
    if state.get("status") == WorkflowStatus.TESTS_PASSED.value:
        return "final_review"
    return "repair_failed" if state.get("status") == WorkflowStatus.TESTS_FAILED.value else "end"


def _after_final_review(state: PlanReviewState) -> str:
    data = state.get("final_approval_decision")
    if not isinstance(data, Mapping):
        raise ApprovalDecisionError("final review did not record a decision")
    return "approved" if data.get("decision") == "approve" else "rejected"


def _patch_artifact_from_state(state: Mapping[str, Any]) -> PatchArtifact | None:
    values = (state.get("workspace_id"), state.get("source_plan_hash"), state.get("changed_files"), state.get("unified_diff"), state.get("patch_hash"))
    if not all(value is not None for value in values):
        return None
    return PatchArtifact(workspace_id=values[0], source_plan_hash=values[1], changed_files=tuple(values[2]), unified_diff=values[3], patch_hash=values[4])


def _test_result_state(result: TestRunResult, state: PlanReviewState) -> PlanReviewState:
    if result.status is TestStatus.PASSED:
        workflow_status = WorkflowStatus.TESTS_PASSED
    elif result.status in {TestStatus.FAILED, TestStatus.NO_TESTS_COLLECTED}:
        workflow_status = WorkflowStatus.TESTS_FAILED
    else:
        workflow_status = WorkflowStatus.TEST_INFRASTRUCTURE_FAILED
    attempts = list(state.get("attempts", []))
    item = {
        "attempt_number": state.get("attempt_number", 1),
        "workspace_id": result.workspace_id,
        "patch_hash": result.patch_hash,
        "changed_files": list(state.get("changed_files") or []),
        "patch_status": "patch_ready",
        "test_status": result.status.value,
        "test_run_id": result.test_run_id,
    }
    if not attempts or attempts[-1].get("attempt_number") != item["attempt_number"]:
        attempts.append(item)
    elif attempts[-1] != item:
        raise RuntimeError("attempt history conflicts with completed test evidence")
    update: PlanReviewState = {
        "attempts": attempts,
        "test_status": result.status.value,
        "tested_patch_hash": result.patch_hash,
        "test_mode": result.mode.value,
        "test_selectors": list(result.validated_selectors),
        "test_result": result.model_dump(mode="json"),
        "test_error": (
            _error_record(result.failure_classification, result.failure_message or "test stage failed safely")
            if result.failure_classification else None
        ),
        "status": workflow_status.value,
    }
    if result.status is TestStatus.PASSED:
        update["final_candidate_patch_hash"] = result.patch_hash
        update["final_candidate_test_run_id"] = result.test_run_id
    return update


def _test_state_failure(error_type: str, message: str) -> PlanReviewState:
    return {"test_status": TestStatus.INFRASTRUCTURE_FAILED.value, "tested_patch_hash": None, "test_mode": None, "test_selectors": None, "test_result": None, "test_error": _error_record(error_type, message), "status": WorkflowStatus.TEST_INFRASTRUCTURE_FAILED.value}


def _planner_error_record(error: PlannerError | PlanValidationError) -> dict[str, str | None]:
    record = _error_record(type(error).__name__, str(error))
    if isinstance(error, PlannerInferenceError):
        record.update({"provider_error_type": error.provider_error_type, "provider_error_classification": error.provider_error_classification, "provider_error_message": error.provider_error_message, "model": error.model})
    return record


def _patch_failure(error: Exception) -> PlanReviewState:
    messages = {"PatchOutputError": "patch output was not valid structured data", "PatchScopeError": "patch proposal exceeded approved authority", "PatchValidationError": "patch proposal failed deterministic validation", "StaleApprovalError": "approved evidence no longer matches source", "PatchConflictError": "workspace state conflicts with the approved patch", "PatchApplicationError": "workspace patch application failed safely", "WorkspaceError": "isolated workspace could not be prepared", "PatchInferenceError": "patch inference failed"}
    record = _error_record(type(error).__name__, messages.get(type(error).__name__, "patch stage failed safely"))
    if isinstance(error, PatchInferenceError):
        record.update({"provider_error_type": error.provider_error_type, "provider_error_classification": error.provider_error_classification, "provider_error_message": error.provider_error_message, "model": error.model})
    return {"workspace_id": None, "source_plan_hash": None, "changed_files": None, "unified_diff": None, "patch_hash": None, "patch_error": record, "status": WorkflowStatus.PATCH_FAILED.value}


def _critic_failure(error: Exception) -> PlanReviewState:
    record = _error_record(type(error).__name__, "critic stage failed safely")
    if isinstance(error, CriticInferenceError):
        record.update({"provider_error_type": error.provider_error_type, "provider_error_classification": error.provider_error_classification, "provider_error_message": error.provider_error_message, "model": error.model})
    return {"critic_error": record, "status": WorkflowStatus.CRITIC_FAILED.value}


def _export_failure(error: Exception) -> PlanReviewState:
    return {"export_status": "failed", "export_error": _error_record(type(error).__name__, "patch export failed safely"), "status": WorkflowStatus.EXPORT_FAILED.value}


def _error_record(error_type: str, message: str) -> dict[str, str | None]:
    return {"error_type": error_type, "message": message, "provider_error_type": None, "provider_error_classification": None, "provider_error_message": None, "model": None}


__all__ = ["MAX_PATCH_ATTEMPTS", "build_plan_review_graph"]
