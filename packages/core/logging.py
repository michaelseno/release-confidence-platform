"""Structured logging field standards for Phase 0 tests and documentation."""

from packages.core.constants.identifiers import MANDATORY_IDENTIFIERS

STANDARD_LOG_FIELDS: tuple[str, ...] = (
    "timestamp",
    "level",
    "message",
    "service",
    "stage",
    "event_type",
)

CORRELATION_LOG_FIELDS: tuple[str, ...] = MANDATORY_IDENTIFIERS

FORBIDDEN_LOG_FIELDS: tuple[str, ...] = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
)
