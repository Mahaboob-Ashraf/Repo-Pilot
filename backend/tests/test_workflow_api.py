"""HTTP contract tests for the M7 human review workspace."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app.dependencies import get_workflow_application
from app.exporting import FinalReviewDecision, PatchExportArtifact
from app.main import app
from app.patching import PatchArtifact
from app.planning import PlanningEvidence, RepairPlan, RepairStep, StructuredPlanner
from app.sandbox import (
    TestMode as SandboxMode,
    TestResourcePolicy as SandboxResourcePolicy,
    TestRunResult as SandboxRunResult,
    TestStatus as SandboxStatus,
)
from app.workflow import ApprovalDecision, PlanReviewResult, PlanReviewService, WorkflowStatus
from app.workflow.application import (
    WorkflowApplicationError,
    WorkflowMetadata,
    WorkflowReview,
)
from tests.planning_fakes import FakeInferenceProvider, make_context_pack, make_valid_plan


PLAN_HASH = "a" * 64
PATCH_HASH = "b" * 64
TEST_RUN_ID = "c" * 64
SECRET = "super-secret-provider-token"


def _plan() -> RepairPlan:
    return RepairPlan(
        summary="Correct discount arithmetic.",
        diagnosis="The discount rate is added instead of subtracted.",
        proposed_files=("pricing.py",),
        steps=(
            RepairStep(
                description="Subtract the rate.",
                affected_files=("pricing.py",),
                evidence_chunk_ids=("chunk-pricing",),
            ),
        ),
        suggested_tests=("tests/test_pricing.py",),
    )


def _evidence() -> tuple[PlanningEvidence, ...]:
    return (
        PlanningEvidence(
            chunk_id="chunk-pricing",
            path="pricing.py",
            qualified_symbol="apply_discount",
            chunk_type="function",
            start_line=1,
            end_line=2,
            content_hash="d" * 64,
            source_text="def apply_discount(total, rate):\n    return total * (1 + rate)",
            origin="retrieved",
            source_retrieval_rank=1,
        ),
    )


def _test_result(status: SandboxStatus = SandboxStatus.PASSED) -> SandboxRunResult:
    return SandboxRunResult(
        test_run_id=TEST_RUN_ID,
        patch_hash=PATCH_HASH,
        workspace_id="workspace-internal-only",
        mode=SandboxMode.FULL,
        validated_selectors=(),
        status=status,
        exit_code=0 if status is SandboxStatus.PASSED else 1,
        duration_ms=18,
        stdout="1 passed" if status is SandboxStatus.PASSED else "1 failed",
        stderr="",
        output_truncated=False,
        image_reference="repopilot-python-test:3.11-pytest9",
        image_id="sha256:" + "e" * 64,
        resource_policy=SandboxResourcePolicy(),
        failure_classification=None,
        failure_message=None,
    )


def _result(status: WorkflowStatus) -> PlanReviewResult:
    common = dict(
        thread_id="thread-017",
        status=status,
        issue_text="Fix discount arithmetic",
        evidence=_evidence(),
        context_status="complete",
        retrieval_mode="hybrid",
        retrieval_degraded=False,
        plan=_plan(),
        plan_hash=PLAN_HASH,
    )
    if status is WorkflowStatus.AWAITING_APPROVAL:
        return PlanReviewResult(**common)
    if status is WorkflowStatus.REJECTED:
        return PlanReviewResult(
            **common,
            approval_decision=ApprovalDecision(
                decision="reject", plan_hash=PLAN_HASH
            ),
        )
    patch = PatchArtifact(
        workspace_id="workspace-internal-only",
        source_plan_hash=PLAN_HASH,
        changed_files=("pricing.py",),
        unified_diff="--- a/pricing.py\n+++ b/pricing.py\n@@ -1 +1 @@\n-old\n+new\n",
        patch_hash=PATCH_HASH,
    )
    final = dict(
        **common,
        approved_file_scope=("pricing.py",),
        patch=patch,
        test=_test_result(),
        final_candidate_patch_hash=PATCH_HASH,
    )
    if status is WorkflowStatus.COMPLETED:
        return PlanReviewResult(
            **final,
            final_approval_decision=FinalReviewDecision(
                decision="approve", patch_hash=PATCH_HASH
            ),
            export=PatchExportArtifact(
                artifact_id=PATCH_HASH,
                filename=f"{PATCH_HASH}.patch",
                patch_hash=PATCH_HASH,
                approved_plan_hash=PLAN_HASH,
                attempt_number=1,
                changed_files=("pricing.py",),
                test_run_id=TEST_RUN_ID,
            ),
        )
    if status is WorkflowStatus.FINAL_REJECTED:
        return PlanReviewResult(
            **final,
            final_approval_decision=FinalReviewDecision(
                decision="reject", patch_hash=PATCH_HASH
            ),
        )
    return PlanReviewResult(**final)


def _review(status: WorkflowStatus) -> WorkflowReview:
    return WorkflowReview(
        metadata=WorkflowMetadata(
            thread_id="thread-017",
            repository_path=r"C:\work\toy-repo",
            issue="Fix discount arithmetic",
        ),
        result=_result(status),
    )


class RecordingWorkflowApplication:
    def __init__(self) -> None:
        self.create_calls = 0
        self.get_calls = 0
        self.plan_calls: list[ApprovalDecision] = []
        self.final_calls: list[FinalReviewDecision] = []

    async def create_workflow(self, *, repository_path, issue, thread_id=None):
        self.create_calls += 1
        if repository_path == "invalid":
            raise WorkflowApplicationError(
                "invalid_repository", "Repository path is invalid.", status_code=400
            )
        if repository_path == "explode":
            raise RuntimeError(f"traceback with {SECRET}")
        return _review(WorkflowStatus.AWAITING_APPROVAL)

    async def get_workflow(self, *, thread_id):
        self.get_calls += 1
        if thread_id == "missing":
            raise WorkflowApplicationError(
                "workflow_not_found", "Workflow was not found.", status_code=404
            )
        return _review(WorkflowStatus.AWAITING_APPROVAL)

    async def submit_plan_decision(self, *, thread_id, decision):
        self.plan_calls.append(decision)
        if decision.plan_hash != PLAN_HASH:
            raise WorkflowApplicationError(
                "stale_plan_hash", "The displayed plan hash is stale.", status_code=409
            )
        return _review(
            WorkflowStatus.REJECTED
            if decision.decision == "reject"
            else WorkflowStatus.AWAITING_FINAL_APPROVAL
        )

    async def submit_final_decision(self, *, thread_id, decision):
        self.final_calls.append(decision)
        if decision.patch_hash != PATCH_HASH:
            raise WorkflowApplicationError(
                "stale_patch_hash", "The displayed patch hash is stale.", status_code=409
            )
        return _review(
            WorkflowStatus.FINAL_REJECTED
            if decision.decision == "reject"
            else WorkflowStatus.COMPLETED
        )


def _client():
    boundary = RecordingWorkflowApplication()
    app.dependency_overrides[get_workflow_application] = lambda: boundary
    return TestClient(app), boundary


def test_start_calls_application_boundary_and_returns_first_approval_state() -> None:
    client, boundary = _client()
    try:
        response = client.post(
            "/api/workflows",
            json={"repository_path": r"C:\work\toy-repo", "issue": "Fix it"},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json()["status"] == "awaiting_approval"
    assert response.json()["plan_hash"] == PLAN_HASH
    assert boundary.create_calls == 1


def test_invalid_repository_and_empty_issue_are_rejected() -> None:
    client, _ = _client()
    try:
        invalid = client.post(
            "/api/workflows", json={"repository_path": "invalid", "issue": "Fix"}
        )
        empty = client.post(
            "/api/workflows", json={"repository_path": "repo", "issue": "   "}
        )
    finally:
        app.dependency_overrides.clear()
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "invalid_repository"
    assert empty.status_code == 422


def test_get_is_read_only_and_unknown_thread_is_404() -> None:
    client, boundary = _client()
    try:
        first = client.get("/api/workflows/thread-017")
        second = client.get("/api/workflows/thread-017")
        missing = client.get("/api/workflows/missing")
    finally:
        app.dependency_overrides.clear()
    assert first.status_code == second.status_code == 200
    assert missing.status_code == 404
    assert boundary.get_calls == 3
    assert boundary.create_calls == 0
    assert boundary.plan_calls == []
    assert boundary.final_calls == []


def test_plan_decision_requires_exact_hash_and_rejection_is_terminal() -> None:
    client, boundary = _client()
    try:
        stale = client.post(
            "/api/workflows/thread-017/plan-decision",
            json={"decision": "approve", "plan_hash": "0" * 64},
        )
        rejected = client.post(
            "/api/workflows/thread-017/plan-decision",
            json={"decision": "reject", "plan_hash": PLAN_HASH},
        )
    finally:
        app.dependency_overrides.clear()
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_plan_hash"
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["patch"] is None
    assert boundary.plan_calls[-1].plan_hash == PLAN_HASH


def test_plan_approval_can_reach_final_review_with_safe_patch_and_test_views() -> None:
    client, _ = _client()
    try:
        response = client.post(
            "/api/workflows/thread-017/plan-decision",
            json={"decision": "approve", "plan_hash": PLAN_HASH},
        )
    finally:
        app.dependency_overrides.clear()
    body = response.json()
    assert body["status"] == "awaiting_final_approval"
    assert body["patch"]["canonical_unified_diff"].startswith("--- a/pricing.py")
    assert body["test"]["tested_patch_hash"] == PATCH_HASH
    assert body["final_review"]["final_patch_hash"] == PATCH_HASH


def test_final_decision_requires_exact_hash_rejects_without_export_and_approves_export() -> None:
    client, boundary = _client()
    try:
        stale = client.post(
            "/api/workflows/thread-017/final-decision",
            json={"decision": "approve", "patch_hash": "0" * 64},
        )
        rejected = client.post(
            "/api/workflows/thread-017/final-decision",
            json={"decision": "reject", "patch_hash": PATCH_HASH},
        )
        approved = client.post(
            "/api/workflows/thread-017/final-decision",
            json={"decision": "approve", "patch_hash": PATCH_HASH},
        )
    finally:
        app.dependency_overrides.clear()
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_patch_hash"
    assert rejected.json()["status"] == "final_rejected"
    assert rejected.json()["export"] is None
    assert approved.json()["status"] == "completed"
    assert approved.json()["export"]["filename"] == f"{PATCH_HASH}.patch"
    assert boundary.final_calls[-1].patch_hash == PATCH_HASH


def test_internal_exception_does_not_expose_traceback_or_secret() -> None:
    client, _ = _client()
    try:
        response = client.post(
            "/api/workflows",
            json={"repository_path": "explode", "issue": "Fix"},
        )
    finally:
        app.dependency_overrides.clear()
    rendered = response.text
    assert response.status_code == 500
    assert "workflow_internal_error" in rendered
    assert SECRET not in rendered
    assert "traceback" not in rendered.lower()


def test_api_view_omits_runtime_and_workspace_implementation_details() -> None:
    client, _ = _client()
    try:
        response = client.post(
            "/api/workflows/thread-017/plan-decision",
            json={"decision": "approve", "plan_hash": PLAN_HASH},
        )
    finally:
        app.dependency_overrides.clear()
    rendered = response.text
    assert "workspace-internal-only" not in rendered
    assert "resource_policy" not in rendered
    assert "InferenceProvider" not in rendered
    assert "checkpoint" not in rendered


def test_service_get_reconstructs_pause_without_rerunning_planner() -> None:
    pack = make_context_pack()
    provider = FakeInferenceProvider(make_valid_plan(pack).model_dump_json())
    service = PlanReviewService(StructuredPlanner(provider), InMemorySaver())

    async def scenario():
        await service.start_plan_review(
            thread_id="read-only-get", context_pack=pack
        )
        first = await service.get_plan_review(thread_id="read-only-get")
        second = await service.get_plan_review(thread_id="read-only-get")
        missing = await service.get_plan_review(thread_id="missing")
        return first, second, missing

    first, second, missing = asyncio.run(scenario())
    assert first is not None and second is not None
    assert first.status is second.status is WorkflowStatus.AWAITING_APPROVAL
    assert missing is None
    assert provider.calls == 1
