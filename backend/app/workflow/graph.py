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
):
    """Compile the M3 graph with services captured outside checkpointed state."""

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
    builder.add_edge("approved", END)
    builder.add_edge("rejected", END)
    return builder.compile(checkpointer=checkpointer)


def _repair_plan_from_state(state: PlanReviewState) -> RepairPlan:
    """Validate the already-grounded plan at the terminal scope-freeze node."""

    plan_data = state.get("plan")
    if not isinstance(plan_data, dict):
        raise ApprovalDecisionError("workflow has no validated repair plan")
    return RepairPlan.model_validate(plan_data)


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
