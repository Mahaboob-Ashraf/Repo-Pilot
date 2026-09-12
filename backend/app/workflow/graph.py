"""One bounded LangGraph plan-and-approval workflow for M3."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from app.planning import (
    PlanningContextSnapshot,
    PlanValidationError,
    PlannerError,
    PlannerInferenceError,
    RepairPlan,
    StructuredPlanner,
)
from app.patching import ApprovedPatchService, PatchError, PatchInferenceError
from app.workflow.models import (
    ApprovalDecision,
    ApprovalDecisionError,
    PlanReviewState,
    WorkflowStatus,
    build_approval_payload,
)


def build_plan_review_graph(
    planner: StructuredPlanner,
    checkpointer: BaseCheckpointSaver[Any],
    patch_service: ApprovedPatchService | None = None,
):
    """Compile the bounded M3 graph with an optional M4 patch continuation."""

    async def planner_node(state: PlanReviewState) -> PlanReviewState:
        context = PlanningContextSnapshot.model_validate(
            {
                "issue_text": state["issue_text"],
                "rendered_context": state["rendered_context"],
                "evidence": state["evidence"],
                "context_status": state["context_status"],
                "retrieval_mode": state["retrieval_mode"],
                "retrieval_degraded": state["retrieval_degraded"],
                "degradation_reason": state.get("degradation_reason"),
            }
        )
        try:
            plan, plan_hash = await planner.create_plan_with_hash(context)
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
        # Everything before interrupt() is pure and deterministic because this node
        # restarts from its beginning when the graph is resumed.
        payload = build_approval_payload(state)
        raw_decision = interrupt(payload.model_dump(mode="json"))
        try:
            decision = ApprovalDecision.model_validate(raw_decision)
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
        plan = _repair_plan_from_state(state)
        return {
            "approved_file_scope": list(plan.proposed_files),
            "status": WorkflowStatus.APPROVED_FOR_PATCH.value,
        }

    async def patch_node(state: PlanReviewState) -> PlanReviewState:
        if patch_service is None:
            raise RuntimeError("patch node requires an ApprovedPatchService")
        plan = _repair_plan_from_state(state)
        context = _planning_context_from_state(state)
        approval_data = state.get("approval_decision")
        approved_files = state.get("approved_file_scope")
        if not isinstance(approval_data, dict) or not isinstance(approved_files, list):
            return _patch_failure(PatchError("approved patch authority is incomplete"))
        try:
            approval = ApprovalDecision.model_validate(approval_data)
            artifact = await patch_service.prepare_patch(
                thread_id=state["thread_id"],
                workflow_status=state["status"],
                approval_plan_hash=approval.plan_hash,
                approved_plan=plan,
                approved_plan_hash=state["plan_hash"],
                approved_files=tuple(approved_files),
                context=context,
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
            "status": WorkflowStatus.PATCH_READY.value,
        }

    def rejected_node(state: PlanReviewState) -> PlanReviewState:
        return {
            "approved_file_scope": None,
            "status": WorkflowStatus.REJECTED.value,
        }

    builder = StateGraph(PlanReviewState)
    builder.add_node("planner", planner_node)
    builder.add_node("approval", approval_node)
    builder.add_node("approved", approved_node)
    builder.add_node("rejected", rejected_node)
    if patch_service is not None:
        builder.add_node("patch", patch_node)
    builder.add_edge(START, "planner")
    builder.add_conditional_edges(
        "planner",
        _after_planner,
        {"approval": "approval", "end": END},
    )
    builder.add_conditional_edges(
        "approval",
        _after_approval,
        {"approved": "approved", "rejected": "rejected"},
    )
    if patch_service is None:
        builder.add_edge("approved", END)
    else:
        builder.add_edge("approved", "patch")
        builder.add_edge("patch", END)
    builder.add_edge("rejected", END)
    return builder.compile(checkpointer=checkpointer)


def _repair_plan_from_state(state: PlanReviewState) -> RepairPlan:
    """Validate the already-grounded plan at the terminal scope-freeze node."""

    plan_data = state.get("plan")
    if not isinstance(plan_data, dict):
        raise ApprovalDecisionError("workflow has no validated repair plan")
    return RepairPlan.model_validate(plan_data)


def _planning_context_from_state(state: PlanReviewState) -> PlanningContextSnapshot:
    return PlanningContextSnapshot.model_validate(
        {
            "issue_text": state["issue_text"],
            "rendered_context": state["rendered_context"],
            "evidence": state["evidence"],
            "context_status": state["context_status"],
            "retrieval_mode": state["retrieval_mode"],
            "retrieval_degraded": state["retrieval_degraded"],
            "degradation_reason": state.get("degradation_reason"),
        }
    )


def _after_planner(state: PlanReviewState) -> str:
    if state.get("status") == WorkflowStatus.PLANNER_FAILED.value:
        return "end"
    return "approval"


def _planner_error_record(
    error: PlannerError | PlanValidationError,
) -> dict[str, str | None]:
    record: dict[str, str | None] = {
        "error_type": type(error).__name__,
        "message": str(error),
        "provider_error_type": None,
        "provider_error_classification": None,
        "provider_error_message": None,
        "model": None,
    }
    if isinstance(error, PlannerInferenceError):
        record.update(
            {
                "provider_error_type": error.provider_error_type,
                "provider_error_classification": (
                    error.provider_error_classification
                ),
                "provider_error_message": error.provider_error_message,
                "model": error.model,
            }
        )
    return record


def _patch_failure(error: Exception) -> PlanReviewState:
    messages = {
        "PatchOutputError": "patch output was not valid structured data",
        "PatchScopeError": "patch proposal exceeded approved authority",
        "PatchValidationError": "patch proposal failed deterministic validation",
        "StaleApprovalError": "approved evidence no longer matches source",
        "PatchConflictError": "workspace state conflicts with the approved patch",
        "PatchApplicationError": "workspace patch application failed safely",
        "WorkspaceError": "isolated workspace could not be prepared",
        "PatchInferenceError": "patch inference failed",
        "PlanValidationError": "approved plan grounding is no longer valid",
        "ValidationError": "approved patch state is invalid",
        "PatchError": "approved patch authority is incomplete",
    }
    record: dict[str, str | None] = {
        "error_type": type(error).__name__,
        "message": messages.get(type(error).__name__, "patch stage failed safely"),
        "provider_error_type": None,
        "provider_error_classification": None,
        "provider_error_message": None,
        "model": None,
    }
    if isinstance(error, PatchInferenceError):
        record.update(
            {
                "provider_error_type": error.provider_error_type,
                "provider_error_classification": error.provider_error_classification,
                "provider_error_message": error.provider_error_message,
                "model": error.model,
            }
        )
    return {
        "workspace_id": None,
        "source_plan_hash": None,
        "changed_files": None,
        "unified_diff": None,
        "patch_hash": None,
        "patch_error": record,
        "status": WorkflowStatus.PATCH_FAILED.value,
    }


def _after_approval(state: PlanReviewState) -> str:
    decision_data = state.get("approval_decision")
    if not isinstance(decision_data, Mapping):
        raise ApprovalDecisionError("approval node did not record a decision")
    decision = cast(str, decision_data.get("decision"))
    if decision == "approve":
        return "approved"
    if decision == "reject":
        return "rejected"
    raise ApprovalDecisionError("approval decision must be approve or reject")
