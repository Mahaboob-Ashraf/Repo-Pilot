"""Disposable execution snapshots derived from verified M4 workspaces."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import shutil
import tempfile
from typing import Iterator

from app.patching import PatchArtifact, WorkspaceManager, validate_repository_relative_path
from app.sandbox.errors import TestSnapshotError


@dataclass(frozen=True, slots=True)
class TestExecutionSnapshot:
    repository_root: Path


class DisposableTestSnapshotManager:
    """Copy exact verified workspace bytes and remove them after one test run."""

    def __init__(
        self,
        *,
        workspace_manager: WorkspaceManager,
        snapshot_root: str | Path,
    ) -> None:
        root = Path(snapshot_root).expanduser()
        if not root.is_absolute():
            raise TestSnapshotError("test snapshot root must be absolute")
        resolved = root.resolve()
        forbidden = (
            workspace_manager.canonical_repository,
            workspace_manager.workspace_root,
        )
        if any(resolved == item or resolved.is_relative_to(item) for item in forbidden):
            raise TestSnapshotError(
                "test snapshot root must be outside source and durable workspaces"
            )
        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise TestSnapshotError("test snapshot root could not be created") from exc
        self._workspaces = workspace_manager
        self._snapshot_root = resolved

    @property
    def snapshot_root(self) -> Path:
        return self._snapshot_root

    @contextmanager
    def create(
        self,
        *,
        artifact: PatchArtifact,
        expected_hashes: dict[str, str],
    ) -> Iterator[TestExecutionSnapshot]:
        staging = Path(
            tempfile.mkdtemp(prefix="execution-", dir=self._snapshot_root)
        ).resolve()
        repository_root = staging / "repository"
        try:
            repository_root.mkdir()
            durable_root = self._workspaces.repository_root_for(artifact.workspace_id)
            for path in sorted(expected_hashes):
                relative = validate_repository_relative_path(path)
                source = durable_root.joinpath(*relative.parts)
                if source.is_symlink() or not source.is_file():
                    raise TestSnapshotError(
                        "verified workspace file became unsafe during snapshot copy"
                    )
                data = source.read_bytes()
                if sha256(data).hexdigest() != expected_hashes[path]:
                    raise TestSnapshotError(
                        "workspace changed while creating the test snapshot"
                    )
                destination = repository_root.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            yield TestExecutionSnapshot(repository_root=repository_root)
        except OSError as exc:
            raise TestSnapshotError("disposable test snapshot failed") from exc
        finally:
            self._remove(staging)

    def _remove(self, staging: Path) -> None:
        resolved = staging.resolve()
        if not resolved.is_relative_to(self._snapshot_root):
            raise TestSnapshotError("refusing to clean outside test snapshot root")
        try:
            shutil.rmtree(resolved)
        except OSError as exc:
            raise TestSnapshotError("disposable test snapshot cleanup failed") from exc


__all__ = ["DisposableTestSnapshotManager", "TestExecutionSnapshot"]
