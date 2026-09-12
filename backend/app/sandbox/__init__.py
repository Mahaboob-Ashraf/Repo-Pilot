"""Restricted Docker test execution for verified M4 patch artifacts."""

from app.sandbox.errors import (
    DockerImageUnavailableError,
    DockerUnavailableError,
    TestConfigurationError,
    TestResultConflictError,
    TestRunnerError,
    TestSnapshotError,
    TestTimeoutError,
    TestWorkspaceIntegrityError,
)
from app.sandbox.process import ProcessResult, ProcessTimedOut
from app.sandbox.runner import (
    DEFAULT_TEST_IMAGE,
    DockerTestRunner,
    TestRunner,
    TestRunSpec,
)
from app.sandbox.schemas import (
    TestMode,
    TestResourcePolicy,
    TestRunRequest,
    TestRunResult,
    TestStatus,
)
from app.sandbox.selectors import pytest_argv, validate_pytest_selectors
from app.sandbox.service import ApprovedPatchTestService, compute_test_request_hash
from app.sandbox.store import TestResultStore
from app.sandbox.workspace import DisposableTestSnapshotManager

__all__ = [
    "ApprovedPatchTestService",
    "DEFAULT_TEST_IMAGE",
    "DisposableTestSnapshotManager",
    "DockerImageUnavailableError",
    "DockerTestRunner",
    "DockerUnavailableError",
    "ProcessResult",
    "ProcessTimedOut",
    "TestConfigurationError",
    "TestMode",
    "TestResourcePolicy",
    "TestResultConflictError",
    "TestResultStore",
    "TestRunRequest",
    "TestRunResult",
    "TestRunSpec",
    "TestRunner",
    "TestRunnerError",
    "TestSnapshotError",
    "TestStatus",
    "TestTimeoutError",
    "TestWorkspaceIntegrityError",
    "pytest_argv",
    "compute_test_request_hash",
    "validate_pytest_selectors",
]
