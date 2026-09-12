"""Typed patch-export failures."""


class PatchExportError(Exception):
    """Expected export authority, integrity, or write failure."""


class PatchExportConflictError(PatchExportError):
    """An existing deterministic export path contains conflicting bytes."""


class FinalApprovalError(PatchExportError):
    """Final human approval is absent, stale, or mismatched."""

