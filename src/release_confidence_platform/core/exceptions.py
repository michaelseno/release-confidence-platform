"""Structured exceptions for Phase 1 backend engine."""

from dataclasses import dataclass


@dataclass
class EngineError(Exception):
    """Base sanitized engine exception."""

    error_type: str
    message: str

    def __str__(self) -> str:
        return self.message


class ValidationError(EngineError):
    def __init__(
        self,
        message: str = "Validation failed",
        error_type: str = "VALIDATION_ERROR",
        *,
        context: dict | None = None,
    ):
        super().__init__(error_type, message)
        self.context = context or {}


class ConfigError(EngineError):
    def __init__(self, message: str = "Configuration error", error_type: str = "CONFIG_ERROR"):
        super().__init__(error_type, message)


class SecretError(EngineError):
    def __init__(self, message: str = "Secret resolution failed", error_type: str = "SECRET_ERROR"):
        super().__init__(error_type, message)


class StorageError(EngineError):
    def __init__(self, message: str = "Storage error", error_type: str = "STORAGE_ERROR"):
        super().__init__(error_type, message)


class DuplicateRunIdError(StorageError):
    def __init__(self, message: str = "Duplicate run id"):
        super().__init__(message, "DUPLICATE_RUN_ID")
