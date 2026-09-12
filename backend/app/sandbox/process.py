"""Small explicit-argv subprocess boundary used only by DockerTestRunner."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProcessResult:
    exit_code: int
    stdout: bytes
    stderr: bytes


class ProcessLaunchError(OSError):
    pass


class ProcessTimedOut(TimeoutError):
    def __init__(self, *, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.stdout = stdout
        self.stderr = stderr
        super().__init__("process exceeded its timeout")


class CommandExecutor(Protocol):
    def run(self, argv: tuple[str, ...], *, timeout_seconds: int) -> ProcessResult:
        """Execute literal argv without a command shell."""


class SubprocessCommandExecutor:
    def run(self, argv: tuple[str, ...], *, timeout_seconds: int) -> ProcessResult:
        try:
            completed = subprocess.run(
                list(argv),
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProcessTimedOut(
                stdout=_as_bytes(exc.stdout),
                stderr=_as_bytes(exc.stderr),
            ) from exc
        except OSError as exc:
            raise ProcessLaunchError("Docker command could not be started") from exc
        return ProcessResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def _as_bytes(value: bytes | str | None) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    return value.encode("utf-8", errors="replace")


__all__ = [
    "CommandExecutor",
    "ProcessLaunchError",
    "ProcessResult",
    "ProcessTimedOut",
    "SubprocessCommandExecutor",
]
