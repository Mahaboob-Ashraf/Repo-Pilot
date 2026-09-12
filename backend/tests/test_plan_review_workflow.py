"""Focused LangGraph interrupt, approval-state, and persistence tests."""

from __future__ import annotations

import asyncio
from hashlib import sha256
import json
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from app.planning import StructuredPlanner
from app.providers.base import InferenceUnavailableError
from app.workflow import (
    ApprovalDecision,
    CheckpointConfigurationError,
    PlanReviewService,
    WorkflowStatus,
    open_sqlite_plan_review_service,
)
from tests.planning_fakes import (
    FakeInferenceProvider,
    TOY_REPOSITORY,
    make_context_pack,
    make_valid_plan,
)


def _service() -> tuple[PlanReviewService, FakeInferenceProvider]:
    pack = make_context_pack()
    provider = FakeInferenceProvider(make_valid_plan(pack).model_dump_json())
    return PlanReviewService(StructuredPlanner(provider), InMemorySaver()), provider


def test_initial_run_plans_then_pauses_with_reviewable_interrupt_payload() -> None:
    async def scenario():
        service, provider = _service()
        result = await service.start_plan_review(
            thread_id="initial-pause", context_pack=make_context_pack()
        )
        return result, provider

    result, provider = asyncio.run(scenario())

    assert result.status is WorkflowStatus.AWAITING_APPROVAL
    assert provider.calls == 1
    assert result.plan is not None
    assert result.plan_hash is not None
    assert result.approved_file_scope is None
    assert result.approval_decision is None
    assert result.approval_payload is not None
    assert result.approval_payload.plan == result.plan
    assert result.approval_payload.plan_hash == result.plan_hash
    assert result.approval_payload.proposed_file_scope == result.plan.proposed_files
    assert result.approval_payload.evidence
    assert {
        item.chunk_id for item in result.approval_payload.evidence
    } == {
        chunk_id
        for step in result.plan.steps
        for chunk_id in step.evidence_chunk_ids
    }


def test_approve_resumes_same_thread_and_freezes_validated_file_scope() -> None:
    async def scenario():
        service, provider = _service()
        pending = await service.start_plan_review(
            thread_id="approve-thread", context_pack=make_context_pack()
        )
        approved = await service.resume_plan_review(
            thread_id="approve-thread",
            decision={
                "decision": "approve",
                "plan_hash": pending.plan_hash,
                "comment": "Scope reviewed.",
            },
        )
        return pending, approved, provider

    pending, approved, provider = asyncio.run(scenario())

    assert approved.status is WorkflowStatus.APPROVED_FOR_PATCH
    assert approved.approved_file_scope == pending.plan.proposed_files
    assert approved.approval_decision == ApprovalDecision(
        decision="approve",
        plan_hash=pending.plan_hash,
        comment="Scope reviewed.",
    )
    assert approved.reviewer_comment == "Scope reviewed."
    assert provider.calls == 1


def test_reject_resumes_same_thread_and_terminates_without_file_scope() -> None:
    async def scenario():
        service, provider = _service()
        pending = await service.start_plan_review(
            thread_id="reject-thread", context_pack=make_context_pack()
        )
        rejected = await service.resume_plan_review(
            thread_id="reject-thread",
            decision={
                "decision": "reject",
                "plan_hash": pending.plan_hash,
                "comment": "Diagnosis needs revision.",
            },
        )
        return rejected, provider

    rejected, provider = asyncio.run(scenario())

    assert rejected.status is WorkflowStatus.REJECTED
    assert rejected.approved_file_scope is None
    assert rejected.approval_decision.decision == "reject"
    assert rejected.reviewer_comment == "Diagnosis needs revision."
    assert provider.calls == 1


def test_stale_plan_hash_cannot_approve_and_checkpoint_remains_pending() -> None:
    async def scenario():
        service, provider = _service()
        pending = await service.start_plan_review(
            thread_id="stale-thread", context_pack=make_context_pack()
        )
        stale = await service.resume_plan_review(
            thread_id="stale-thread",
            decision={"decision": "approve", "plan_hash": "0" * 64},
        )
        approved = await service.resume_plan_review(
            thread_id="stale-thread",
            decision={"decision": "approve", "plan_hash": pending.plan_hash},
        )
        return stale, approved, provider

    stale, approved, provider = asyncio.run(scenario())

    assert stale.status is WorkflowStatus.VALIDATION_FAILED
    assert stale.error.error_type == "ApprovalDecisionError"
    assert "does not match" in stale.error.message
    assert stale.approved_file_scope is None
    assert stale.approval_payload is not None
    assert approved.status is WorkflowStatus.APPROVED_FOR_PATCH
    assert provider.calls == 1


def test_invalid_decision_object_does_not_resume_checkpoint() -> None:
    async def scenario():
        service, _ = _service()
        pending = await service.start_plan_review(
            thread_id="invalid-decision", context_pack=make_context_pack()
        )
        invalid = await service.resume_plan_review(
            thread_id="invalid-decision",
            decision={"decision": "maybe", "plan_hash": pending.plan_hash},
        )
        return invalid

    invalid = asyncio.run(scenario())

    assert invalid.status is WorkflowStatus.VALIDATION_FAILED
    assert invalid.error.error_type == "ApprovalDecisionError"
    assert invalid.approval_payload is not None


def test_independent_thread_ids_do_not_share_state() -> None:
    async def scenario():
        service, provider = _service()
        first = await service.start_plan_review(
            thread_id="thread-a", context_pack=make_context_pack()
        )
        second = await service.start_plan_review(
            thread_id="thread-b", context_pack=make_context_pack()
        )
        approved = await service.resume_plan_review(
            thread_id="thread-a",
            decision={"decision": "approve", "plan_hash": first.plan_hash},
        )
        rejected = await service.resume_plan_review(
            thread_id="thread-b",
            decision={"decision": "reject", "plan_hash": second.plan_hash},
        )
        return approved, rejected, provider

    approved, rejected, provider = asyncio.run(scenario())

    assert approved.status is WorkflowStatus.APPROVED_FOR_PATCH
    assert rejected.status is WorkflowStatus.REJECTED
    assert provider.calls == 2


def test_wrong_thread_id_has_no_approval_checkpoint() -> None:
    async def scenario():
        service, _ = _service()
        pending = await service.start_plan_review(
            thread_id="real-thread", context_pack=make_context_pack()
        )
        return await service.resume_plan_review(
            thread_id="other-thread",
            decision={"decision": "approve", "plan_hash": pending.plan_hash},
        )

    result = asyncio.run(scenario())

    assert result.status is WorkflowStatus.VALIDATION_FAILED
    assert "no checkpointed approval" in result.error.message


def test_planner_failure_is_terminal_and_never_reaches_approval() -> None:
    async def scenario():
        provider = FakeInferenceProvider("malformed")
        service = PlanReviewService(StructuredPlanner(provider), InMemorySaver())
        result = await service.start_plan_review(
            thread_id="planner-failure", context_pack=make_context_pack()
        )
        return result, provider

    result, provider = asyncio.run(scenario())

    assert result.status is WorkflowStatus.PLANNER_FAILED
    assert result.error.error_type == "PlannerOutputError"
    assert result.plan is None
    assert result.plan_hash is None
    assert result.approval_payload is None
    assert provider.calls == 1


def test_inference_failure_persists_only_safe_structured_diagnostics() -> None:
    secret = "must-not-leak-api-key"

    class UnavailableProvider(FakeInferenceProvider):
        async def generate(self, prompt: str) -> str:
            self.calls += 1
            self.prompts.append(prompt)
            raise InferenceUnavailableError(
                f"Authorization: Bearer {secret}; headers={{private}}; "
                "request_body=<full-payload>"
            )

    before = {
        path.relative_to(TOY_REPOSITORY).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(TOY_REPOSITORY.rglob("*.py"))
    }
    provider = UnavailableProvider("unused")
    checkpointer = InMemorySaver()
    service = PlanReviewService(StructuredPlanner(provider), checkpointer)

    result = asyncio.run(
        service.start_plan_review(
            thread_id="safe-inference-failure",
            context_pack=make_context_pack(),
        )
    )
    checkpoint = checkpointer.get_tuple(
        {"configurable": {"thread_id": "safe-inference-failure"}}
    )
    persisted_json = json.dumps(checkpoint.checkpoint, default=str)
    after = {
        path.relative_to(TOY_REPOSITORY).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(TOY_REPOSITORY.rglob("*.py"))
    }

    assert result.status is WorkflowStatus.PLANNER_FAILED
    assert result.approval_payload is None
    assert result.plan is None
    assert result.plan_hash is None
    assert result.error.error_type == "PlannerInferenceError"
    assert result.error.provider_error_type == "InferenceUnavailableError"
    assert result.error.provider_error_classification == "availability_error"
    assert result.error.provider_error_message == "Inference provider is unavailable"
    assert result.error.model == "fake-planner"
    assert secret not in persisted_json
    assert "Authorization" not in persisted_json
    assert "request_body" not in persisted_json
    assert before == after
    assert provider.calls == 1


def test_repository_files_remain_unchanged_through_plan_and_approval() -> None:
    def digests() -> dict[str, str]:
        return {
            path.relative_to(TOY_REPOSITORY).as_posix(): sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(TOY_REPOSITORY.rglob("*.py"))
        }

    before = digests()

    async def scenario():
        service, _ = _service()
        pending = await service.start_plan_review(
            thread_id="read-only-proof", context_pack=make_context_pack()
        )
        await service.resume_plan_review(
            thread_id="read-only-proof",
            decision={"decision": "approve", "plan_hash": pending.plan_hash},
        )

    asyncio.run(scenario())

    assert digests() == before


def test_sqlite_checkpointer_creates_isolated_local_database(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "checkpoints.sqlite3"

    async def scenario():
        pack = make_context_pack()
        provider = FakeInferenceProvider(make_valid_plan(pack).model_dump_json())
        async with open_sqlite_plan_review_service(
            planner=StructuredPlanner(provider),
            checkpoint_path=checkpoint_path,
        ) as service:
            result = await service.start_plan_review(
                thread_id="sqlite-create", context_pack=pack
            )
        return result

    result = asyncio.run(scenario())

    assert result.status is WorkflowStatus.AWAITING_APPROVAL
    assert checkpoint_path.is_file()
    assert checkpoint_path.stat().st_size > 0


def test_sqlite_pause_resumes_after_service_reconstruction(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "durable.sqlite3"

    async def scenario():
        pack = make_context_pack()
        first_provider = FakeInferenceProvider(make_valid_plan(pack).model_dump_json())
        async with open_sqlite_plan_review_service(
            planner=StructuredPlanner(first_provider),
            checkpoint_path=checkpoint_path,
        ) as first_service:
            pending = await first_service.start_plan_review(
                thread_id="durable-thread", context_pack=pack
            )

        second_provider = FakeInferenceProvider("must not be called on resume")
        async with open_sqlite_plan_review_service(
            planner=StructuredPlanner(second_provider),
            checkpoint_path=checkpoint_path,
        ) as second_service:
            approved = await second_service.resume_plan_review(
                thread_id="durable-thread",
                decision={
                    "decision": "approve",
                    "plan_hash": pending.plan_hash,
                },
            )
        return pending, approved, first_provider, second_provider

    pending, approved, first_provider, second_provider = asyncio.run(scenario())

    assert pending.status is WorkflowStatus.AWAITING_APPROVAL
    assert approved.status is WorkflowStatus.APPROVED_FOR_PATCH
    assert approved.approved_file_scope == pending.plan.proposed_files
    assert first_provider.calls == 1
    assert second_provider.calls == 0


def test_checkpoint_database_inside_source_repository_is_rejected() -> None:
    source_db = Path(__file__).parents[2] / ".repopilot" / "checkpoints.sqlite3"

    async def scenario():
        service_context = open_sqlite_plan_review_service(
            planner=StructuredPlanner(FakeInferenceProvider("unused")),
            checkpoint_path=source_db,
        )
        async with service_context:
            raise AssertionError("unsafe checkpoint path unexpectedly opened")

    try:
        asyncio.run(scenario())
    except CheckpointConfigurationError:
        pass
    else:
        raise AssertionError("source-tree checkpoint path was not rejected")
    assert not source_db.exists()
