"""Immutable JSON-friendly schemas for bounded M5 test execution."""

from __future__ import annotations

from enum import StrEnum

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SandboxSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TestMode(StrEnum):
    FULL = "full"
    TARGETED = "targeted"


class TestStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NO_TESTS_COLLECTED = "no_tests_collected"
    PYTEST_ERROR = "pytest_error"
    TIMED_OUT = "timed_out"
    INFRASTRUCTURE_FAILED = "infrastructure_failed"


class TestRunRequest(SandboxSchema):
    """RepoPilot-owned test mode and optional literal pytest selectors."""

    mode: TestMode = TestMode.FULL
    selectors: tuple[str, ...] = ()

    @model_validator(mode="after")
    def selectors_match_mode(self) -> TestRunRequest:
        if self.mode is TestMode.FULL and self.selectors:
            raise ValueError("full test mode must not contain selectors")
        if self.mode is TestMode.TARGETED and not self.selectors:
            raise ValueError("targeted test mode requires selectors")
        if len(self.selectors) != len(set(self.selectors)):
            raise ValueError("test selectors must be unique")
        return self


class TestResourcePolicy(SandboxSchema):
    network: Literal["none"] = "none"
    memory_bytes: int = Field(default=536_870_912, ge=67_108_864)
    cpus: float = Field(default=1.0, gt=0, le=8)
    pids_limit: int = Field(default=128, ge=16, le=4096)
    wall_timeout_seconds: int = Field(default=120, ge=1, le=3600)
    tmpfs_size_bytes: int = Field(default=67_108_864, ge=1_048_576)
    output_limit_bytes: int = Field(default=65_536, ge=1_024, le=1_048_576)
    container_workdir: Literal["/workspace"] = "/workspace"
    container_user: Literal["65532:65532"] = "65532:65532"
    read_only_root: bool = True
    source_mount_read_only: bool = True
    cap_drop_all: bool = True
    no_new_privileges: bool = True

    @model_validator(mode="after")
    def required_security_controls(self) -> TestResourcePolicy:
        if self.network != "none":
            raise ValueError("Docker test networking must be disabled")
        if not all(
            (
                self.read_only_root,
                self.source_mount_read_only,
                self.cap_drop_all,
                self.no_new_privileges,
            )
        ):
            raise ValueError("required Docker security controls cannot be disabled")
        return self


class TestRunResult(SandboxSchema):
    """Bounded evidence for exactly one patch-bound pytest execution."""

    test_run_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    patch_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    workspace_id: str = Field(min_length=1)
    mode: TestMode
    validated_selectors: tuple[str, ...]
    status: TestStatus
    exit_code: int | None
    duration_ms: int = Field(ge=0)
    stdout: str
    stderr: str
    output_truncated: bool
    image_reference: str = Field(min_length=1)
    image_id: str | None = None
    resource_policy: TestResourcePolicy
    failure_classification: str | None = None
    failure_message: str | None = None


__all__ = [
    "TestMode",
    "TestResourcePolicy",
    "TestRunRequest",
    "TestRunResult",
    "TestStatus",
]
