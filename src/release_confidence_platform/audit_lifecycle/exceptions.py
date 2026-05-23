"""Lifecycle-specific controlled errors."""

from release_confidence_platform.core.exceptions import EngineError


class LifecycleError(EngineError):
    def __init__(self, message: str = "Lifecycle error", error_type: str = "LIFECYCLE_ERROR"):
        super().__init__(error_type, message)


class InvalidTransitionError(LifecycleError):
    def __init__(self, message: str = "Invalid lifecycle transition"):
        super().__init__(message, "INVALID_LIFECYCLE_TRANSITION")


class LifecycleConflictError(LifecycleError):
    def __init__(self, message: str = "Lifecycle state conflict"):
        super().__init__(message, "LIFECYCLE_CONFLICT")
