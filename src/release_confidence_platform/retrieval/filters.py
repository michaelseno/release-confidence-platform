"""Filter parsing and application for the Engineering Retrieval Layer."""

from __future__ import annotations

import argparse
from typing import Any

from release_confidence_platform.retrieval.dtypes import RetrievalFilter

# Fields that must never appear in retrieval output (sensitive data exclusion)
_BLOCKED_FIELD_KEYS = frozenset(
    {
        "request_body",
        "response_body",
        "raw_body",
        "body",
        "headers",
        "authorization",
        "cookie",
        "token",
        "secret",
        "password",
        "credential",
        "raw_result_s3_key",  # raw S3 keys are not exposed; use sanitized ref
    }
)


def parse_filters(args: argparse.Namespace) -> RetrievalFilter:
    """Build a RetrievalFilter from CLI args."""
    return RetrievalFilter(
        client_id=getattr(args, "client", None),
        audit_id=getattr(args, "audit", None),
        run_id=getattr(args, "run", None),
        endpoint_id=getattr(args, "endpoint", None),
        scenario_id=getattr(args, "scenario", None),
        window_start=_parse_window_start(getattr(args, "window", None)),
        window_end=_parse_window_end(getattr(args, "window", None)),
    )


def apply_filter(items: list[dict[str, Any]], filters: RetrievalFilter) -> list[dict[str, Any]]:
    """Filter a list of DynamoDB records by the provided RetrievalFilter."""
    result = items
    if filters.client_id:
        result = [
            item
            for item in result
            if item.get("client_id") == filters.client_id
            or item.get("PK") == f"CLIENT#{filters.client_id}"
        ]
    if filters.audit_id:
        result = [item for item in result if item.get("audit_id") == filters.audit_id]
    if filters.run_id:
        result = [item for item in result if item.get("run_id") == filters.run_id]
    if filters.endpoint_id:
        result = [item for item in result if item.get("endpoint_id") == filters.endpoint_id]
    return result


def scrub_sensitive_fields(record: dict[str, Any]) -> dict[str, Any]:
    """Remove any blocked sensitive fields from a record dict."""
    return {k: v for k, v in record.items() if k.lower() not in _BLOCKED_FIELD_KEYS}


def sanitize_s3_key_ref(key: str | None) -> str | None:
    """Replace a raw S3 key with a sanitized reference token."""
    if not key:
        return None
    import hashlib  # noqa: PLC0415

    return "s3ref:" + hashlib.sha256(key.encode()).hexdigest()[:16]


def _parse_window_start(window: str | None) -> str | None:
    if not window:
        return None
    if "/" in window:
        return window.split("/")[0]
    return window


def _parse_window_end(window: str | None) -> str | None:
    if not window:
        return None
    if "/" in window:
        parts = window.split("/")
        return parts[1] if len(parts) > 1 else None
    return None
