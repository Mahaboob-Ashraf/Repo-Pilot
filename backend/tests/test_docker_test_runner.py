"""M5 command safety, Docker policy, result mapping, and bounded-output tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.patching import PatchArtifact
from app.sandbox import (
    DockerTestRunner,
    ProcessResult,
    ProcessTimedOut,
    TestConfigurationError as ConfigurationError,
    TestMode as Mode,
    TestResourcePolicy as ResourcePolicy,
    TestRunSpec as RunSpec,
    TestStatus as Status,
    pytest_argv,
    validate_pytest_selectors,
)
from app.sandbox.process import SubprocessCommandExecutor
from app.sandbox.process import ProcessLaunchError


IMAGE_ID = "sha256:" + "1" * 64


@dataclass
class FakeExecutor:
    outcomes: list[ProcessResult | Exception]
    calls: list[tuple[tuple[str, ...], int]] = field(default_factory=list)

    def run(self, argv: tuple[str, ...], *, timeout_seconds: int) -> ProcessResult:
        self.calls.append((argv, timeout_seconds))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _spec(tmp_path: Path, *, selectors=()) -> RunSpec:
    repository = tmp_path / "execution" / "repository"
    (repository / "tests").mkdir(parents=True)
    (repository / "tests" / "test_pricing.py").write_text(
        "def test_price():\n    assert True\n", encoding="utf-8"
    )
    return RunSpec(
        test_run_id="a" * 64,
        patch=PatchArtifact(
            workspace_id="workspace-" + "b" * 64,
            source_plan_hash="c" * 64,
            changed_files=("pricing.py",),
            unified_diff="--- a/pricing.py\n+++ b/pricing.py\n",
            patch_hash="d" * 64,
        ),
        mode=Mode.TARGETED if selectors else Mode.FULL,
        validated_selectors=selectors,
        execution_repository=repository,
    )


def _executor_for_run(exit_code=0, *, stdout=b"ok", stderr=b"") -> FakeExecutor:
    return FakeExecutor(
        [
            ProcessResult(0, b"29.0\n", b""),
            ProcessResult(0, (IMAGE_ID + "\n").encode(), b""),
            ProcessResult(exit_code, stdout, stderr),
        ]
    )


def test_full_command_is_repopilot_owned_and_has_no_selector(tmp_path) -> None:
    executor = _executor_for_run()
    runner = DockerTestRunner(executor=executor)

    result = asyncio.run(runner.run(_spec(tmp_path)))

    argv = executor.calls[2][0]
    assert result.status is Status.PASSED
    assert argv[-6:] == pytest_argv(())
    assert "shell" not in argv


def test_targeted_selector_is_one_literal_argv_element(tmp_path) -> None:
    selector = "tests/test_pricing.py::test_price"
    executor = _executor_for_run()
    runner = DockerTestRunner(executor=executor)

    asyncio.run(runner.run(_spec(tmp_path, selectors=(selector,))))

    argv = executor.calls[2][0]
    assert argv[-1] == selector
    assert argv.count(selector) == 1


@pytest.mark.parametrize(
    "selector",
    [
        "C:/repo/tests/test_pricing.py::test_price",
        "../tests/test_pricing.py::test_price",
        "tests/missing.py::test_price",
        "tests/test_pricing.py;whoami",
        "tests/test_pricing.py::test_price|whoami",
        "tests/test_pricing.py\n--version",
    ],
)
def test_unsafe_or_missing_selectors_are_rejected(tmp_path, selector) -> None:
    repository = _spec(tmp_path).execution_repository

    with pytest.raises(ConfigurationError):
        validate_pytest_selectors((selector,), repository_root=repository)


def test_pytest_executable_cannot_be_redefined() -> None:
    argv = pytest_argv(("tests/test_safe.py::test_safe",))

    assert argv[:6] == (
        "python",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
    )


def test_subprocess_boundary_forces_shell_false(monkeypatch) -> None:
    observed = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed.update(kwargs)

        class Completed:
            returncode = 0
            stdout = b""
            stderr = b""

        return Completed()

    monkeypatch.setattr("subprocess.run", fake_run)
    SubprocessCommandExecutor().run(("docker", "version"), timeout_seconds=3)

    assert observed["argv"] == ["docker", "version"]
    assert observed["shell"] is False


def test_docker_security_profile_and_mount_boundary(tmp_path) -> None:
    executor = _executor_for_run()
    policy = ResourcePolicy(
        memory_bytes=268_435_456,
        cpus=0.5,
        pids_limit=64,
        wall_timeout_seconds=30,
    )
    runner = DockerTestRunner(executor=executor, resource_policy=policy)
    spec = _spec(tmp_path)
    canonical = tmp_path / "canonical"
    canonical.mkdir()

    asyncio.run(runner.run(spec))

    argv = executor.calls[2][0]
    joined = " ".join(argv)
    assert "--network none" in joined
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--memory 268435456" in joined
    assert "--cpus 0.5" in joined
    assert "--pids-limit 64" in joined
    assert "--read-only" in argv
    assert "--pull never" in joined
    assert "PYTHONDONTWRITEBYTECODE=1" in argv
    assert any(str(spec.execution_repository.resolve()) in item for item in argv)
    assert all(str(canonical.resolve()) not in item for item in argv)
    assert all("docker.sock" not in item and ".docker" not in item for item in argv)


@pytest.mark.parametrize(
    ("exit_code", "expected"),
    [
        (0, Status.PASSED),
        (1, Status.FAILED),
        (5, Status.NO_TESTS_COLLECTED),
        (3, Status.PYTEST_ERROR),
        (125, Status.INFRASTRUCTURE_FAILED),
    ],
)
def test_exit_codes_have_deliberate_statuses(tmp_path, exit_code, expected) -> None:
    executor = _executor_for_run(exit_code)
    runner = DockerTestRunner(executor=executor)

    result = asyncio.run(runner.run(_spec(tmp_path)))

    assert result.status is expected
    assert result.exit_code == exit_code
    assert result.patch_hash == "d" * 64
    assert result.image_reference == "repopilot-python-test:3.11-pytest9"
    assert result.image_id == IMAGE_ID
    assert IMAGE_ID in executor.calls[2][0]
    assert "repopilot-python-test:3.11-pytest9" not in executor.calls[2][0]


def test_daemon_unavailable_is_infrastructure_failure(tmp_path) -> None:
    runner = DockerTestRunner(
        executor=FakeExecutor([ProcessResult(1, b"", b"daemon unavailable")])
    )

    result = asyncio.run(runner.run(_spec(tmp_path)))

    assert result.status is Status.INFRASTRUCTURE_FAILED
    assert result.failure_classification == "docker_unavailable"


def test_missing_image_fails_without_docker_run_or_pull(tmp_path) -> None:
    executor = FakeExecutor(
        [
            ProcessResult(0, b"29.0\n", b""),
            ProcessResult(1, b"", b"not found"),
        ]
    )
    runner = DockerTestRunner(executor=executor)

    result = asyncio.run(runner.run(_spec(tmp_path)))

    assert result.status is Status.INFRASTRUCTURE_FAILED
    assert result.failure_classification == "image_unavailable"
    assert len(executor.calls) == 2
    assert all(call[0][:3] != ("docker", "run", "--rm") for call in executor.calls)
    assert all("pull" not in call[0] for call in executor.calls)


def test_timeout_forces_container_removal(tmp_path) -> None:
    executor = FakeExecutor(
        [
            ProcessResult(0, b"29.0\n", b""),
            ProcessResult(0, (IMAGE_ID + "\n").encode(), b""),
            ProcessTimedOut(stdout=b"partial", stderr=b"timeout"),
            ProcessResult(0, b"removed", b""),
        ]
    )
    runner = DockerTestRunner(executor=executor)

    result = asyncio.run(runner.run(_spec(tmp_path)))

    assert result.status is Status.TIMED_OUT
    assert result.failure_classification == "test_timeout"
    assert executor.calls[-1][0][:3] == ("docker", "rm", "--force")


def test_container_launch_failure_is_infrastructure_result(tmp_path) -> None:
    executor = FakeExecutor(
        [
            ProcessResult(0, b"29.0\n", b""),
            ProcessResult(0, (IMAGE_ID + "\n").encode(), b""),
            ProcessLaunchError("missing executable"),
        ]
    )

    result = asyncio.run(DockerTestRunner(executor=executor).run(_spec(tmp_path)))

    assert result.status is Status.INFRASTRUCTURE_FAILED
    assert result.failure_classification == "container_launch_failed"


def test_stdout_and_stderr_are_bounded_and_host_path_is_redacted(tmp_path) -> None:
    policy = ResourcePolicy(output_limit_bytes=1024)
    spec = _spec(tmp_path)
    secret_path = str(spec.execution_repository.resolve()).encode()
    executor = _executor_for_run(
        stdout=secret_path + b"x" * 3000,
        stderr=b"y" * 3000,
    )
    runner = DockerTestRunner(executor=executor, resource_policy=policy)

    result = asyncio.run(runner.run(spec))

    assert result.output_truncated is True
    assert len(result.stdout.encode()) <= 1024
    assert len(result.stderr.encode()) <= 1024
    assert str(spec.execution_repository.resolve()) not in result.stdout
