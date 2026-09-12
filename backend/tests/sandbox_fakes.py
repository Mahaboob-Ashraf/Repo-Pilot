"""Deterministic M5 fakes; no test in this module contacts Docker."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.patching import (
    ApprovedPatchService,
    PatchArtifact,
    StructuredPatcher,
    WorkspaceManager,
)
from app.planning import PlanningContextSnapshot, repair_plan_hash
from app.sandbox import (
    ApprovedPatchTestService,
    DisposableTestSnapshotManager,
    TestMode,
    TestResourcePolicy,
    TestResultStore,
    TestRunResult,
    TestRunSpec,
    TestStatus,
)
from tests.patching_fakes import copy_toy_repository, patch_inputs
from tests.planning_fakes import FakeInferenceProvider


@dataclass
class FakeTestRunner:
    status: TestStatus = TestStatus.PASSED
    exit_code: int | None = 0
    callback: Callable[[TestRunSpec], None] | None = None
    calls: list[TestRunSpec] = field(default_factory=list)
    image_reference: str = "repopilot-python-test:3.11-pytest9"
    resource_policy: TestResourcePolicy = field(default_factory=TestResourcePolicy)

    async def run(self, spec: TestRunSpec) -> TestRunResult:
        self.calls.append(spec)
        if self.callback is not None:
            self.callback(spec)
        failure = self.status is not TestStatus.PASSED
        return TestRunResult(
            test_run_id=spec.test_run_id,
            patch_hash=spec.patch.patch_hash,
            workspace_id=spec.patch.workspace_id,
            mode=spec.mode,
            validated_selectors=spec.validated_selectors,
            status=self.status,
            exit_code=self.exit_code,
            duration_ms=7,
            stdout="fake stdout",
            stderr="fake stderr" if failure else "",
            output_truncated=False,
            image_reference=self.image_reference,
            image_id="sha256:fake-test-image",
            resource_policy=self.resource_policy,
            failure_classification=("fake_failure" if failure else None),
            failure_message=("fake test failure" if failure else None),
        )


def make_patched_workspace(tmp_path: Path, *, thread_id: str = "m5-thread"):
    repository = copy_toy_repository(tmp_path / "input")
    pack, plan, proposal = patch_inputs(repository)
    manager = WorkspaceManager(
        canonical_repository=repository,
        workspace_root=tmp_path / "workspaces",
    )
    patch_service = ApprovedPatchService(
        patcher=StructuredPatcher(FakeInferenceProvider(proposal.model_dump_json())),
        workspace_manager=manager,
    )
    plan_hash = repair_plan_hash(plan)
    artifact = asyncio.run(
        patch_service.prepare_patch(
            thread_id=thread_id,
            workflow_status="approved_for_patch",
            approval_plan_hash=plan_hash,
            approved_plan=plan,
            approved_plan_hash=plan_hash,
            approved_files=plan.proposed_files,
            context=PlanningContextSnapshot.from_context_pack(pack),
        )
    )
    return repository, pack, plan, artifact, manager, patch_service


def make_test_service(
    tmp_path: Path,
    *,
    manager: WorkspaceManager,
    runner: FakeTestRunner,
) -> ApprovedPatchTestService:
    return ApprovedPatchTestService(
        workspace_manager=manager,
        snapshot_manager=DisposableTestSnapshotManager(
            workspace_manager=manager,
            snapshot_root=(tmp_path / "executions").resolve(),
        ),
        runner=runner,
        result_store=TestResultStore((tmp_path / "test-results").resolve()),
    )


__all__ = ["FakeTestRunner", "make_patched_workspace", "make_test_service"]
