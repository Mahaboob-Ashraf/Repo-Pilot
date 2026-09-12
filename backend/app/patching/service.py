"""Approved-plan binding, deterministic validation, and atomic patch application."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
import difflib
from hashlib import sha256
from pathlib import Path

from app.patching.errors import (
    PatchApplicationError,
    PatchConflictError,
    PatchError,
    PatchScopeError,
    PatchValidationError,
    StaleApprovalError,
)
from app.patching.patcher import StructuredPatcher
from app.patching.schemas import PatchArtifact, PatchEdit, PatchProposal
from app.patching.workspace import WorkspaceManager, validate_repository_relative_path
from app.planning import (
    PlanningContextSnapshot,
    PlanningEvidence,
    RepairPlan,
    repair_plan_hash,
    validate_plan_grounding,
)


@dataclass(frozen=True, slots=True)
class _ValidatedEdit:
    edit: PatchEdit
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _FileChange:
    path: str
    target: Path
    original_bytes: bytes
    patched_bytes: bytes
    original_text: str
    patched_text: str


class ApprovedPatchService:
    """Turn one exact approved plan into one durable isolated patch artifact."""

    def __init__(
        self,
        *,
        patcher: StructuredPatcher,
        workspace_manager: WorkspaceManager,
        file_writer: Callable[[Path, bytes], None] | None = None,
    ) -> None:
        self._patcher = patcher
        self._workspaces = workspace_manager
        self._file_writer = file_writer or _write_bytes

    async def prepare_patch(
        self,
        *,
        thread_id: str,
        workflow_status: str,
        approval_plan_hash: str,
        approved_plan: RepairPlan,
        approved_plan_hash: str,
        approved_files: tuple[str, ...],
        context: PlanningContextSnapshot,
    ) -> PatchArtifact:
        _validate_authority(
            workflow_status=workflow_status,
            approval_plan_hash=approval_plan_hash,
            approved_plan=approved_plan,
            approved_plan_hash=approved_plan_hash,
            approved_files=approved_files,
            context=context,
        )
        _validate_evidence_freshness(
            self._workspaces.canonical_repository,
            context=context,
            approved_files=approved_files,
        )

        workspace_id = self._workspaces.workspace_id_for(
            thread_id=thread_id,
            approved_plan_hash=approved_plan_hash,
        )
        snapshot = self._workspaces.prepare(workspace_id)
        existing = self._workspaces.load_patch_artifact(
            workspace_id=workspace_id,
            approved_plan_hash=approved_plan_hash,
        )
        if existing is not None:
            return existing

        _validate_evidence_freshness(
            snapshot.repository_root,
            context=context,
            approved_files=approved_files,
        )
        proposal = await self._patcher.create_patch(
            context=context,
            approved_plan=approved_plan,
            approved_plan_hash=approved_plan_hash,
            approved_files=approved_files,
        )

        # Close the approval-to-application race against both source and snapshot.
        _validate_evidence_freshness(
            self._workspaces.canonical_repository,
            context=context,
            approved_files=approved_files,
        )
        _validate_evidence_freshness(
            snapshot.repository_root,
            context=context,
            approved_files=approved_files,
        )
        changes = _validate_complete_proposal(
            proposal,
            workspace_id=workspace_id,
            approved_files=approved_files,
            context=context,
            workspaces=self._workspaces,
        )
        unified_diff = canonical_unified_diff(changes)
        artifact = PatchArtifact(
            workspace_id=workspace_id,
            source_plan_hash=approved_plan_hash,
            changed_files=tuple(change.path for change in changes),
            unified_diff=unified_diff,
            patch_hash=canonical_patch_hash(unified_diff),
        )
        self._apply_transaction(artifact=artifact, changes=changes)
        return artifact

    def _apply_transaction(
        self,
        *,
        artifact: PatchArtifact,
        changes: tuple[_FileChange, ...],
    ) -> None:
        originals = {change.target: change.original_bytes for change in changes}
        try:
            for change in changes:
                self._file_writer(change.target, change.patched_bytes)
            self._workspaces.save_patch_artifact(
                artifact=artifact,
                patched_file_hashes={
                    change.path: sha256(change.patched_bytes).hexdigest()
                    for change in changes
                },
            )
        except Exception as exc:
            rollback_errors: list[OSError] = []
            for target, original in originals.items():
                try:
                    _write_bytes(target, original)
                except OSError as rollback_exc:
                    rollback_errors.append(rollback_exc)
            try:
                self._workspaces.remove_patch_artifact(artifact.workspace_id)
            except PatchError as rollback_exc:
                rollback_errors.append(OSError(str(rollback_exc)))
            if rollback_errors:
                raise PatchApplicationError(
                    "workspace patch application failed and rollback was incomplete"
                ) from rollback_errors[0]
            if isinstance(exc, PatchConflictError):
                raise
            raise PatchApplicationError(
                "workspace patch application failed and was rolled back"
            ) from exc


def _validate_authority(
    *,
    workflow_status: str,
    approval_plan_hash: str,
    approved_plan: RepairPlan,
    approved_plan_hash: str,
    approved_files: tuple[str, ...],
    context: PlanningContextSnapshot,
) -> None:
    if workflow_status != "approved_for_patch":
        raise PatchScopeError("workflow status does not authorize patching")
    if approval_plan_hash != approved_plan_hash:
        raise PatchScopeError("approval hash does not match the planned patch")
    if repair_plan_hash(approved_plan) != approved_plan_hash:
        raise StaleApprovalError("approved plan content does not match its hash")
    if approved_files != approved_plan.proposed_files:
        raise PatchScopeError("approved file scope does not match the approved plan")
    if len(approved_files) != len(set(approved_files)):
        raise PatchScopeError("approved file scope contains duplicates")
    validate_plan_grounding(approved_plan, context)


def _validate_evidence_freshness(
    repository_root: Path,
    *,
    context: PlanningContextSnapshot,
    approved_files: tuple[str, ...],
) -> None:
    approved = set(approved_files)
    evidence_by_path: dict[str, list[PlanningEvidence]] = defaultdict(list)
    for evidence in context.evidence:
        if evidence.path in approved:
            evidence_by_path[evidence.path].append(evidence)
    if set(evidence_by_path) != approved:
        raise StaleApprovalError("approved scope lacks evidence fingerprints")

    for path in approved_files:
        text = _read_utf8_file(repository_root, path, stale=True)[1]
        for evidence in evidence_by_path[path]:
            _evidence_range(text, evidence)


def _validate_complete_proposal(
    proposal: PatchProposal,
    *,
    workspace_id: str,
    approved_files: tuple[str, ...],
    context: PlanningContextSnapshot,
    workspaces: WorkspaceManager,
) -> tuple[_FileChange, ...]:
    approved = set(approved_files)
    evidence_by_id = {item.chunk_id: item for item in context.evidence}
    edits_by_path: dict[str, list[_ValidatedEdit]] = defaultdict(list)
    originals: dict[str, tuple[Path, bytes, str]] = {}

    for edit in proposal.edits:
        validate_repository_relative_path(edit.path)
        if edit.path not in approved:
            raise PatchScopeError("patch proposal contains an unapproved file")
        if "\x00" in edit.expected_old_text or "\x00" in edit.replacement_text:
            raise PatchValidationError("patch edits must contain UTF-8 text, not NUL data")
        if edit.expected_old_text == edit.replacement_text:
            raise PatchValidationError("patch edit must change source text")

        cited: list[PlanningEvidence] = []
        for chunk_id in edit.evidence_chunk_ids:
            evidence = evidence_by_id.get(chunk_id)
            if evidence is None:
                raise PatchValidationError(
                    "patch edit cites evidence outside the approved ContextPack"
                )
            cited.append(evidence)
        same_file_evidence = tuple(item for item in cited if item.path == edit.path)
        if not same_file_evidence:
            raise PatchValidationError(
                "patch edit lacks a same-file ContextPack citation"
            )

        if edit.path not in originals:
            target = workspaces.resolve_existing_file(workspace_id, edit.path)
            data, text = _read_utf8_file(target.parent, target.name, stale=False)
            originals[edit.path] = (target, data, text)
        _target, _data, text = originals[edit.path]
        matches = _exact_match_ranges(text, edit.expected_old_text)
        if not matches:
            raise PatchValidationError("expected_old_text was not found exactly")
        if len(matches) != 1:
            raise PatchValidationError("expected_old_text matched ambiguously")
        start, end = matches[0]
        if not any(
            _range_contains(
                _evidence_range(text, evidence),
                (start, end),
            )
            for evidence in same_file_evidence
        ):
            raise PatchValidationError(
                "expected_old_text is outside its cited same-file evidence"
            )
        edits_by_path[edit.path].append(
            _ValidatedEdit(edit=edit, start=start, end=end)
        )

    changes: list[_FileChange] = []
    for path in sorted(edits_by_path):
        target, original_bytes, original_text = originals[path]
        edits = sorted(edits_by_path[path], key=lambda item: (item.start, item.end))
        for previous, current in zip(edits, edits[1:], strict=False):
            if current.start < previous.end:
                raise PatchValidationError("patch proposal contains overlapping edits")

        patched_text = original_text
        for validated in reversed(edits):
            patched_text = (
                patched_text[: validated.start]
                + validated.edit.replacement_text
                + patched_text[validated.end :]
            )
        patched_bytes = patched_text.encode("utf-8")
        if patched_bytes == original_bytes:
            raise PatchValidationError("patch proposal produces no file change")
        changes.append(
            _FileChange(
                path=path,
                target=target,
                original_bytes=original_bytes,
                patched_bytes=patched_bytes,
                original_text=original_text,
                patched_text=patched_text,
            )
        )
    if not changes:
        raise PatchValidationError("patch proposal contains no applicable edits")
    return tuple(changes)


def canonical_unified_diff(changes: Iterable[_FileChange]) -> str:
    """Generate machine-path-free canonical UTF-8 unified diff text."""

    output: list[str] = []
    for change in sorted(changes, key=lambda item: item.path):
        raw_lines = difflib.unified_diff(
            change.original_text.splitlines(keepends=True),
            change.patched_text.splitlines(keepends=True),
            fromfile=f"a/{change.path}",
            tofile=f"b/{change.path}",
            lineterm="\n",
        )
        for line in raw_lines:
            if line.endswith("\r\n"):
                output.append(line[:-2] + "\n")
            elif line.endswith("\r"):
                output.append(line[:-1] + "\n")
            elif line.endswith("\n"):
                output.append(line)
            else:
                output.append(line + "\n")
                if line.startswith((" ", "+", "-")):
                    output.append("\\ No newline at end of file\n")
    diff = "".join(output)
    if not diff:
        raise PatchValidationError("patch proposal produced an empty unified diff")
    return diff


def canonical_patch_hash(unified_diff: str) -> str:
    if not isinstance(unified_diff, str) or not unified_diff:
        raise PatchValidationError("canonical unified diff must not be empty")
    return sha256(unified_diff.encode("utf-8")).hexdigest()


def _read_utf8_file(
    root: Path,
    path: str,
    *,
    stale: bool,
) -> tuple[bytes, str]:
    try:
        relative = validate_repository_relative_path(path)
        candidate = root.joinpath(*relative.parts)
        if candidate.is_symlink():
            raise OSError("symlink target")
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve())
        if not resolved.is_file():
            raise OSError("not a regular file")
        data = resolved.read_bytes()
        if b"\x00" in data:
            raise UnicodeError("NUL data")
        text = data.decode("utf-8")
        return data, text
    except (OSError, UnicodeError, ValueError) as exc:
        if stale:
            raise StaleApprovalError(
                "approved evidence file is unavailable or not unchanged UTF-8 text"
            ) from exc
        raise PatchValidationError(
            "patch target must be an existing UTF-8 regular text file"
        ) from exc


def _evidence_range(
    text: str,
    evidence: PlanningEvidence,
) -> tuple[int, int]:
    lines = text.splitlines(keepends=True)
    if (
        evidence.start_line < 1
        or evidence.end_line < evidence.start_line
        or evidence.end_line > len(lines)
        or evidence.content_hash is None
        or evidence.source_text is None
    ):
        raise StaleApprovalError("approved evidence line range is no longer valid")
    if sha256(evidence.source_text.encode("utf-8")).hexdigest() != evidence.content_hash:
        raise StaleApprovalError("approved evidence fingerprint is inconsistent")
    start = sum(len(line) for line in lines[: evidence.start_line - 1])
    end = start + len(evidence.source_text)
    if text[start:end] != evidence.source_text:
        raise StaleApprovalError(
            "approved evidence no longer matches repository content"
        )
    observed_end_line = evidence.start_line + evidence.source_text.count("\n")
    if observed_end_line != evidence.end_line:
        raise StaleApprovalError("approved evidence line range is inconsistent")
    return start, end


def _exact_match_ranges(text: str, needle: str) -> tuple[tuple[int, int], ...]:
    matches: list[tuple[int, int]] = []
    offset = 0
    while True:
        start = text.find(needle, offset)
        if start < 0:
            return tuple(matches)
        matches.append((start, start + len(needle)))
        offset = start + 1


def _range_contains(container: tuple[int, int], item: tuple[int, int]) -> bool:
    return container[0] <= item[0] and item[1] <= container[1]


def _write_bytes(path: Path, data: bytes) -> None:
    path.write_bytes(data)


__all__ = [
    "ApprovedPatchService",
    "canonical_patch_hash",
    "canonical_unified_diff",
]
