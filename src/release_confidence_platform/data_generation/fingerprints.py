"""Sanitized canonical SHA-256 fingerprint utilities for Phase 2."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from release_confidence_platform.sanitization.sanitizer import sanitize

EMPTY_PAYLOAD_SENTINEL = "EMPTY_PAYLOAD"


def canonicalize(value: Any, *, empty_payload: bool = False) -> bytes:
    if empty_payload:
        return EMPTY_PAYLOAD_SENTINEL.encode("utf-8")
    sanitized = sanitize(value)
    if isinstance(sanitized, bytes | bytearray):
        return b"binary:[REDACTED]"
    if isinstance(sanitized, str):
        return f"string:{sanitized}".encode()
    return ("json:" + json.dumps(sanitized, sort_keys=True, separators=(",", ":"))).encode("utf-8")


def fingerprint(value: Any, *, empty_payload: bool = False) -> str:
    return hashlib.sha256(canonicalize(value, empty_payload=empty_payload)).hexdigest()


def payload_fingerprint(payload: Any) -> str:
    return fingerprint(payload, empty_payload=payload is None)


def response_fingerprint(value: Any) -> str:
    return fingerprint(value, empty_payload=value is None)
