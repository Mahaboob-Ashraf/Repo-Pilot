"""Bounded M6 retry, final interrupt, export, and replay tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json

from langgraph.checkpoint.memory import InMemorySaver

from app.critic import (
    CriticAssessment,
    CriticAssessmentStore,
    CriticService,
    RetryInstruction,
    StructuredCritic,
)
from app.exporting import PatchExporter
from app.patching import ApprovedPatchService, PatchEdit, PatchProposal, StructuredPatcher, WorkspaceManager
from app.planning import StructuredPlanner
from app.sandbox import ApprovedPatchTestService, DisposableTestSnapshotManager
from app.sandbox import TestResultStore as SandboxResultStore
from app.sandbox import TestRunRequest as SandboxRequest
from app.sandbox import TestStatus as SandboxStatus
from app.workflow import PlanReviewService, WorkflowStatus, open_sqlite_plan_review_service
from tests.patching_fakes import OLD_CALCULATION, NEW_CALCULATION, copy_toy_repository, patch_inputs
from tests.planning_fakes import FakeInferenceProvider
from tests.sandbox_fakes import FakeTestRunner


@dataclass
class SequenceProvider:
    responses: list[str]
    prompts: list[str] = field(default_factory=list)
    calls: int = 0

    @property
    def model(self) -> str:
        return "fake-sequence"

    async def generate(self, prompt: str) -> str:
        index = self.calls
        self.calls += 1
        self.prompts.append(prompt)
        return self.responses[index]


class SequenceRunner(FakeTestRunner):
    def __init__(self, statuses):
        super().__init__()
        self.statuses = list(statuses)

    async def run(self, spec):
        self.status = self.statuses[len(self.calls)]
        self.exit_code = 0 if self.status is SandboxStatus.PASSED else 1
        return await super().run(spec)


def _workflow(tmp_path, *, statuses, retry=True, critic_response=None):
    repository = copy_toy_repository(tmp_path / "input")
    pack, plan, correct = patch_inputs(repository)
    evidence = next(item for item in pack.included_chunks if item.path == "pricing.py")
    wrong = PatchProposal(
        summary="An incomplete first correction.",
        edits=(PatchEdit(
            path="pricing.py", expected_old_text=OLD_CALCULATION,
            replacement_text="return price * (1 - discount_percent / 200)",
            evidence_chunk_ids=(evidence.chunk_id,), rationale="Attempt a subtraction.",
        ),),
    )
    assessment = CriticAssessment(
        summary="The discount magnitude remains wrong.",
        failure_diagnosis="The divisor halves the requested discount.",
        retry_recommended=retry,
        retry_instructions=(
            (RetryInstruction(
                description="Use the full approved percentage in the pricing formula.",
                affected_files=("pricing.py",),
            ),) if retry else ()
        ),
        evidence_chunk_ids=(evidence.chunk_id,),
    )
    patch_provider = SequenceProvider(
        [
            (correct if statuses[0] is SandboxStatus.PASSED else wrong).model_dump_json(),
            correct.model_dump_json(),
        ]
    )
    critic_provider = FakeInferenceProvider(
        critic_response if critic_response is not None else assessment.model_dump_json()
    )
    manager = WorkspaceManager(
        canonical_repository=repository,
        workspace_root=(tmp_path / "workspaces").resolve(),
    )
    patch_service = ApprovedPatchService(
        patcher=StructuredPatcher(patch_provider), workspace_manager=manager
    )
    runner = SequenceRunner(statuses)
    test_service = ApprovedPatchTestService(
        workspace_manager=manager,
        snapshot_manager=DisposableTestSnapshotManager(
            workspace_manager=manager, snapshot_root=(tmp_path / "executions").resolve()
        ),
        runner=runner,
        result_store=SandboxResultStore((tmp_path / "test-results").resolve()),
    )
    critic_service = CriticService(
        StructuredCritic(critic_provider),
        CriticAssessmentStore((tmp_path / "critic-results").resolve()),
    )
    exporter = PatchExporter(
        export_root=(tmp_path / "exports").resolve(), workspace_manager=manager
    )
    service = PlanReviewService(
        StructuredPlanner(FakeInferenceProvider(plan.model_dump_json())),
        InMemorySaver(), patch_service, test_service, SandboxRequest(),
        critic_service, exporter,
    )
    return service, pack, repository, manager, patch_provider, critic_provider, runner, exporter


def _approve_plan(service, pack, thread_id="m6"):
    async def scenario():
        pending = await service.start_plan_review(thread_id=thread_id, context_pack=pack)
        return await service.resume_plan_review(
            thread_id=thread_id,
            decision={"decision": "approve", "plan_hash": pending.plan_hash},
        )
    return asyncio.run(scenario())


def test_attempt_one_pass_skips_critic_and_reaches_real_final_interrupt(tmp_path) -> None:
    service, pack, _repo, _manager, patcher, critic, runner, _exporter = _workflow(
        tmp_path, statuses=[SandboxStatus.PASSED]
    )
    result = _approve_plan(service, pack)
    assert result.status is WorkflowStatus.AWAITING_FINAL_APPROVAL
    assert result.final_approval_payload.final_patch_hash == result.patch.patch_hash
    assert result.final_approval_payload.test_result.test_run_id == result.test.test_run_id
    assert result.attempt_number == 1 and len(result.attempts) == 1
    assert patcher.calls == 1 and critic.calls == 0 and len(runner.calls) == 1
    snapshot = asyncio.run(service._graph.aget_state(
        {"configurable": {"thread_id": "m6"}}
    ))
    assert snapshot.next == ("final_review",)


def test_exact_final_approval_exports_and_reject_exports_nothing(tmp_path) -> None:
    service, pack, repository, _manager, _patcher, _critic, _runner, exporter = _workflow(
        tmp_path / "approve", statuses=[SandboxStatus.PASSED]
    )
    before = (repository / "pricing.py").read_bytes()
    pending = _approve_plan(service, pack, "approve")
    completed = asyncio.run(service.resume_final_review(
        thread_id="approve",
        decision={"decision": "approve", "patch_hash": pending.patch.patch_hash, "comment": "reviewed"},
    ))
    assert completed.status is WorkflowStatus.COMPLETED
    assert completed.export.patch_hash == pending.patch.patch_hash
    assert (exporter.root / completed.export.filename).read_text(encoding="utf-8") == pending.patch.unified_diff
    assert (repository / "pricing.py").read_bytes() == before

    rejected_service, rejected_pack, *_rest = _workflow(
        tmp_path / "reject", statuses=[SandboxStatus.PASSED]
    )
    rejected_pending = _approve_plan(rejected_service, rejected_pack, "reject")
    rejected = asyncio.run(rejected_service.resume_final_review(
        thread_id="reject",
        decision={"decision": "reject", "patch_hash": rejected_pending.patch.patch_hash},
    ))
    assert rejected.status is WorkflowStatus.FINAL_REJECTED
    assert rejected.export is None


def test_wrong_final_hash_fails_closed_and_can_then_resume_exactly(tmp_path) -> None:
    service, pack, *_ = _workflow(tmp_path, statuses=[SandboxStatus.PASSED])
    pending = _approve_plan(service, pack, "hash")
    wrong = asyncio.run(service.resume_final_review(
        thread_id="hash", decision={"decision": "approve", "patch_hash": "0" * 64}
    ))
    assert wrong.status is WorkflowStatus.VALIDATION_FAILED
    assert wrong.export is None
    completed = asyncio.run(service.resume_final_review(
        thread_id="hash", decision={"decision": "approve", "patch_hash": pending.patch.patch_hash}
    ))
    assert completed.status is WorkflowStatus.COMPLETED


def test_failed_attempt_one_critic_retry_uses_fresh_baseline_and_passes(tmp_path) -> None:
    service, pack, repository, manager, patcher, critic, runner, _exporter = _workflow(
        tmp_path, statuses=[SandboxStatus.FAILED, SandboxStatus.PASSED]
    )
    result = _approve_plan(service, pack, "retry")
    assert result.status is WorkflowStatus.AWAITING_FINAL_APPROVAL
    assert result.attempt_number == 2 and len(result.attempts) == 2
    assert result.attempts[0].workspace_id != result.attempts[1].workspace_id
    assert result.attempts[0].patch_hash != result.attempts[1].patch_hash
    assert result.patch.patch_hash == result.attempts[1].patch_hash
    assert result.critic_assessment.retry_recommended is True
    assert patcher.calls == 2 and critic.calls == 1 and len(runner.calls) == 2
    first_text = (manager.repository_root_for(result.attempts[0].workspace_id) / "pricing.py").read_text()
    second_text = (manager.repository_root_for(result.attempts[1].workspace_id) / "pricing.py").read_text()
    assert "discount_percent / 200" in first_text
    assert NEW_CALCULATION in second_text and "/ 200" not in second_text
    assert OLD_CALCULATION in (repository / "pricing.py").read_text()


def test_retry_false_and_second_failure_are_terminal_without_more_generation(tmp_path) -> None:
    service, pack, _repo, _manager, patcher, critic, runner, _exporter = _workflow(
        tmp_path / "no-retry", statuses=[SandboxStatus.FAILED], retry=False
    )
    result = _approve_plan(service, pack, "no-retry")
    assert result.status is WorkflowStatus.REPAIR_FAILED
    assert patcher.calls == 1 and critic.calls == 1 and len(runner.calls) == 1

    service2, pack2, _repo2, _manager2, patcher2, critic2, runner2, _exporter2 = _workflow(
        tmp_path / "twice", statuses=[SandboxStatus.FAILED, SandboxStatus.FAILED]
    )
    result2 = _approve_plan(service2, pack2, "twice")
    assert result2.status is WorkflowStatus.REPAIR_FAILED
    assert result2.attempt_number == 2 and len(result2.attempts) == 2
    assert patcher2.calls == 2 and critic2.calls == 1 and len(runner2.calls) == 2


def test_infrastructure_failure_and_malformed_critic_never_retry(tmp_path) -> None:
    service, pack, _repo, _manager, patcher, critic, runner, _exporter = _workflow(
        tmp_path / "infra", statuses=[SandboxStatus.INFRASTRUCTURE_FAILED]
    )
    result = _approve_plan(service, pack, "infra")
    assert result.status is WorkflowStatus.TEST_INFRASTRUCTURE_FAILED
    assert patcher.calls == 1 and critic.calls == 0 and len(runner.calls) == 1

    bad_service, bad_pack, _repo2, _manager2, patcher2, critic2, runner2, _exporter2 = _workflow(
        tmp_path / "bad", statuses=[SandboxStatus.FAILED], critic_response="not-json"
    )
    bad = _approve_plan(bad_service, bad_pack, "bad")
    assert bad.status is WorkflowStatus.CRITIC_FAILED
    assert patcher2.calls == 1 and critic2.calls == 1 and len(runner2.calls) == 1


def test_retry_preserves_stale_approval_protection(tmp_path) -> None:
    service, pack, repository, _manager, patcher, critic, runner, _exporter = _workflow(
        tmp_path, statuses=[SandboxStatus.FAILED]
    )

    def change_approved_baseline(_spec) -> None:
        (repository / "pricing.py").write_text("changed after approval\n", encoding="utf-8")

    runner.callback = change_approved_baseline
    result = _approve_plan(service, pack, "stale-retry")
    assert result.status is WorkflowStatus.PATCH_FAILED
    assert result.error.error_type == "StaleApprovalError"
    assert patcher.calls == 1
    assert critic.calls == 1
    assert len(runner.calls) == 1


def test_retry_patcher_cannot_expand_the_human_approved_scope(tmp_path) -> None:
    service, pack, _repository, _manager, patcher, critic, runner, _exporter = _workflow(
        tmp_path, statuses=[SandboxStatus.FAILED]
    )
    test_evidence = next(
        item for item in pack.included_chunks if item.path == "tests/test_pricing.py"
    )
    unauthorized = PatchProposal(
        summary="Try to expand scope.",
        edits=(PatchEdit(
            path="tests/test_pricing.py",
            expected_old_text="def test_twenty_percent_discount_reduces_price():",
            replacement_text="def test_twenty_percent_discount_reduces_price():",
            evidence_chunk_ids=(test_evidence.chunk_id,),
            rationale="Model-selected scope must be rejected.",
        ),),
    )
    patcher.responses[1] = unauthorized.model_dump_json()
    result = _approve_plan(service, pack, "retry-scope")
    assert result.status is WorkflowStatus.PATCH_FAILED
    assert result.error.error_type == "PatchScopeError"
    assert result.approved_file_scope == ("pricing.py",)
    assert patcher.calls == 2 and critic.calls == 1 and len(runner.calls) == 1


def test_m6_state_is_json_friendly_and_completed_resume_does_not_repeat_work(tmp_path) -> None:
    service, pack, _repo, _manager, patcher, critic, runner, _exporter = _workflow(
        tmp_path, statuses=[SandboxStatus.PASSED]
    )
    pending = _approve_plan(service, pack, "json")
    completed = asyncio.run(service.resume_final_review(
        thread_id="json", decision={"decision": "approve", "patch_hash": pending.patch.patch_hash}
    ))
    assert json.loads(completed.model_dump_json())["status"] == "completed"
    replay = asyncio.run(service.resume_final_review(
        thread_id="json", decision={"decision": "approve", "patch_hash": pending.patch.patch_hash}
    ))
    assert replay.status is WorkflowStatus.VALIDATION_FAILED
    assert patcher.calls == 1 and critic.calls == 0 and len(runner.calls) == 1


def test_final_interrupt_survives_service_restart_without_rerunning_stages(tmp_path) -> None:
    (_unused, pack, repository, manager, patch_provider, critic_provider, runner, exporter) = _workflow(
        tmp_path, statuses=[SandboxStatus.PASSED]
    )
    _pack, plan, _proposal = patch_inputs(repository)
    planner_provider = FakeInferenceProvider(plan.model_dump_json())
    patch_service = ApprovedPatchService(
        patcher=StructuredPatcher(patch_provider), workspace_manager=manager
    )
    test_service = ApprovedPatchTestService(
        workspace_manager=manager,
        snapshot_manager=DisposableTestSnapshotManager(
            workspace_manager=manager,
            snapshot_root=(tmp_path / "restart-executions").resolve(),
        ),
        runner=runner,
        result_store=SandboxResultStore((tmp_path / "restart-tests").resolve()),
    )
    critic_service = CriticService(
        StructuredCritic(critic_provider),
        CriticAssessmentStore((tmp_path / "restart-critics").resolve()),
    )
    checkpoint = (tmp_path / "state" / "workflow.sqlite3").resolve()

    async def scenario():
        async with open_sqlite_plan_review_service(
            planner=StructuredPlanner(planner_provider), checkpoint_path=checkpoint,
            patch_service=patch_service, test_service=test_service,
            test_request=SandboxRequest(), critic_service=critic_service,
            patch_exporter=exporter,
        ) as first:
            pending = await first.start_plan_review(thread_id="restart", context_pack=pack)
            waiting = await first.resume_plan_review(
                thread_id="restart",
                decision={"decision": "approve", "plan_hash": pending.plan_hash},
            )
        async with open_sqlite_plan_review_service(
            planner=StructuredPlanner(planner_provider), checkpoint_path=checkpoint,
            patch_service=patch_service, test_service=test_service,
            test_request=SandboxRequest(), critic_service=critic_service,
            patch_exporter=exporter,
        ) as resumed:
            completed = await resumed.resume_final_review(
                thread_id="restart",
                decision={"decision": "approve", "patch_hash": waiting.patch.patch_hash},
            )
        return waiting, completed

    waiting, completed = asyncio.run(scenario())
    assert waiting.status is WorkflowStatus.AWAITING_FINAL_APPROVAL
    assert completed.status is WorkflowStatus.COMPLETED
    assert planner_provider.calls == 1
    assert patch_provider.calls == 1
    assert critic_provider.calls == 0
    assert len(runner.calls) == 1


def test_final_export_rechecks_workspace_and_fails_closed_on_tampering(tmp_path) -> None:
    service, pack, _repository, manager, _patcher, _critic, _runner, _exporter = _workflow(
        tmp_path, statuses=[SandboxStatus.PASSED]
    )
    pending = _approve_plan(service, pack, "tamper")
    target = manager.repository_root_for(pending.patch.workspace_id) / "pricing.py"
    target.write_text("tampered\n", encoding="utf-8")
    result = asyncio.run(service.resume_final_review(
        thread_id="tamper",
        decision={"decision": "approve", "patch_hash": pending.patch.patch_hash},
    ))
    assert result.status is WorkflowStatus.EXPORT_FAILED
    assert result.export is None


def test_independent_m6_threads_keep_workspaces_and_test_evidence_isolated(tmp_path) -> None:
    service, pack, _repository, _manager, patcher, critic, runner, _exporter = _workflow(
        tmp_path, statuses=[SandboxStatus.PASSED, SandboxStatus.PASSED]
    )
    first = _approve_plan(service, pack, "first")
    second = _approve_plan(service, pack, "second")
    assert first.patch.workspace_id != second.patch.workspace_id
    assert first.test.test_run_id != second.test.test_run_id
    assert first.patch.patch_hash == second.patch.patch_hash
    assert patcher.calls == 2 and critic.calls == 0 and len(runner.calls) == 2
