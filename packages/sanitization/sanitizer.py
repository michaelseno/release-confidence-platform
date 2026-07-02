"""Centralized sanitization for logs, metadata, and raw evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTION_TOKEN = "[REDACTED]"

SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "email",
    "phone",
    "ssn",
    "pii",
)
# Structural evidence identifiers must survive sanitize() byte-identical. They are
# system-generated (UUIDs, operator-chosen slugs, version strings) and are compared
# for strict equality across storage layers (DynamoDB run records vs. S3 raw result
# envelopes) — a coincidental PII-pattern match (e.g. a UUID containing a bounded
# 10-digit run that looks like a phone number) must not cause redaction here.
STRUCTURAL_IDENTIFIER_KEYS = frozenset(
    {
        "run_id",
        "client_id",
        "audit_id",
        "audit_execution_id",
        "job_id",
        "aggregation_job_id",
        "config_version",
        "aggregation_version",
        "intelligence_job_id",
    }
)
SENSITIVE_QUERY_KEYS = (
    "token",
    "api_key",
    "apikey",
    "password",
    "secret",
    "auth",
    "email",
    "phone",
)
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})(?!\d)")
BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"\b(token|secret|api[_-]?key|password)=([^\s;,]+)", re.IGNORECASE
)


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _is_structural_identifier_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return normalized in STRUCTURAL_IDENTIFIER_KEYS


def _sanitize_string(value: str) -> str:
    value = BEARER_PATTERN.sub(REDACTION_TOKEN, value)
    value = SECRET_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}={REDACTION_TOKEN}", value
    )
    value = EMAIL_PATTERN.sub(REDACTION_TOKEN, value)
    return PHONE_PATTERN.sub(REDACTION_TOKEN, value)


def sanitize_url(value: str) -> str:
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return _sanitize_string(value)
    query = []
    changed = False
    for key, val in parse_qsl(parts.query, keep_blank_values=True):
        if any(part in key.lower() for part in SENSITIVE_QUERY_KEYS):
            query.append((key, REDACTION_TOKEN))
            changed = True
        else:
            query.append((key, _sanitize_string(val)))
    sanitized = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )
    return sanitized if changed else _sanitize_string(sanitized)


def sanitize(value: Any) -> Any:
    """Recursively redact sensitive keys and common PII patterns."""
    if isinstance(value, Mapping):
        sanitized: dict[Any, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                sanitized[key] = REDACTION_TOKEN
            elif _is_structural_identifier_key(key) and isinstance(item, str):
                sanitized[key] = item
            else:
                sanitized[key] = sanitize(item)
        return sanitized
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return sanitize_url(value)
        return _sanitize_string(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize(item) for item in value]
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value
