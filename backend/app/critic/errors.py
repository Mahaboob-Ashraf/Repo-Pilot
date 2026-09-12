"""Typed failure boundaries for bounded critic assessment."""


class CriticError(Exception):
    """Base class for expected critic-stage failures."""


class CriticInferenceError(CriticError):
    """Inference provider failed before a critic assessment was produced."""

    def __init__(
        self,
        *,
        model: str,
        provider_error_type: str,
        provider_error_classification: str,
        provider_error_message: str,
    ) -> None:
        super().__init__("critic inference failed")
        self.model = model
        self.provider_error_type = provider_error_type
        self.provider_error_classification = provider_error_classification
        self.provider_error_message = provider_error_message


class CriticOutputError(CriticError):
    """Model output was not a strict CriticAssessment."""


class CriticValidationError(CriticError):
    """A parsed assessment violated evidence or authority constraints."""


class CriticConflictError(CriticError):
    """Durable critic evidence conflicts with the current request."""


class RetryLimitError(CriticError):
    """A patch attempt would exceed the deterministic two-attempt limit."""

