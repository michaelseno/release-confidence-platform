"""Structured JSON logging field standards and helpers."""

from __future__ import annotations

import json
import logging
from typing import Any

from packages.core.constants.engine import LOG_CATEGORIES, LOG_CATEGORY_INTERNAL
from packages.core.constants.identifiers import MANDATORY_IDENTIFIERS
from packages.core.time import utc_now_iso
from packages.sanitization.sanitizer import sanitize

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


class StructuredLogger:
    """Small JSON logger that sanitizes payloads before emission."""

    def __init__(
        self, name: str = "release-confidence-platform", logger: logging.Logger | None = None
    ):
        self.logger = logger or logging.getLogger(name)

    def log(
        self,
        message: str,
        *,
        log_category: str = LOG_CATEGORY_INTERNAL,
        level: str = "INFO",
        **fields: Any,
    ) -> dict[str, Any]:
        if log_category not in LOG_CATEGORIES:
            log_category = LOG_CATEGORY_INTERNAL
        record = sanitize(
            {
                "timestamp": utc_now_iso(),
                "level": level,
                "message": message,
                "service": "release-confidence-platform",
                "event_type": fields.pop("event_type", message),
                "log_category": log_category,
                **fields,
            }
        )
        self.logger.log(
            getattr(logging, level.upper(), logging.INFO), json.dumps(record, sort_keys=True)
        )
        return record
