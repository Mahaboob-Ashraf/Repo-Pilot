"""Focused M4 LangGraph approved/rejected patch-stage tests."""

from __future__ import annotations

import asyncio
import json

from langgraph.checkpoint.memory import InMemorySaver

from app.patching import (
    ApprovedPatchService,
    PatchEdit,
    StructuredPatcher,
    WorkspaceManager,
)
from app.planning import StructuredPlanner
from app.workflow import PlanReviewService, WorkflowStatus
from tests.patching_fakes import copy_toy_repository, patch_inputs
from tests.planning_fakes import FakeInferenceProvider


def _workflow(tmp_path, *, patch_response=None):
    repository = copy_toy_repository(tmp_path)
    pack, plan, proposal = patch_inputs(repository)
    planner_provider = FakeInferenceProvider(plan.model_dump_json())
    patcher_provider = FakeInferenceProvider(
        (patch_response or proposal).model_dump_json()
    )
    checkpointer = InMemorySaver()
    patch_service = ApprovedPatchService(
        patcher=StructuredPatcher(patcher_provider),
        workspace_manager=WorkspaceManager(
            canonical_repository=repository,
            workspace_root=tmp_path / "workspaces",
        ),
    )
    service = PlanReviewService(
        StructuredPlanner(planner_provider),
        checkpointer,
        patch_service,
    )
    return service, checkpointer, planner_provider, patcher_provider, pack, plan, proposal


def test_reject_path_never_calls_patcher_or_creates_workspace(tmp_path) -> None:
    service, _checkpointer, _planner, patcher, pack, _plan, _proposal = _workflow(
        tmp_path
    )

    async def scenario():
        pending = await service.start_plan_review(thread_id="reject", context_pack=pack)
        return await service.resume_plan_review(
            thread_id="reject",
            decision={
                "decision": "reject",
                "plan_hash": pending.plan_hash,
            },
        )

    result = asyncio.run(scenario())

    assert result.status is WorkflowStatus.REJECTED
    assert result.patch is None
    assert patcher.calls == 0
    assert not tuple((tmp_path / "workspaces").glob("workspace-*"))


def test_approve_path_enters_patch_stage_and_ends_patch_ready(tmp_path) -> None:
    service, _checkpointer, planner, patcher, pack, plan, _proposal = _workflow(
        tmp_path
    )

    async def scenario():
        pending = await service.start_plan_review(thread_id="approve", context_pack=pack)
        return pending, await service.resume_plan_review(
            thread_id="approve",
            decision={
                "decision": "approve",
                "plan_hash": pending.plan_hash,
                "comment": "Approved exact scope.",
            },
        )

    pending, result = asyncio.run(scenario())

    assert pending.status is WorkflowStatus.AWAITING_APPROVAL
    assert result.status is WorkflowStatus.PATCH_READY
    assert result.approved_file_scope == plan.proposed_files
    assert result.patch is not None
    assert result.patch.source_plan_hash == pending.plan_hash
    assert result.patch.changed_files == ("pricing.py",)
    assert result.error is None
    assert planner.calls == 1
    assert patcher.calls == 1


def test_model_cannot_expand_checkpointed_approved_scope(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path / "inputs")
    pack, plan, proposal = patch_inputs(repository)
    test_evidence = next(
        item for item in pack.included_chunks if item.path == "tests/test_pricing.py"
    )
    expanded = proposal.model_copy(
        update={
            "edits": proposal.edits
            + (
                PatchEdit(
                    path="tests/test_pricing.py",
                    expected_old_text="50.0, 0.0",
                    replacement_text="50.0, 1.0",
                    evidence_chunk_ids=(test_evidence.chunk_id,),
                    rationale="Unapproved expansion.",
                ),
            )
        }
    )
    planner_provider = FakeInferenceProvider(plan.model_dump_json())
    patcher_provider = FakeInferenceProvider(expanded.model_dump_json())
    service = PlanReviewService(
        StructuredPlanner(planner_provider),
        InMemorySaver(),
        ApprovedPatchService(
            patcher=StructuredPatcher(patcher_provider),
            workspace_manager=WorkspaceManager(
                canonical_repository=repository,
                workspace_root=tmp_path / "workspaces",
            ),
        ),
    )

    async def scenario():
        pending = await service.start_plan_review(thread_id="scope", context_pack=pack)
        return await service.resume_plan_review(
            thread_id="scope",
            decision={"decision": "approve", "plan_hash": pending.plan_hash},
        )

    result = asyncio.run(scenario())

    assert result.status is WorkflowStatus.PATCH_FAILED
    assert result.patch is None
    assert result.error.error_type == "PatchScopeError"
    assert result.error.message == "patch proposal exceeded approved authority"


def test_exact_patch_validation_reason_is_retained_safely(tmp_path) -> None:
    service, _checkpointer, _planner, patcher, pack, _plan, proposal = _workflow(
        tmp_path
    )
    invalid_edit = proposal.edits[0].model_copy(
        update={"expected_old_text": "return price * (1 + missing / 100)"}
    )
    patcher.response = proposal.model_copy(
        update={"edits": (invalid_edit,)}
    ).model_dump_json()

    async def scenario():
        pending = await service.start_plan_review(
            thread_id="specific-patch-failure", context_pack=pack
        )
        return await service.resume_plan_review(
            thread_id="specific-patch-failure",
            decision={"decision": "approve", "plan_hash": pending.plan_hash},
        )

    result = asyncio.run(scenario())

    assert result.status is WorkflowStatus.PATCH_FAILED
    assert result.error.error_type == "PatchValidationError"
    assert result.error.message == "expected_old_text was not found exactly"


def test_malformed_patch_output_fails_without_patch_ready(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path / "inputs")
    pack, plan, _proposal = patch_inputs(repository)
    patcher_provider = FakeInferenceProvider("malformed")
    service = PlanReviewService(
        StructuredPlanner(FakeInferenceProvider(plan.model_dump_json())),
        InMemorySaver(),
        ApprovedPatchService(
            patcher=StructuredPatcher(patcher_provider),
            workspace_manager=WorkspaceManager(
                canonical_repository=repository,
                workspace_root=tmp_path / "workspaces",
            ),
        ),
    )

    async def scenario():
        pending = await service.start_plan_review(thread_id="failure", context_pack=pack)
        return await service.resume_plan_review(
            thread_id="failure",
            decision={"decision": "approve", "plan_hash": pending.plan_hash},
        )

    result = asyncio.run(scenario())

    assert result.status is WorkflowStatus.PATCH_FAILED
    assert result.patch is None
    assert result.error.error_type == "PatchOutputError"
    assert patcher_provider.calls == 1


def test_checkpoint_state_records_only_json_friendly_patch_artifact(tmp_path) -> None:
    service, checkpointer, _planner, _patcher, pack, _plan, _proposal = _workflow(
        tmp_path
    )

    async def scenario():
        pending = await service.start_plan_review(thread_id="state", context_pack=pack)
        return await service.resume_plan_review(
            thread_id="state",
            decision={"decision": "approve", "plan_hash": pending.plan_hash},
        )

    result = asyncio.run(scenario())
    checkpoint = checkpointer.get_tuple({"configurable": {"thread_id": "state"}})
    serialized = json.dumps(checkpoint.checkpoint)

    assert result.status is WorkflowStatus.PATCH_READY
    assert result.patch.workspace_id in serialized
    assert result.patch.patch_hash in serialized
    assert (
        checkpoint.checkpoint["channel_values"]["unified_diff"]
        == result.patch.unified_diff
    )
    assert str(tmp_path) not in serialized


def test_independent_graph_threads_create_isolated_patch_workspaces(tmp_path) -> None:
    service, _checkpointer, _planner, patcher, pack, _plan, _proposal = _workflow(
        tmp_path
    )

    async def scenario():
        first_pending = await service.start_plan_review(
            thread_id="first", context_pack=pack
        )
        first = await service.resume_plan_review(
            thread_id="first",
            decision={"decision": "approve", "plan_hash": first_pending.plan_hash},
        )
        second_pending = await service.start_plan_review(
            thread_id="second", context_pack=pack
        )
        second = await service.resume_plan_review(
            thread_id="second",
            decision={"decision": "approve", "plan_hash": second_pending.plan_hash},
        )
        return first, second

    first, second = asyncio.run(scenario())

    assert first.status is second.status is WorkflowStatus.PATCH_READY
    assert first.patch.workspace_id != second.patch.workspace_id
    assert patcher.calls == 2
