"""Immutable JSON-facing final review and export models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.critic import CriticAssessment
from app.planning import PlanningEvidence
from app.sandbox import TestRunResult


class ExportSchema(BaseModel):
    # Unified diff text is byte-significant and must never be normalized.
    model_config = ConfigDict(extra="forbid", frozen=True)


class FinalReviewDecision(ExportSchema):
    decision: Literal["approve", "reject"]
    patch_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    comment: str | None = None

    @field_validator("comment")
    @classmethod
    def blank_comment_becomes_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class FinalReviewPayload(ExportSchema):
    question: str = Field(min_length=1)
    issue: str = Field(min_length=1)
    plan_summary: str = Field(min_length=1)
    approved_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    final_attempt_number: int = Field(ge=1, le=2)
    final_patch_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_files: tuple[str, ...] = Field(min_length=1)
    changed_files: tuple[str, ...] = Field(min_length=1)
    canonical_unified_diff: str = Field(min_length=1)
    test_result: TestRunResult
    evidence: tuple[PlanningEvidence, ...]
    critic_assessment: CriticAssessment | None = None


class PatchExportArtifact(ExportSchema):
    artifact_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    filename: str = Field(pattern=r"^[0-9a-f]{64}\.patch$")
    patch_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempt_number: int = Field(ge=1, le=2)
    changed_files: tuple[str, ...] = Field(min_length=1)
    test_run_id: str = Field(pattern=r"^[0-9a-f]{64}$")


__all__ = ["FinalReviewDecision", "FinalReviewPayload", "PatchExportArtifact"]
