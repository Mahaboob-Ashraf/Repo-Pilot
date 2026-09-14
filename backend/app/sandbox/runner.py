"""Narrow test-runner protocol and restricted Docker implementation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import re
from time import monotonic
from typing import Protocol

from app.patching import PatchArtifact
from app.sandbox.errors import (
    DockerImageUnavailableError,
    DockerUnavailableError,
    TestConfigurationError,
    TestTimeoutError,
)
from app.sandbox.process import (
    CommandExecutor,
    ProcessLaunchError,
    ProcessResult,
    ProcessTimedOut,
    SubprocessCommandExecutor,
)
from app.sandbox.schemas import (
    TestMode,
    TestResourcePolicy,
    TestRunResult,
    TestStatus,
)
from app.sandbox.selectors import pytest_argv


DEFAULT_TEST_IMAGE = "repopilot-python-test:3.11-pytest9"
_IMAGE_REFERENCE = re.compile(
    r"^[a-z0-9]+(?:[._/-][a-z0-9]+)*(?::[A-Za-z0-9][A-Za-z0-9_.-]{0,127})?$"
)


@dataclass(frozen=True, slots=True)
class TestRunSpec:
    test_run_id: str
    patch: PatchArtifact
    mode: TestMode
    validated_selectors: tuple[str, ...]
    execution_repository: Path


class TestRunner(Protocol):
    @property
    def image_reference(self) -> str: ...

    @property
    def resource_policy(self) -> TestResourcePolicy: ...

    async def run(self, spec: TestRunSpec) -> TestRunResult: ...


class DockerTestRunner:
    """Run fixed pytest argv in a locked-down, networkless Docker container."""

    def __init__(
        self,
        *,
        image_reference: str = DEFAULT_TEST_IMAGE,
        docker_executable: str = "docker",
        resource_policy: TestResourcePolicy | None = None,
        executor: CommandExecutor | None = None,
    ) -> None:
        if (
            not isinstance(image_reference, str)
            or not _IMAGE_REFERENCE.fullmatch(image_reference)
        ):
            raise TestConfigurationError("Docker test image reference is invalid")
        if not isinstance(docker_executable, str) or not docker_executable.strip():
            raise TestConfigurationError("Docker executable is invalid")
        self._image_reference = image_reference
        self._docker_executable = docker_executable
        self._policy = resource_policy or TestResourcePolicy()
        self._executor = executor or SubprocessCommandExecutor()

    @property
    def image_reference(self) -> str:
        return self._image_reference

    @property
    def resource_policy(self) -> TestResourcePolicy:
        return self._policy

    async def run(self, spec: TestRunSpec) -> TestRunResult:
        started = monotonic()
        image_id: str | None = None
        try:
            await self._require_daemon()
            image_id = await self._resolve_local_image()
            command = self.docker_argv(spec, image_id=image_id)
            try:
                completed = await asyncio.to_thread(
                    self._executor.run,
                    command,
                    timeout_seconds=self._policy.wall_timeout_seconds,
                )
            except ProcessTimedOut as exc:
                cleanup = await self._force_remove(spec.test_run_id)
                timeout_error = TestTimeoutError(
                    "Docker test exceeded the configured wall-clock timeout"
                )
                stderr = exc.stderr + cleanup
                return self._result(
                    spec=spec,
                    status=TestStatus.TIMED_OUT,
                    exit_code=None,
                    started=started,
                    stdout=exc.stdout,
                    stderr=stderr,
                    image_id=image_id,
                    failure=timeout_error,
                    classification="test_timeout",
                )
            except ProcessLaunchError as exc:
                unavailable = DockerUnavailableError(
                    "Docker command could not start the configured container"
                )
                return self._result(
                    spec=spec,
                    status=TestStatus.INFRASTRUCTURE_FAILED,
                    exit_code=None,
                    started=started,
                    image_id=image_id,
                    failure=unavailable,
                    classification="container_launch_failed",
                )
            return self._completed_result(
                spec=spec,
                completed=completed,
                started=started,
                image_id=image_id,
            )
        except DockerImageUnavailableError as exc:
            return self._result(
                spec=spec,
                status=TestStatus.INFRASTRUCTURE_FAILED,
                exit_code=None,
                started=started,
                image_id=None,
                failure=exc,
                classification="image_unavailable",
            )
        except DockerUnavailableError as exc:
            return self._result(
                spec=spec,
                status=TestStatus.INFRASTRUCTURE_FAILED,
                exit_code=None,
                started=started,
                image_id=None,
                failure=exc,
                classification="docker_unavailable",
            )

    def docker_argv(
        self,
        spec: TestRunSpec,
        *,
        image_id: str | None = None,
    ) -> tuple[str, ...]:
        repository = spec.execution_repository.resolve(strict=True)
        container_name = _container_name(spec.test_run_id)
        mount = f"type=bind,source={repository},target=/workspace,readonly"
        tmpfs = (
            "/tmp:rw,noexec,nosuid,nodev,mode=1777,"
            f"size={self._policy.tmpfs_size_bytes}"
        )
        argv = (
            self._docker_executable,
            "run",
            "--rm",
            "--pull",
            "never",
            "--name",
            container_name,
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            str(self._policy.memory_bytes),
            "--cpus",
            _format_cpus(self._policy.cpus),
            "--pids-limit",
            str(self._policy.pids_limit),
            "--read-only",
            "--tmpfs",
            tmpfs,
            "--workdir",
            self._policy.container_workdir,
            "--user",
            self._policy.container_user,
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "HOME=/tmp",
            "--mount",
            mount,
            image_id or self._image_reference,
            *pytest_argv(spec.validated_selectors),
        )
        return argv

    async def _require_daemon(self) -> None:
        command = (
            self._docker_executable,
            "version",
            "--format",
            "{{.Server.Version}}",
        )
        try:
            result = await asyncio.to_thread(
                self._executor.run,
                command,
                timeout_seconds=min(10, self._policy.wall_timeout_seconds),
            )
        except (ProcessLaunchError, ProcessTimedOut) as exc:
            raise DockerUnavailableError("Docker daemon is unavailable") from exc
        if result.exit_code != 0 or not result.stdout.strip():
            raise DockerUnavailableError("Docker daemon is unavailable")

    async def _resolve_local_image(self) -> str:
        command = (
            self._docker_executable,
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            self._image_reference,
        )
        try:
            result = await asyncio.to_thread(
                self._executor.run,
                command,
                timeout_seconds=min(10, self._policy.wall_timeout_seconds),
            )
        except (ProcessLaunchError, ProcessTimedOut) as exc:
            raise DockerUnavailableError("Docker daemon is unavailable") from exc
        if result.exit_code != 0:
            raise DockerImageUnavailableError(
                "configured Docker test image is unavailable locally"
            )
        image_id = result.stdout.decode("utf-8", errors="replace").strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise DockerImageUnavailableError(
                "configured Docker test image has no valid resolved identity"
            )
        return image_id

    async def _force_remove(self, test_run_id: str) -> bytes:
        command = (
            self._docker_executable,
            "rm",
            "--force",
            _container_name(test_run_id),
        )
        try:
            result = await asyncio.to_thread(
                self._executor.run,
                command,
                timeout_seconds=10,
            )
        except (ProcessLaunchError, ProcessTimedOut):
            return b"\nRepoPilot could not confirm forced container cleanup."
        if result.exit_code != 0:
            return b"\nRepoPilot could not confirm forced container cleanup."
        return b""

    def _completed_result(
        self,
        *,
        spec: TestRunSpec,
        completed: ProcessResult,
        started: float,
        image_id: str,
    ) -> TestRunResult:
        if completed.exit_code == 0:
            return self._result(
                spec=spec,
                status=TestStatus.PASSED,
                exit_code=0,
                started=started,
                stdout=completed.stdout,
                stderr=completed.stderr,
                image_id=image_id,
            )
        if completed.exit_code == 1:
            status = TestStatus.FAILED
            classification = "pytest_assertion_failure"
            message = "pytest reported one or more test failures"
        elif completed.exit_code == 5:
            status = TestStatus.NO_TESTS_COLLECTED
            classification = "no_tests_collected"
            message = "pytest collected no tests"
        elif completed.exit_code in {2, 3, 4}:
            status = TestStatus.PYTEST_ERROR
            classification = "pytest_execution_error"
            message = "pytest did not complete as a normal test run"
        else:
            status = TestStatus.INFRASTRUCTURE_FAILED
            classification = "container_execution_failed"
            message = "Docker could not complete the configured test process"
        return self._result(
            spec=spec,
            status=status,
            exit_code=completed.exit_code,
            started=started,
            stdout=completed.stdout,
            stderr=completed.stderr,
            image_id=image_id,
            failure=RuntimeError(message),
            classification=classification,
        )

    def _result(
        self,
        *,
        spec: TestRunSpec,
        status: TestStatus,
        exit_code: int | None,
        started: float,
        image_id: str | None,
        stdout: bytes = b"",
        stderr: bytes = b"",
        failure: Exception | None = None,
        classification: str | None = None,
    ) -> TestRunResult:
        safe_stdout = _sanitize_output(stdout, spec.execution_repository)
        safe_stderr = _sanitize_output(stderr, spec.execution_repository)
        bounded_stdout, stdout_truncated = _bounded_text(
            safe_stdout, self._policy.output_limit_bytes
        )
        bounded_stderr, stderr_truncated = _bounded_text(
            safe_stderr, self._policy.output_limit_bytes
        )
        return TestRunResult(
            test_run_id=spec.test_run_id,
            patch_hash=spec.patch.patch_hash,
            workspace_id=spec.patch.workspace_id,
            mode=spec.mode,
            validated_selectors=spec.validated_selectors,
            status=status,
            exit_code=exit_code,
            duration_ms=max(0, round((monotonic() - started) * 1000)),
            stdout=bounded_stdout,
            stderr=bounded_stderr,
            output_truncated=stdout_truncated or stderr_truncated,
            image_reference=self._image_reference,
            image_id=image_id,
            resource_policy=self._policy,
            failure_classification=classification,
            failure_message=str(failure) if failure is not None else None,
        )


def _container_name(test_run_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", test_run_id):
        raise TestConfigurationError("test run ID is invalid")
    return f"repopilot-test-{test_run_id[:32]}"


def _format_cpus(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _sanitize_output(data: bytes, repository: Path) -> bytes:
    text = data.decode("utf-8", errors="replace")
    for path in {str(repository), repository.as_posix()}:
        text = text.replace(path, "<test-snapshot>")
    return text.encode("utf-8")


def _bounded_text(data: bytes, limit: int) -> tuple[str, bool]:
    if len(data) <= limit:
        return _decode_with_byte_limit(data, limit)
    marker = b"[RepoPilot output truncated; showing tail]\n"
    body_limit = max(0, limit - len(marker))
    bounded = marker + data[-body_limit:] if body_limit else marker[:limit]
    text, _decode_truncated = _decode_with_byte_limit(bounded, limit)
    return text, True


def _decode_with_byte_limit(data: bytes, limit: int) -> tuple[str, bool]:
    text = data.decode("utf-8", errors="replace")
    truncated = False
    while len(text.encode("utf-8")) > limit:
        text = text[:-1]
        truncated = True
    return text, truncated


__all__ = [
    "DEFAULT_TEST_IMAGE",
    "DockerTestRunner",
    "TestRunSpec",
    "TestRunner",
]
