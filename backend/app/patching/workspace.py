"""Durable isolated filesystem snapshots for approved patch application."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import tempfile
from typing import Any

from app.ingestion import EXCLUDED_DIRECTORY_NAMES
from app.patching.errors import (
    PatchApplicationError,
    PatchConflictError,
    PatchValidationError,
    WorkspaceError,
)
from app.patching.schemas import PatchArtifact


_WORKSPACE_ID_PATTERN = re.compile(r"^workspace-[0-9a-f]{64}$")
_WORKSPACE_METADATA_NAME = "workspace.json"
_PATCH_METADATA_NAME = "patch.json"
_REPOSITORY_DIRECTORY_NAME = "repository"


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    workspace_id: str
    repository_root: Path
    baseline_hashes: dict[str, str]


class WorkspaceManager:
    """Create and reopen durable snapshots outside the canonical repository."""

    def __init__(
        self,
        *,
        canonical_repository: str | Path,
        workspace_root: str | Path,
    ) -> None:
        try:
            source = Path(canonical_repository).resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise WorkspaceError("canonical repository does not exist") from exc
        if not source.is_dir():
            raise WorkspaceError("canonical repository must be a directory")

        root = Path(workspace_root).expanduser()
        if not root.is_absolute():
            raise WorkspaceError("workspace root must be an absolute path")
        resolved_root = root.resolve()
        if resolved_root == source or resolved_root.is_relative_to(source):
            raise WorkspaceError(
                "workspace root must be outside the canonical repository"
            )
        try:
            resolved_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkspaceError("workspace root could not be created") from exc

        self._canonical_repository = source
        self._workspace_root = resolved_root
        self._repository_identity = sha256(
            str(source).casefold().encode("utf-8")
        ).hexdigest()

    @property
    def canonical_repository(self) -> Path:
        return self._canonical_repository

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    def workspace_id_for(self, *, thread_id: str, approved_plan_hash: str) -> str:
        identity = (
            f"{self._repository_identity}\0{thread_id}\0{approved_plan_hash}"
        ).encode("utf-8")
        return f"workspace-{sha256(identity).hexdigest()}"

    def prepare(self, workspace_id: str) -> WorkspaceSnapshot:
        container = self._workspace_container(workspace_id)
        if container.exists():
            return self._open_existing(workspace_id, container)

        staging_path = Path(
            tempfile.mkdtemp(prefix=".repopilot-staging-", dir=self._workspace_root)
        ).resolve()
        try:
            repository_root = staging_path / _REPOSITORY_DIRECTORY_NAME
            repository_root.mkdir()
            baseline_hashes = self._copy_snapshot(repository_root)
            self._write_json(
                staging_path / _WORKSPACE_METADATA_NAME,
                {
                    "workspace_id": workspace_id,
                    "baseline_hashes": baseline_hashes,
                },
            )
            try:
                staging_path.replace(container)
            except OSError as exc:
                raise WorkspaceError("workspace snapshot could not be finalized") from exc
        finally:
            if staging_path.exists():
                self._remove_staging(staging_path)

        return WorkspaceSnapshot(
            workspace_id=workspace_id,
            repository_root=container / _REPOSITORY_DIRECTORY_NAME,
            baseline_hashes=baseline_hashes,
        )

    def load_patch_artifact(
        self,
        *,
        workspace_id: str,
        approved_plan_hash: str,
    ) -> PatchArtifact | None:
        snapshot = self.prepare(workspace_id)
        record_path = self._workspace_container(workspace_id) / _PATCH_METADATA_NAME
        if not record_path.exists():
            self._verify_unpatched_snapshot(snapshot)
            return None
        artifact, patched_hashes = self._load_patch_record(record_path)
        if artifact.source_plan_hash != approved_plan_hash:
            raise PatchConflictError(
                "workspace already contains a patch for a different approved plan"
            )
        if not isinstance(patched_hashes, dict):
            raise PatchConflictError("workspace patch record is invalid")
        for path, expected_hash in patched_hashes.items():
            if not isinstance(path, str) or not isinstance(expected_hash, str):
                raise PatchConflictError("workspace patch record is invalid")
            target = self.resolve_existing_file(workspace_id, path)
            if _hash_bytes(target.read_bytes()) != expected_hash:
                raise PatchConflictError(
                    "workspace content conflicts with its completed patch record"
                )
        return artifact

    def verify_patch_artifact(self, artifact: PatchArtifact) -> dict[str, str]:
        """Verify one exact M4 artifact and every durable workspace file byte."""

        snapshot = self.prepare(artifact.workspace_id)
        record_path = (
            self._workspace_container(artifact.workspace_id) / _PATCH_METADATA_NAME
        )
        if not record_path.exists():
            raise PatchConflictError("workspace has no completed patch record")
        recorded, patched_hashes = self._load_patch_record(record_path)
        if recorded != artifact:
            raise PatchConflictError("workspace patch record does not match artifact")
        if sha256(artifact.unified_diff.encode("utf-8")).hexdigest() != artifact.patch_hash:
            raise PatchConflictError("workspace patch hash is inconsistent")
        if (
            artifact.changed_files != tuple(sorted(set(artifact.changed_files)))
            or set(patched_hashes) != set(artifact.changed_files)
        ):
            raise PatchConflictError("workspace changed-file scope is inconsistent")

        expected_hashes = dict(snapshot.baseline_hashes)
        for path, digest in patched_hashes.items():
            try:
                validate_repository_relative_path(path)
            except PatchValidationError as exc:
                raise PatchConflictError("workspace patch record path is invalid") from exc
            if path not in expected_hashes:
                raise PatchConflictError("workspace patch record contains a new file")
            expected_hashes[path] = digest

        current_hashes = self._repository_hashes(snapshot.repository_root)
        if current_hashes != dict(sorted(expected_hashes.items())):
            raise PatchConflictError(
                "workspace content no longer matches the completed patch artifact"
            )
        return current_hashes

    def save_patch_artifact(
        self,
        *,
        artifact: PatchArtifact,
        patched_file_hashes: dict[str, str],
    ) -> None:
        record_path = (
            self._workspace_container(artifact.workspace_id) / _PATCH_METADATA_NAME
        )
        if record_path.exists():
            raise PatchConflictError("workspace patch record already exists")
        self._write_json(
            record_path,
            {
                "artifact": artifact.model_dump(mode="json"),
                "patched_file_hashes": dict(sorted(patched_file_hashes.items())),
            },
        )

    def remove_patch_artifact(self, workspace_id: str) -> None:
        record_path = self._workspace_container(workspace_id) / _PATCH_METADATA_NAME
        try:
            record_path.unlink(missing_ok=True)
        except OSError as exc:
            raise PatchApplicationError(
                "workspace patch metadata could not be rolled back"
            ) from exc

    def resolve_existing_file(self, workspace_id: str, path: str) -> Path:
        relative = validate_repository_relative_path(path)
        snapshot = self.prepare(workspace_id)
        source_candidate = self._canonical_repository.joinpath(*relative.parts)
        workspace_candidate = snapshot.repository_root.joinpath(*relative.parts)

        if source_candidate.is_symlink() or workspace_candidate.is_symlink():
            raise PatchValidationError("patch target must not be a symlink")
        try:
            resolved = workspace_candidate.resolve(strict=True)
            resolved.relative_to(snapshot.repository_root)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise PatchValidationError(
                "patch target must be an existing workspace file"
            ) from exc
        if not resolved.is_file():
            raise PatchValidationError(
                "patch target must be an existing regular file"
            )
        return resolved

    def repository_root_for(self, workspace_id: str) -> Path:
        return self.prepare(workspace_id).repository_root

    @staticmethod
    def _load_patch_record(record_path: Path) -> tuple[PatchArtifact, dict[str, str]]:
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            artifact = PatchArtifact.model_validate(record["artifact"])
            patched_hashes = record["patched_file_hashes"]
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PatchConflictError("workspace patch record is invalid") from exc
        if not isinstance(patched_hashes, dict) or any(
            not isinstance(path, str) or not isinstance(digest, str)
            for path, digest in patched_hashes.items()
        ):
            raise PatchConflictError("workspace patch record is invalid")
        return artifact, dict(patched_hashes)

    @staticmethod
    def _repository_hashes(repository_root: Path) -> dict[str, str]:
        hashes: dict[str, str] = {}
        try:
            for current, directory_names, file_names in os.walk(
                repository_root,
                topdown=True,
                followlinks=False,
            ):
                current_path = Path(current)
                for name in directory_names:
                    if (current_path / name).is_symlink():
                        raise PatchConflictError(
                            "workspace contains an unexpected directory symlink"
                        )
                for name in sorted(file_names):
                    target = current_path / name
                    if target.is_symlink() or not target.is_file():
                        raise PatchConflictError(
                            "workspace contains an unexpected non-regular file"
                        )
                    relative = target.relative_to(repository_root).as_posix()
                    hashes[relative] = _hash_bytes(target.read_bytes())
        except OSError as exc:
            raise PatchConflictError("workspace content could not be verified") from exc
        return dict(sorted(hashes.items()))

    def _workspace_container(self, workspace_id: str) -> Path:
        if not isinstance(workspace_id, str) or not _WORKSPACE_ID_PATTERN.fullmatch(
            workspace_id
        ):
            raise WorkspaceError("workspace ID is invalid")
        container = (self._workspace_root / workspace_id).resolve()
        if not container.is_relative_to(self._workspace_root):
            raise WorkspaceError("workspace ID resolves outside the workspace root")
        return container

    def _open_existing(
        self,
        workspace_id: str,
        container: Path,
    ) -> WorkspaceSnapshot:
        metadata_path = container / _WORKSPACE_METADATA_NAME
        repository_root = container / _REPOSITORY_DIRECTORY_NAME
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            recorded_id = metadata["workspace_id"]
            baseline_hashes = metadata["baseline_hashes"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise PatchConflictError("existing workspace metadata is invalid") from exc
        if recorded_id != workspace_id or not isinstance(baseline_hashes, dict):
            raise PatchConflictError("existing workspace identity does not match")
        if not repository_root.is_dir() or repository_root.is_symlink():
            raise PatchConflictError("existing workspace repository is invalid")
        if any(
            not isinstance(path, str) or not isinstance(digest, str)
            for path, digest in baseline_hashes.items()
        ):
            raise PatchConflictError("existing workspace baseline is invalid")
        return WorkspaceSnapshot(
            workspace_id=workspace_id,
            repository_root=repository_root.resolve(),
            baseline_hashes=dict(baseline_hashes),
        )

    def _verify_unpatched_snapshot(self, snapshot: WorkspaceSnapshot) -> None:
        for path, expected_hash in snapshot.baseline_hashes.items():
            target = self.resolve_existing_file(snapshot.workspace_id, path)
            try:
                actual_hash = _hash_bytes(target.read_bytes())
            except OSError as exc:
                raise PatchConflictError("workspace snapshot could not be read") from exc
            if actual_hash != expected_hash:
                raise PatchConflictError(
                    "workspace content changed before patch application"
                )

    def _copy_snapshot(self, destination_root: Path) -> dict[str, str]:
        hashes: dict[str, str] = {}
        try:
            for current, directory_names, file_names in os.walk(
                self._canonical_repository,
                topdown=True,
                followlinks=False,
            ):
                current_path = Path(current)
                directory_names[:] = sorted(
                    name
                    for name in directory_names
                    if name.casefold() not in EXCLUDED_DIRECTORY_NAMES
                    and not (current_path / name).is_symlink()
                )
                for file_name in sorted(file_names):
                    source = current_path / file_name
                    if source.is_symlink():
                        continue
                    resolved = source.resolve(strict=True)
                    relative = resolved.relative_to(self._canonical_repository)
                    if not resolved.is_file():
                        continue
                    data = resolved.read_bytes()
                    relative_posix = relative.as_posix()
                    destination = destination_root.joinpath(*relative.parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
                    hashes[relative_posix] = _hash_bytes(data)
        except (OSError, ValueError) as exc:
            raise WorkspaceError("canonical repository snapshot could not be copied") from exc
        return dict(sorted(hashes.items()))

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            path.write_text(serialized, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise WorkspaceError("workspace metadata could not be written") from exc

    def _remove_staging(self, staging_path: Path) -> None:
        resolved = staging_path.resolve()
        if not resolved.is_relative_to(self._workspace_root):
            raise WorkspaceError("refusing to clean staging outside workspace root")
        try:
            shutil.rmtree(resolved)
        except OSError as exc:
            raise WorkspaceError("workspace staging could not be cleaned") from exc


def validate_repository_relative_path(path: str) -> PurePosixPath:
    if not isinstance(path, str) or not path or "\\" in path:
        raise PatchValidationError(
            "patch path must be a repository-relative POSIX path"
        )
    posix_path = PurePosixPath(path)
    windows_path = PureWindowsPath(path)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or path != posix_path.as_posix()
        or any(part in {"", ".", ".."} for part in posix_path.parts)
    ):
        raise PatchValidationError(
            "patch path must be a repository-relative POSIX path"
        )
    return posix_path


def _hash_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


__all__ = [
    "WorkspaceManager",
    "WorkspaceSnapshot",
    "validate_repository_relative_path",
]
