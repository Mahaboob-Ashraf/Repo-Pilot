"""Strict JSON-friendly critic schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CriticSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RetryInstruction(CriticSchema):
    """Advisory action explicitly tied to already-approved files."""

    description: str = Field(min_length=1)
    affected_files: tuple[str, ...] = Field(min_length=1)

    @field_validator("affected_files")
    @classmethod
    def files_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("retry instruction files must be unique")
        return value


class CriticAssessment(CriticSchema):
    """Bounded diagnosis; it carries no approval or patch authority."""

    summary: str = Field(min_length=1)
    failure_diagnosis: str = Field(min_length=1)
    retry_recommended: bool
    retry_instructions: tuple[RetryInstruction, ...]
    evidence_chunk_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_chunk_ids")
    @classmethod
    def citations_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item for item in value) or len(value) != len(set(value)):
            raise ValueError("critic evidence citations must be unique and nonblank")
        return value

    @model_validator(mode="after")
    def recommendation_matches_instructions(self) -> CriticAssessment:
        if self.retry_recommended != bool(self.retry_instructions):
            raise ValueError(
                "retry instructions must be present exactly when retry is recommended"
            )
        return self


__all__ = ["CriticAssessment", "RetryInstruction"]
