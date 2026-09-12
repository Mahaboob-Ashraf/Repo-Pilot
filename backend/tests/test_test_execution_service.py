"""M5 patch-integrity, snapshot-isolation, and replay tests."""

from __future__ import annotations

import asyncio
from hashlib import sha256
from pathlib import Path

from app.sandbox import (
    ApprovedPatchTestService,
    DisposableTestSnapshotManager,
    TestMode as Mode,
    TestResourcePolicy as ResourcePolicy,
    TestResultStore as ResultStore,
    TestRunRequest as RunRequest,
    TestStatus as Status,
    compute_test_request_hash,
)
from app.sandbox.errors import TestConfigurationError as ConfigurationError
from tests.patching_fakes import NEW_CALCULATION, OLD_CALCULATION
from tests.sandbox_fakes import (
    FakeTestRunner,
    make_patched_workspace,
    make_test_service,
)


def _run(service, *, plan, artifact, request=None, status="patch_ready", changed=None):
    return asyncio.run(
        service.run_tests(
            thread_id="m5-thread",
            workflow_status=status,
            approved_plan_hash=(
                artifact.source_plan_hash if plan is not None else "f" * 64
            ),
            changed_files=changed or artifact.changed_files,
            patch=artifact,
            request=request or RunRequest(),
        )
    )


def _hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.py"))
    }


def test_testing_requires_patch_ready_and_exact_plan_hash_scope(tmp_path) -> None:
    _repo, _pack, plan, artifact, manager, _patch_service = make_patched_workspace(
        tmp_path
    )
    runner = FakeTestRunner()
    service = make_test_service(tmp_path, manager=manager, runner=runner)

    wrong_status = _run(service, plan=plan, artifact=artifact, status="patch_failed")
    wrong_plan = asyncio.run(
        service.run_tests(
            thread_id="m5-thread",
            workflow_status="patch_ready",
            approved_plan_hash="e" * 64,
            changed_files=artifact.changed_files,
            patch=artifact,
            request=RunRequest(),
        )
    )
    wrong_scope = _run(
        service,
        plan=plan,
        artifact=artifact,
        changed=("tests/test_pricing.py",),
    )

    assert {wrong_status.status, wrong_plan.status, wrong_scope.status} == {
        Status.INFRASTRUCTURE_FAILED
    }
    assert len(runner.calls) == 0


def test_tampered_workspace_is_rejected_before_runner(tmp_path) -> None:
    _repo, _pack, plan, artifact, manager, _patch_service = make_patched_workspace(
        tmp_path
    )
    durable = manager.repository_root_for(artifact.workspace_id)
    (durable / "pricing.py").write_text("tampered\n", encoding="utf-8")
    runner = FakeTestRunner()
    service = make_test_service(tmp_path, manager=manager, runner=runner)

    result = _run(service, plan=plan, artifact=artifact)

    assert result.status is Status.INFRASTRUCTURE_FAILED
    assert result.failure_classification == "workspace_integrity_error"
    assert runner.calls == []


def test_added_workspace_file_is_tampering(tmp_path) -> None:
    _repo, _pack, plan, artifact, manager, _patch_service = make_patched_workspace(
        tmp_path
    )
    durable = manager.repository_root_for(artifact.workspace_id)
    (durable / "unexpected.py").write_text("raise SystemExit\n", encoding="utf-8")
    runner = FakeTestRunner()

    result = _run(
        make_test_service(tmp_path, manager=manager, runner=runner),
        plan=plan,
        artifact=artifact,
    )

    assert result.failure_classification == "workspace_integrity_error"
    assert runner.calls == []


def test_snapshot_is_patched_disposable_and_separate_from_durable(tmp_path) -> None:
    repository, _pack, plan, artifact, manager, _patch_service = (
        make_patched_workspace(tmp_path)
    )
    durable = manager.repository_root_for(artifact.workspace_id)
    durable_before = _hashes(durable)
    canonical_before = _hashes(repository)
    observed: dict[str, Path] = {}

    def inspect_and_contaminate(spec) -> None:
        observed["root"] = spec.execution_repository
        assert spec.execution_repository != durable
        text = (spec.execution_repository / "pricing.py").read_text(encoding="utf-8")
        assert NEW_CALCULATION in text
        (spec.execution_repository / "pricing.py").write_text(
            "execution-only contamination\n", encoding="utf-8"
        )

    runner = FakeTestRunner(callback=inspect_and_contaminate)
    service = make_test_service(tmp_path, manager=manager, runner=runner)

    result = _run(service, plan=plan, artifact=artifact)

    assert result.status is Status.PASSED
    assert not observed["root"].exists()
    assert _hashes(durable) == durable_before
    assert _hashes(repository) == canonical_before
    assert OLD_CALCULATION in (repository / "pricing.py").read_text(encoding="utf-8")


def test_targeted_selector_is_validated_in_snapshot(tmp_path) -> None:
    _repo, _pack, plan, artifact, manager, _patch_service = make_patched_workspace(
        tmp_path
    )
    runner = FakeTestRunner()
    service = make_test_service(tmp_path, manager=manager, runner=runner)
    request = RunRequest(
        mode=Mode.TARGETED,
        selectors=(
            "tests/test_pricing.py::test_twenty_percent_discount_reduces_price",
        ),
    )

    result = _run(service, plan=plan, artifact=artifact, request=request)

    assert result.status is Status.PASSED
    assert result.validated_selectors == request.selectors
    assert runner.calls[0].validated_selectors == request.selectors


def test_invalid_selector_never_creates_execution_or_calls_runner(tmp_path) -> None:
    _repo, _pack, plan, artifact, manager, _patch_service = make_patched_workspace(
        tmp_path
    )
    runner = FakeTestRunner()
    service = make_test_service(tmp_path, manager=manager, runner=runner)
    request = RunRequest(
        mode=Mode.TARGETED,
        selectors=("tests/test_pricing.py::test_ok;whoami",),
    )

    result = _run(service, plan=plan, artifact=artifact, request=request)

    assert result.status is Status.INFRASTRUCTURE_FAILED
    assert result.failure_classification == "test_configuration_error"
    assert runner.calls == []
    assert not tuple((tmp_path / "executions").glob("execution-*"))


def test_identical_completed_request_is_replayed_without_runner(tmp_path) -> None:
    _repo, _pack, plan, artifact, manager, _patch_service = make_patched_workspace(
        tmp_path
    )
    runner = FakeTestRunner()
    service = make_test_service(tmp_path, manager=manager, runner=runner)

    first = _run(service, plan=plan, artifact=artifact)
    second = _run(service, plan=plan, artifact=artifact)

    assert first == second
    assert len(runner.calls) == 1


def test_completed_result_survives_service_reconstruction(tmp_path) -> None:
    _repo, _pack, plan, artifact, manager, _patch_service = make_patched_workspace(
        tmp_path
    )
    runner = FakeTestRunner()
    first_service = make_test_service(tmp_path, manager=manager, runner=runner)
    first = _run(first_service, plan=plan, artifact=artifact)
    second_service = make_test_service(tmp_path, manager=manager, runner=runner)

    second = _run(second_service, plan=plan, artifact=artifact)

    assert first == second
    assert len(runner.calls) == 1


def test_patch_request_and_policy_identity_change_test_run_id(tmp_path) -> None:
    _repo, _pack, _plan, artifact, _manager, _patch_service = make_patched_workspace(
        tmp_path
    )
    runner = FakeTestRunner()
    base = compute_test_request_hash(
        thread_id="thread-a",
        patch=artifact,
        request=RunRequest(),
        runner=runner,
    )
    changed_patch = artifact.model_copy(update={"patch_hash": "1" * 64})
    changed_patch_id = compute_test_request_hash(
        thread_id="thread-a",
        patch=changed_patch,
        request=RunRequest(),
        runner=runner,
    )
    different_thread = compute_test_request_hash(
        thread_id="thread-b",
        patch=artifact,
        request=RunRequest(),
        runner=runner,
    )
    policy_runner = FakeTestRunner(
        resource_policy=ResourcePolicy(memory_bytes=268_435_456)
    )
    different_policy = compute_test_request_hash(
        thread_id="thread-a",
        patch=artifact,
        request=RunRequest(),
        runner=policy_runner,
    )

    assert len({base, changed_patch_id, different_thread, different_policy}) == 4


def test_full_workspace_integrity_accepts_unchanged_completed_artifact(tmp_path) -> None:
    _repo, _pack, _plan, artifact, manager, _patch_service = make_patched_workspace(
        tmp_path
    )

    hashes = manager.verify_patch_artifact(artifact)

    assert set(hashes) == {"pricing.py", "tests/test_pricing.py"}


def test_result_store_root_is_separate_and_json_durable(tmp_path) -> None:
    _repo, _pack, plan, artifact, manager, _patch_service = make_patched_workspace(
        tmp_path
    )
    runner = FakeTestRunner()
    snapshot_manager = DisposableTestSnapshotManager(
        workspace_manager=manager,
        snapshot_root=(tmp_path / "execution-root").resolve(),
    )
    store = ResultStore((tmp_path / "evidence-root").resolve())
    service = ApprovedPatchTestService(
        workspace_manager=manager,
        snapshot_manager=snapshot_manager,
        runner=runner,
        result_store=store,
    )

    result = _run(service, plan=plan, artifact=artifact)

    stored = store.load(result.test_run_id)
    assert stored == result
    assert list(store.root.glob("test-*.json"))


def test_result_store_inside_canonical_repository_is_rejected(tmp_path) -> None:
    repository, _pack, _plan, _artifact, manager, _patch_service = (
        make_patched_workspace(tmp_path)
    )
    runner = FakeTestRunner()

    try:
        ApprovedPatchTestService(
            workspace_manager=manager,
            snapshot_manager=DisposableTestSnapshotManager(
                workspace_manager=manager,
                snapshot_root=(tmp_path / "execution-root").resolve(),
            ),
            runner=runner,
            result_store=ResultStore((repository / "test-evidence").resolve()),
        )
    except ConfigurationError:
        pass
    else:
        raise AssertionError("unsafe result root was accepted")
    assert not (repository / "test-evidence").exists()
