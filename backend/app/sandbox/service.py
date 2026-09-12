"""M5 authority, integrity, disposable snapshot, and replay boundary."""

from __future__ import annotations

from hashlib import sha256
import json

from app.patching import PatchArtifact, PatchConflictError, WorkspaceManager
from app.sandbox.errors import (
    TestConfigurationError,
    TestResultConflictError,
    TestRunnerError,
    TestSnapshotError,
    TestWorkspaceIntegrityError,
)
from app.sandbox.runner import TestRunSpec, TestRunner
from app.sandbox.schemas import TestRunRequest, TestRunResult, TestStatus
from app.sandbox.selectors import validate_pytest_selectors
from app.sandbox.store import TestResultStore
from app.sandbox.workspace import DisposableTestSnapshotManager


class ApprovedPatchTestService:
    """Test one exact patch artifact without exposing Docker or filesystem paths."""

    def __init__(
        self,
        *,
        workspace_manager: WorkspaceManager,
        snapshot_manager: DisposableTestSnapshotManager,
        runner: TestRunner,
        result_store: TestResultStore,
    ) -> None:
        if any(
            result_store.root == forbidden
            or result_store.root.is_relative_to(forbidden)
            for forbidden in (
                workspace_manager.canonical_repository,
                workspace_manager.workspace_root,
            )
        ):
            raise TestConfigurationError(
                "test result root must be outside source and durable workspaces"
            )
        result_store.ensure_root()
        self._workspaces = workspace_manager
        self._snapshots = snapshot_manager
        self._runner = runner
        self._results = result_store

    async def run_tests(
        self,
        *,
        thread_id: str,
        workflow_status: str,
        approved_plan_hash: str,
        changed_files: tuple[str, ...],
        patch: PatchArtifact,
        request: TestRunRequest,
    ) -> TestRunResult:
        test_run_id = compute_test_request_hash(
            thread_id=thread_id,
            patch=patch,
            request=request,
            runner=self._runner,
        )
        validated_selectors: tuple[str, ...] = ()
        try:
            _validate_test_authority(
                workflow_status=workflow_status,
                approved_plan_hash=approved_plan_hash,
                changed_files=changed_files,
                patch=patch,
            )
            expected_hashes = self._verify_workspace(patch)
            durable_root = self._workspaces.repository_root_for(patch.workspace_id)
            validated_selectors = validate_pytest_selectors(
                request.selectors,
                repository_root=durable_root,
            )
            cached = self._results.load(test_run_id)
            if cached is not None:
                _validate_cached_result(
                    cached,
                    patch=patch,
                    request=request,
                    validated_selectors=validated_selectors,
                    runner=self._runner,
                )
                return cached

            with self._snapshots.create(
                artifact=patch,
                expected_hashes=expected_hashes,
            ) as snapshot:
                snapshot_selectors = validate_pytest_selectors(
                    request.selectors,
                    repository_root=snapshot.repository_root,
                )
                result = await self._runner.run(
                    TestRunSpec(
                        test_run_id=test_run_id,
                        patch=patch,
                        mode=request.mode,
                        validated_selectors=snapshot_selectors,
                        execution_repository=snapshot.repository_root,
                    )
                )
            self._verify_workspace(patch)
            self._results.save(result)
            return result
        except (
            TestConfigurationError,
            TestResultConflictError,
            TestSnapshotError,
            TestWorkspaceIntegrityError,
        ) as exc:
            return _infrastructure_result(
                test_run_id=test_run_id,
                patch=patch,
                request=request,
                validated_selectors=validated_selectors,
                runner=self._runner,
                error=exc,
            )

    def _verify_workspace(self, patch: PatchArtifact) -> dict[str, str]:
        try:
            return self._workspaces.verify_patch_artifact(patch)
        except PatchConflictError as exc:
            raise TestWorkspaceIntegrityError(
                "M4 workspace no longer matches the exact patch artifact"
            ) from exc


def compute_test_request_hash(
    *,
    thread_id: str,
    patch: PatchArtifact,
    request: TestRunRequest,
    runner: TestRunner,
) -> str:
    if not thread_id or thread_id != thread_id.strip():
        raise TestConfigurationError("thread ID is invalid for test execution")
    payload = {
        "thread_id": thread_id,
        "workspace_id": patch.workspace_id,
        "patch_hash": patch.patch_hash,
        "mode": request.mode.value,
        "selectors": list(request.selectors),
        "image_reference": runner.image_reference,
        "resource_policy": runner.resource_policy.model_dump(mode="json"),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _validate_test_authority(
    *,
    workflow_status: str,
    approved_plan_hash: str,
    changed_files: tuple[str, ...],
    patch: PatchArtifact,
) -> None:
    if workflow_status != "patch_ready":
        raise TestWorkspaceIntegrityError("workflow status does not authorize testing")
    if patch.source_plan_hash != approved_plan_hash:
        raise TestWorkspaceIntegrityError("patch is not bound to the approved plan hash")
    if changed_files != patch.changed_files:
        raise TestWorkspaceIntegrityError("workflow changed-file scope conflicts")
    if not patch.patch_hash:
        raise TestWorkspaceIntegrityError("patch identity is missing")


def _validate_cached_result(
    result: TestRunResult,
    *,
    patch: PatchArtifact,
    request: TestRunRequest,
    validated_selectors: tuple[str, ...],
    runner: TestRunner,
) -> None:
    if (
        result.patch_hash != patch.patch_hash
        or result.workspace_id != patch.workspace_id
        or result.mode is not request.mode
        or result.validated_selectors != validated_selectors
        or result.image_reference != runner.image_reference
        or result.resource_policy != runner.resource_policy
    ):
        raise TestResultConflictError("stored test evidence does not match request")


def _infrastructure_result(
    *,
    test_run_id: str,
    patch: PatchArtifact,
    request: TestRunRequest,
    validated_selectors: tuple[str, ...],
    runner: TestRunner,
    error: TestRunnerError,
) -> TestRunResult:
    return TestRunResult(
        test_run_id=test_run_id,
        patch_hash=patch.patch_hash,
        workspace_id=patch.workspace_id,
        mode=request.mode,
        validated_selectors=validated_selectors,
        status=TestStatus.INFRASTRUCTURE_FAILED,
        exit_code=None,
        duration_ms=0,
        stdout="",
        stderr="",
        output_truncated=False,
        image_reference=runner.image_reference,
        image_id=None,
        resource_policy=runner.resource_policy,
        failure_classification=_failure_classification(error),
        failure_message=str(error),
    )


def _failure_classification(error: TestRunnerError) -> str:
    if isinstance(error, TestWorkspaceIntegrityError):
        return "workspace_integrity_error"
    if isinstance(error, TestConfigurationError):
        return "test_configuration_error"
    if isinstance(error, TestSnapshotError):
        return "test_snapshot_error"
    return "test_result_conflict"


__all__ = ["ApprovedPatchTestService", "compute_test_request_hash"]
