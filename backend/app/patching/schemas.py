"""Strict structured patch proposals and review artifacts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PatchSchema(BaseModel):
    """Immutable, extra-forbidden base for patching data."""

    # Exact replacement strings must retain leading/trailing whitespace verbatim.
    model_config = ConfigDict(extra="forbid", frozen=True)


class PatchEdit(PatchSchema):
    """One exact replacement proposed against an existing approved file."""

    path: str = Field(min_length=1)
    expected_old_text: str = Field(min_length=1)
    replacement_text: str
    evidence_chunk_ids: tuple[str, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1)

    @field_validator("evidence_chunk_ids")
    @classmethod
    def citations_must_be_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not chunk_id.strip() for chunk_id in value):
            raise ValueError("evidence chunk IDs must be nonblank")
        if len(value) != len(set(value)):
            raise ValueError("evidence chunk IDs must be unique")
        return value

    @field_validator("path", "rationale")
    @classmethod
    def descriptive_fields_must_be_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must be nonblank")
        return value


class PatchProposal(PatchSchema):
    """Model-proposed exact replacements; authority remains external."""

    summary: str = Field(min_length=1)
    edits: tuple[PatchEdit, ...] = Field(min_length=1)

    @field_validator("summary")
    @classmethod
    def summary_must_be_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must be nonblank")
        return value


class PatchArtifact(PatchSchema):
    """Canonical M4 result persisted in workflow state and workspace metadata."""

    workspace_id: str = Field(min_length=1)
    source_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    changed_files: tuple[str, ...] = Field(min_length=1)
    unified_diff: str = Field(min_length=1)
    patch_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


__all__ = ["PatchArtifact", "PatchEdit", "PatchProposal"]
