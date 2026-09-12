"""Immutable schemas and deterministic grounding rules for repair planning."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import PurePosixPath, PureWindowsPath

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.context_packing import ContextPack, render_context_pack


class PlanningSchema(BaseModel):
    """Strict immutable base for planner and evidence records."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RepairStep(PlanningSchema):
    """One concrete ordered repair action grounded in packed evidence."""

    description: str = Field(min_length=1)
    affected_files: tuple[str, ...] = Field(min_length=1)
    evidence_chunk_ids: tuple[str, ...]

    @field_validator("affected_files", "evidence_chunk_ids")
    @classmethod
    def entries_must_be_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("entries must be unique")
        return value


class RepairPlan(PlanningSchema):
    """A deterministic model proposal that still requires human approval."""

    summary: str = Field(min_length=1)
    diagnosis: str = Field(min_length=1)
    proposed_files: tuple[str, ...] = Field(min_length=1)
    steps: tuple[RepairStep, ...]
    suggested_tests: tuple[str, ...] = Field(min_length=1)

    @field_validator("proposed_files", "suggested_tests")
    @classmethod
    def entries_must_be_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("entries must be unique")
        return value


class PlanningEvidence(PlanningSchema):
    """JSON-friendly provenance for one chunk in the bounded ContextPack."""

    chunk_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    qualified_symbol: str = Field(min_length=1)
    chunk_type: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_text: str | None = None
    origin: str = Field(min_length=1)
    source_retrieval_rank: int | None = Field(default=None, ge=1)
    structural_causes: tuple[str, ...] = ()


class PlanningContextSnapshot(PlanningSchema):
    """Only the immutable, serializable ContextPack view needed by M3."""

    issue_text: str = Field(min_length=1)
    rendered_context: str = Field(min_length=1)
    evidence: tuple[PlanningEvidence, ...]
    context_status: str = Field(min_length=1)
    retrieval_mode: str = Field(min_length=1)
    retrieval_degraded: bool
    degradation_reason: str | None = None

    @classmethod
    def from_context_pack(cls, context_pack: ContextPack) -> PlanningContextSnapshot:
        evidence = tuple(
            PlanningEvidence(
                chunk_id=item.chunk_id,
                path=item.path,
                qualified_symbol=item.qualified_symbol,
                chunk_type=item.chunk.chunk_type.value,
                start_line=item.chunk.start_line,
                end_line=item.chunk.end_line,
                content_hash=item.chunk.content_hash,
                source_text=item.chunk.source_text,
                origin=item.origin.value,
                source_retrieval_rank=item.source_retrieval_rank,
                structural_causes=tuple(
                    f"{cause.relation.value}:{cause.seed_chunk_id}:"
                    f"{cause.seed_retrieval_rank}"
                    for cause in item.structural_causes
                ),
            )
            for item in context_pack.included_chunks
        )
        return cls(
            issue_text=context_pack.query,
            rendered_context=render_context_pack(context_pack),
            evidence=evidence,
            context_status=context_pack.status.value,
            retrieval_mode=context_pack.retrieval_mode.value,
            retrieval_degraded=context_pack.degraded,
            degradation_reason=context_pack.degradation_reason,
        )


class PlanValidationError(ValueError):
    """Raised when parsed model output is not grounded in the ContextPack."""


def validate_plan_grounding(
    plan: RepairPlan,
    context: PlanningContextSnapshot,
) -> RepairPlan:
    """Reject every citation or editable path not present in packed evidence."""

    if not plan.steps:
        raise PlanValidationError("repair plan must contain a concrete repair step")

    evidence_chunk_ids = {item.chunk_id for item in context.evidence}
    evidence_paths = {item.path for item in context.evidence}
    proposed_files = set(plan.proposed_files)

    for path in plan.proposed_files:
        _validate_repository_relative_path(path)
        if path not in evidence_paths:
            raise PlanValidationError(
                f"proposed file is not represented in ContextPack evidence: {path}"
            )

    citation_count = 0
    affected_files: set[str] = set()
    for step_number, step in enumerate(plan.steps, start=1):
        if not step.evidence_chunk_ids:
            raise PlanValidationError(
                f"repair step {step_number} must contain an evidence citation"
            )
        citation_count += len(step.evidence_chunk_ids)
        for chunk_id in step.evidence_chunk_ids:
            if chunk_id not in evidence_chunk_ids:
                raise PlanValidationError(
                    f"repair step {step_number} cites an unknown chunk: {chunk_id}"
                )
        for path in step.affected_files:
            affected_files.add(path)
            _validate_repository_relative_path(path)
            if path not in evidence_paths:
                raise PlanValidationError(
                    f"repair step {step_number} affects a file outside ContextPack: "
                    f"{path}"
                )
            if path not in proposed_files:
                raise PlanValidationError(
                    f"repair step {step_number} affects a file outside proposed scope: "
                    f"{path}"
                )

    if citation_count == 0:
        raise PlanValidationError("repair plan must contain an evidence citation")
    if affected_files != proposed_files:
        raise PlanValidationError(
            "proposed files must exactly match the files affected by repair steps"
        )
    return plan


def repair_plan_hash(plan: RepairPlan) -> str:
    """Hash canonical JSON without machine-specific or nondeterministic fields."""

    canonical_json = json.dumps(
        plan.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical_json.encode("utf-8")).hexdigest()


def _validate_repository_relative_path(path: str) -> None:
    if not path or "\\" in path:
        raise PlanValidationError(
            f"file path must be a repository-relative POSIX path: {path!r}"
        )
    posix_path = PurePosixPath(path)
    windows_path = PureWindowsPath(path)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or path != posix_path.as_posix()
        or any(part in {"", ".", ".."} for part in posix_path.parts)
    ):
        raise PlanValidationError(
            f"file path must be a repository-relative POSIX path: {path!r}"
        )
