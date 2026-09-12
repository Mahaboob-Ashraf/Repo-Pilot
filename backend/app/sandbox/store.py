"""Small durable cache for replay-safe, patch-bound test evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from pydantic import ValidationError

from app.sandbox.errors import TestResultConflictError
from app.sandbox.schemas import TestRunResult


class TestResultStore:
    def __init__(self, root: str | Path) -> None:
        path = Path(root).expanduser()
        if not path.is_absolute():
            raise TestResultConflictError("test result root must be absolute")
        self._root = path.resolve()

    @property
    def root(self) -> Path:
        return self._root

    def load(self, test_run_id: str) -> TestRunResult | None:
        path = self._path(test_run_id)
        if not path.exists():
            return None
        try:
            result = TestRunResult.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise TestResultConflictError("stored test evidence is invalid") from exc
        if result.test_run_id != test_run_id:
            raise TestResultConflictError("stored test evidence identity conflicts")
        return result

    def save(self, result: TestRunResult) -> None:
        self.ensure_root()
        destination = self._path(result.test_run_id)
        existing = self.load(result.test_run_id)
        if existing is not None:
            if existing != result:
                raise TestResultConflictError("completed test evidence conflicts")
            return
        serialized = json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=".test-result-",
                suffix=".tmp",
                dir=self._root,
                delete=False,
            ) as handle:
                handle.write(serialized)
                temporary = Path(handle.name)
            os.replace(temporary, destination)
        except OSError as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise TestResultConflictError("test evidence could not be persisted") from exc

    def ensure_root(self) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise TestResultConflictError("test result root could not be created") from exc

    def _path(self, test_run_id: str) -> Path:
        if len(test_run_id) != 64 or any(c not in "0123456789abcdef" for c in test_run_id):
            raise TestResultConflictError("test run ID is invalid")
        path = (self._root / f"test-{test_run_id}.json").resolve()
        if not path.is_relative_to(self._root):
            raise TestResultConflictError("test evidence path escaped its root")
        return path


__all__ = ["TestResultStore"]
