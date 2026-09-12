"""Focused M5 LangGraph routing and JSON-state tests."""

from __future__ import annotations

import asyncio
import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.patching import ApprovedPatchService, StructuredPatcher, WorkspaceManager
from app.planning import StructuredPlanner
from app.sandbox import (
    ApprovedPatchTestService,
    DisposableTestSnapshotManager,
    TestResultStore as ResultStore,
    TestRunRequest as RunRequest,
    TestStatus as Status,
)
from app.workflow import PlanReviewService, WorkflowStatus
from tests.patching_fakes import copy_toy_repository, patch_inputs
from tests.planning_fakes import FakeInferenceProvider
from tests.sandbox_fakes import FakeTestRunner


def _workflow(tmp_path, *, test_status=Status.PASSED, patch_response=None):
    repository = copy_toy_repository(tmp_path / "input")
    pack, plan, proposal = patch_inputs(repository)
    planner = FakeInferenceProvider(plan.model_dump_json())
    patcher = FakeInferenceProvider(
        proposal.model_dump_json() if patch_response is None else patch_response
    )
    workspace_manager = WorkspaceManager(
        canonical_repository=repository,
        workspace_root=tmp_path / "workspaces",
    )
    patch_service = ApprovedPatchService(
        patcher=StructuredPatcher(patcher),
        workspace_manager=workspace_manager,
    )
    runner = FakeTestRunner(
        status=test_status,
        exit_code=0 if test_status is Status.PASSED else 1,
    )
    test_service = ApprovedPatchTestService(
        workspace_manager=workspace_manager,
        snapshot_manager=DisposableTestSnapshotManager(
            workspace_manager=workspace_manager,
            snapshot_root=(tmp_path / "executions").resolve(),
        ),
        runner=runner,
        result_store=ResultStore((tmp_path / "test-results").resolve()),
    )
    checkpointer = InMemorySaver()
    service = PlanReviewService(
        StructuredPlanner(planner),
        checkpointer,
        patch_service,
        test_service,
        RunRequest(),
    )
    return service, checkpointer, runner, patcher, pack


def _approve(service, pack, *, thread_id="m5"):
    async def scenario():
        pending = await service.start_plan_review(
            thread_id=thread_id,
            context_pack=pack,
        )
        final = await service.resume_plan_review(
            thread_id=thread_id,
            decision={"decision": "approve", "plan_hash": pending.plan_hash},
        )
        return pending, final

    return asyncio.run(scenario())


@pytest.mark.parametrize(
    ("test_status", "workflow_status"),
    [
        (Status.PASSED, WorkflowStatus.TESTS_PASSED),
        (Status.FAILED, WorkflowStatus.TESTS_FAILED),
        (
            Status.INFRASTRUCTURE_FAILED,
            WorkflowStatus.TEST_INFRASTRUCTURE_FAILED,
        ),
        (Status.TIMED_OUT, WorkflowStatus.TEST_INFRASTRUCTURE_FAILED),
    ],
)
def test_patch_ready_runs_test_once_and_reaches_m5_terminal(
    tmp_path, test_status, workflow_status
) -> None:
    service, _checkpointer, runner, patcher, pack = _workflow(
        tmp_path,
        test_status=test_status,
    )

    pending, final = _approve(service, pack)

    assert final.status is workflow_status
    assert final.patch is not None
    assert final.test is not None
    assert final.test.patch_hash == final.patch.patch_hash
    assert final.test.workspace_id == final.patch.workspace_id
    assert final.test.status is test_status
    assert pending.plan_hash == final.patch.source_plan_hash
    assert patcher.calls == 1
    assert len(runner.calls) == 1


def test_rejected_plan_never_reaches_patch_or_test(tmp_path) -> None:
    service, _checkpointer, runner, patcher, pack = _workflow(tmp_path)

    async def scenario():
        pending = await service.start_plan_review(thread_id="reject", context_pack=pack)
        return await service.resume_plan_review(
            thread_id="reject",
            decision={"decision": "reject", "plan_hash": pending.plan_hash},
        )

    result = asyncio.run(scenario())

    assert result.status is WorkflowStatus.REJECTED
    assert result.patch is None
    assert result.test is None
    assert patcher.calls == 0
    assert runner.calls == []


def test_patch_failure_never_reaches_test(tmp_path) -> None:
    service, _checkpointer, runner, patcher, pack = _workflow(
        tmp_path,
        patch_response="not-json",
    )

    _pending, result = _approve(service, pack)

    assert result.status is WorkflowStatus.PATCH_FAILED
    assert result.test is None
    assert patcher.calls == 1
    assert runner.calls == []


def test_m5_checkpoint_state_is_json_friendly_and_path_free(tmp_path) -> None:
    service, checkpointer, _runner, _patcher, pack = _workflow(tmp_path)

    _pending, result = _approve(service, pack, thread_id="json-state")
    checkpoint = checkpointer.get_tuple(
        {"configurable": {"thread_id": "json-state"}}
    )
    serialized = json.dumps(checkpoint.checkpoint)

    assert result.status is WorkflowStatus.TESTS_PASSED
    assert result.test.test_run_id in serialized
    assert result.test.patch_hash in serialized
    assert str(tmp_path) not in serialized
    assert "ProcessResult" not in serialized


def test_completed_workflow_does_not_rerun_test_on_invalid_resume(tmp_path) -> None:
    service, _checkpointer, runner, _patcher, pack = _workflow(tmp_path)
    pending, final = _approve(service, pack, thread_id="replay")

    replay = asyncio.run(
        service.resume_plan_review(
            thread_id="replay",
            decision={"decision": "approve", "plan_hash": pending.plan_hash},
        )
    )

    assert final.status is WorkflowStatus.TESTS_PASSED
    assert replay.status is WorkflowStatus.VALIDATION_FAILED
    assert len(runner.calls) == 1


def test_independent_threads_produce_isolated_test_evidence(tmp_path) -> None:
    service, _checkpointer, runner, _patcher, pack = _workflow(tmp_path)

    _first_pending, first = _approve(service, pack, thread_id="first")
    _second_pending, second = _approve(service, pack, thread_id="second")

    assert first.status is second.status is WorkflowStatus.TESTS_PASSED
    assert first.patch.workspace_id != second.patch.workspace_id
    assert first.test.test_run_id != second.test.test_run_id
    assert len(runner.calls) == 2
