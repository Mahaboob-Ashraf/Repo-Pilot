"""Typed safety and application failures for M4 patching."""

from __future__ import annotations

from app.providers.base import InferenceProviderError


class PatchError(Exception):
    """Base class for expected patch-stage failures."""


class PatchOutputError(PatchError):
    """Raised when model output is not a valid structured patch proposal."""


class PatchValidationError(PatchError):
    """Raised when a proposal fails deterministic whole-patch validation."""


class PatchScopeError(PatchValidationError):
    """Raised when an edit exceeds the human-approved file scope."""


class StaleApprovalError(PatchValidationError):
    """Raised when approved evidence no longer matches repository content."""


class PatchConflictError(PatchError):
    """Raised when persisted workspace state conflicts with the approved run."""


class PatchApplicationError(PatchError):
    """Raised when transactional workspace application cannot complete."""


class WorkspaceError(PatchError):
    """Raised when an isolated durable workspace cannot be prepared safely."""


class PatchInferenceError(PatchError):
    """Raised when the inference provider cannot produce a patch proposal."""

    def __init__(
        self,
        *,
        model: str,
        provider_error: InferenceProviderError,
        provider_error_type: str,
        provider_error_classification: str,
        provider_error_message: str,
    ) -> None:
        self.model = model
        self.provider_error_type = provider_error_type
        self.provider_error_classification = provider_error_classification
        self.provider_error_message = provider_error_message
        super().__init__(f"patch inference failed for model {model}")


__all__ = [
    "PatchApplicationError",
    "PatchConflictError",
    "PatchError",
    "PatchInferenceError",
    "PatchOutputError",
    "PatchScopeError",
    "PatchValidationError",
    "StaleApprovalError",
    "WorkspaceError",
]
