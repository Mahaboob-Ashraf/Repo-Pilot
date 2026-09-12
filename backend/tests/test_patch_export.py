"""Exact final-approval and patch-export safety tests."""

from __future__ import annotations

import asyncio
from hashlib import sha256

import pytest

from app.exporting import (
    FinalApprovalError,
    FinalReviewDecision,
    PatchExportConflictError,
    PatchExportError,
    PatchExporter,
)
from app.sandbox import TestMode as SandboxMode
from app.sandbox import TestRunResult as SandboxResult
from app.sandbox import TestStatus as SandboxStatus
from tests.sandbox_fakes import make_patched_workspace


def _passing(artifact) -> SandboxResult:
    from app.sandbox import TestResourcePolicy

    return SandboxResult(
        test_run_id="b" * 64, patch_hash=artifact.patch_hash,
        workspace_id=artifact.workspace_id, mode=SandboxMode.FULL,
        validated_selectors=(), status=SandboxStatus.PASSED, exit_code=0,
        duration_ms=1, stdout="ok", stderr="", output_truncated=False,
        image_reference="repopilot-python-test:3.11-pytest9",
        image_id="sha256:test", resource_policy=TestResourcePolicy(),
    )


def test_export_requires_exact_final_approval_and_successful_test(tmp_path) -> None:
    _repo, _pack, plan, patch, manager, _service = make_patched_workspace(tmp_path)
    exporter = PatchExporter(export_root=(tmp_path / "exports").resolve(), workspace_manager=manager)
    decision = FinalReviewDecision(decision="approve", patch_hash=patch.patch_hash)
    with pytest.raises(FinalApprovalError):
        exporter.export(
            workflow_status="awaiting_final_approval", decision=decision,
            approved_plan_hash=patch.source_plan_hash, attempt_number=1,
            patch=patch, test_result=_passing(patch),
        )
    with pytest.raises(FinalApprovalError):
        exporter.export(
            workflow_status="final_approved",
            decision=decision.model_copy(update={"patch_hash": "c" * 64}),
            approved_plan_hash=patch.source_plan_hash, attempt_number=1,
            patch=patch, test_result=_passing(patch),
        )


def test_export_is_exact_hash_verified_and_idempotent(tmp_path) -> None:
    repository, _pack, _plan, patch, manager, _service = make_patched_workspace(tmp_path)
    source_before = (repository / "pricing.py").read_bytes()
    exporter = PatchExporter(export_root=(tmp_path / "exports").resolve(), workspace_manager=manager)
    kwargs = dict(
        workflow_status="final_approved",
        decision=FinalReviewDecision(decision="approve", patch_hash=patch.patch_hash, comment="ship"),
        approved_plan_hash=patch.source_plan_hash, attempt_number=1,
        patch=patch, test_result=_passing(patch),
    )
    first = exporter.export(**kwargs)
    second = exporter.export(**kwargs)
    exported = exporter.root / first.filename
    assert first == second
    assert exported.read_text(encoding="utf-8") == patch.unified_diff
    assert sha256(exported.read_bytes()).hexdigest() == patch.patch_hash
    assert not exporter.root.is_relative_to(repository)
    assert (repository / "pricing.py").read_bytes() == source_before


def test_conflicting_existing_export_is_never_overwritten(tmp_path) -> None:
    _repository, _pack, _plan, patch, manager, _service = make_patched_workspace(tmp_path)
    exporter = PatchExporter(export_root=(tmp_path / "exports").resolve(), workspace_manager=manager)
    target = exporter.root / f"{patch.patch_hash}.patch"
    target.write_bytes(b"conflict")
    with pytest.raises(PatchExportConflictError):
        exporter.export(
            workflow_status="final_approved",
            decision=FinalReviewDecision(decision="approve", patch_hash=patch.patch_hash),
            approved_plan_hash=patch.source_plan_hash, attempt_number=1,
            patch=patch, test_result=_passing(patch),
        )
    assert target.read_bytes() == b"conflict"


def test_export_root_inside_repository_is_rejected(tmp_path) -> None:
    repository, _pack, _plan, _patch, manager, _service = make_patched_workspace(tmp_path)
    with pytest.raises(PatchExportError, match="outside"):
        PatchExporter(export_root=repository / "exports", workspace_manager=manager)
