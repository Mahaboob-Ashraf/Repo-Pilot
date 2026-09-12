"""Typed M5 configuration, infrastructure, and integrity failures."""


class TestRunnerError(Exception):
    """Base class for expected test-stage failures."""


class DockerUnavailableError(TestRunnerError):
    """Docker CLI or daemon is unavailable."""


class DockerImageUnavailableError(TestRunnerError):
    """The configured immutable test environment is not available locally."""


class TestTimeoutError(TestRunnerError):
    """The bounded Docker test exceeded its wall-clock deadline."""


class TestWorkspaceIntegrityError(TestRunnerError):
    """The M4 artifact or durable workspace no longer matches approval state."""


class TestConfigurationError(TestRunnerError):
    """The RepoPilot test request or sandbox policy is unsafe or invalid."""


class TestResultConflictError(TestRunnerError):
    """Persisted test evidence conflicts with the exact requested run."""


class TestSnapshotError(TestRunnerError):
    """A disposable execution snapshot could not be created or removed safely."""


__all__ = [
    "DockerImageUnavailableError",
    "DockerUnavailableError",
    "TestConfigurationError",
    "TestResultConflictError",
    "TestRunnerError",
    "TestSnapshotError",
    "TestTimeoutError",
    "TestWorkspaceIntegrityError",
]
