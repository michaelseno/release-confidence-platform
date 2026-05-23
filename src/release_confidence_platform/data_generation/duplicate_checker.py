"""Run-scoped duplicate checker for Phase 2 payload generation."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from release_confidence_platform.core.time import utc_now_iso

SUPPORTED_DUPLICATE_POLICIES = {"regenerate", "fail_fast", "allow"}
SUPPORTED_DUPLICATE_SCOPES = {"current_run"}
DEFAULT_DUPLICATE_POLICY = "regenerate"
DEFAULT_DUPLICATE_SCOPE = "current_run"
MAX_GENERATION_ATTEMPTS = 5


@dataclass(frozen=True)
class DuplicateReservation:
    duplicate_detected: bool
    existing_metadata: dict[str, Any] | None = None


class DuplicateChecker:
    def __init__(self, *, client_id: str, audit_id: str, run_id: str):
        self.scope_key = (client_id, audit_id, run_id)
        self._lock = threading.Lock()
        self._reservations: dict[tuple[str, tuple[str, str, str], str, str], dict[str, Any]] = {}

    def check_and_reserve(
        self,
        *,
        scope: str,
        fingerprint: str,
        duplicate_subject_type: str,
        endpoint_id: str,
        iteration: int,
        payload_strategy: str,
    ) -> DuplicateReservation:
        if scope not in SUPPORTED_DUPLICATE_SCOPES:
            raise ValueError(f"Unsupported duplicate scope: {scope}")
        key = (scope, self.scope_key, duplicate_subject_type, fingerprint)
        with self._lock:
            existing = self._reservations.get(key)
            if existing is not None:
                return DuplicateReservation(True, existing)
            self._reservations[key] = {
                "fingerprint": fingerprint,
                "endpoint_id": endpoint_id,
                "iteration": iteration,
                "payload_strategy": payload_strategy,
                "reserved_at": utc_now_iso(),
            }
            return DuplicateReservation(False, None)


def normalize_duplicate_policy(value: Any) -> str:
    policy = DEFAULT_DUPLICATE_POLICY if value is None else value
    if policy not in SUPPORTED_DUPLICATE_POLICIES:
        raise ValueError("Invalid duplicate_policy")
    return policy


def normalize_duplicate_scope(value: Any) -> str:
    scope = DEFAULT_DUPLICATE_SCOPE if value is None else value
    if scope not in SUPPORTED_DUPLICATE_SCOPES:
        raise ValueError("Unsupported duplicate_check_scope")
    return scope
