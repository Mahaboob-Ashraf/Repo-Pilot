"""Exact, hash-bound export of RepoPilot's canonical unified diff."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import tempfile

from app.exporting.errors import (
    FinalApprovalError,
    PatchExportConflictError,
    PatchExportError,
)
from app.exporting.schemas import FinalReviewDecision, PatchExportArtifact
from app.patching import PatchArtifact, PatchConflictError, WorkspaceManager
from app.sandbox import TestRunResult, TestStatus


class PatchExporter:
    """Persist an approved exact canonical diff outside the source repository."""

    def __init__(
        self,
        *,
        export_root: str | Path,
        workspace_manager: WorkspaceManager,
    ) -> None:
        root = Path(export_root).expanduser()
        if not root.is_absolute():
            raise PatchExportError("patch export root must be absolute")
        resolved = root.resolve()
        source = workspace_manager.canonical_repository
        if resolved == source or resolved.is_relative_to(source):
            raise PatchExportError("patch export root must be outside the repository")
        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PatchExportError("patch export root could not be created") from exc
        self._root = resolved
        self._workspaces = workspace_manager

    @property
    def root(self) -> Path:
        return self._root

    def export(
        self,
        *,
        workflow_status: str,
        decision: FinalReviewDecision,
        approved_plan_hash: str,
        attempt_number: int,
        patch: PatchArtifact,
        test_result: TestRunResult,
    ) -> PatchExportArtifact:
        _validate_export_authority(
            workflow_status=workflow_status,
            decision=decision,
            approved_plan_hash=approved_plan_hash,
            attempt_number=attempt_number,
            patch=patch,
            test_result=test_result,
        )
        try:
            self._workspaces.verify_patch_artifact(patch)
        except PatchConflictError as exc:
            raise PatchExportError(
                "final patch workspace no longer matches its approved artifact"
            ) from exc

        diff_bytes = patch.unified_diff.encode("utf-8")
        if sha256(diff_bytes).hexdigest() != patch.patch_hash:
            raise PatchExportError("canonical diff does not match approved patch hash")
        artifact = PatchExportArtifact(
            artifact_id=patch.patch_hash,
            filename=f"{patch.patch_hash}.patch",
            patch_hash=patch.patch_hash,
            approved_plan_hash=approved_plan_hash,
            attempt_number=attempt_number,
            changed_files=patch.changed_files,
            test_run_id=test_result.test_run_id,
        )
        destination = self._safe_path(artifact.filename)
        _write_exact_idempotent(destination, diff_bytes)
        exported_bytes = _read_export(destination)
        if exported_bytes != diff_bytes:
            raise PatchExportError("exported patch verification failed")
        if sha256(exported_bytes).hexdigest() != patch.patch_hash:
            raise PatchExportError("exported patch hash verification failed")

        return artifact

    def _safe_path(self, filename: str) -> Path:
        destination = (self._root / filename).resolve()
        if destination.parent != self._root:
            raise PatchExportError("patch export path escaped its configured root")
        return destination


def _validate_export_authority(
    *, workflow_status, decision, approved_plan_hash, attempt_number, patch, test_result
) -> None:
    if workflow_status != "final_approved" or decision.decision != "approve":
        raise FinalApprovalError("final human approval is required before export")
    if decision.patch_hash != patch.patch_hash:
        raise FinalApprovalError("final approval does not match the candidate patch")
    if patch.source_plan_hash != approved_plan_hash:
        raise FinalApprovalError("final patch is not bound to the approved plan")
    if attempt_number not in {1, 2}:
        raise FinalApprovalError("final patch attempt identity is invalid")
    if (
        test_result.status is not TestStatus.PASSED
        or test_result.patch_hash != patch.patch_hash
        or test_result.workspace_id != patch.workspace_id
    ):
        raise FinalApprovalError("final approval lacks matching successful test evidence")


def _write_exact_idempotent(destination: Path, data: bytes) -> None:
    if destination.exists():
        existing = _read_export(destination)
        if existing != data:
            raise PatchExportConflictError(
                "existing deterministic export contains conflicting bytes"
            )
        return
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".export-", suffix=".tmp", dir=destination.parent,
            delete=False,
        ) as handle:
            handle.write(data)
            temporary = Path(handle.name)
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if _read_export(destination) != data:
                raise PatchExportConflictError(
                    "existing deterministic export contains conflicting bytes"
                )
    except OSError as exc:
        raise PatchExportError("patch export could not be written") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_export(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PatchExportError("existing export could not be verified") from exc


__all__ = ["PatchExporter"]
