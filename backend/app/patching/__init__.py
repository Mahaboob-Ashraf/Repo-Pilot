"""Approved-scope structured patch generation and isolated application."""

from app.patching.errors import (
    PatchApplicationError,
    PatchConflictError,
    PatchError,
    PatchInferenceError,
    PatchOutputError,
    PatchScopeError,
    PatchValidationError,
    StaleApprovalError,
    WorkspaceError,
)
from app.patching.patcher import (
    PATCHER_PROMPT_TEMPLATE,
    RETRY_PATCHER_PROMPT_TEMPLATE,
    StructuredPatcher,
)
from app.patching.schemas import PatchArtifact, PatchEdit, PatchProposal
from app.patching.service import (
    ApprovedPatchService,
    canonical_patch_hash,
    canonical_unified_diff,
)
from app.patching.workspace import (
    WorkspaceManager,
    WorkspaceSnapshot,
    validate_repository_relative_path,
)

__all__ = [
    "ApprovedPatchService",
    "PATCHER_PROMPT_TEMPLATE",
    "RETRY_PATCHER_PROMPT_TEMPLATE",
    "PatchApplicationError",
    "PatchArtifact",
    "PatchConflictError",
    "PatchEdit",
    "PatchError",
    "PatchInferenceError",
    "PatchOutputError",
    "PatchProposal",
    "PatchScopeError",
    "PatchValidationError",
    "StaleApprovalError",
    "StructuredPatcher",
    "WorkspaceError",
    "WorkspaceManager",
    "WorkspaceSnapshot",
    "canonical_patch_hash",
    "canonical_unified_diff",
    "validate_repository_relative_path",
]
