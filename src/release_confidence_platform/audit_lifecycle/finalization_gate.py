"""Finalization integrity gate — pure function, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from release_confidence_platform.core.constants.engine import (
    RAW_RESULT_KEY_TEMPLATE,
    RUN_STATUS_STARTED,
    RUN_STATUSES,
)
from release_confidence_platform.core.time import utc_now_iso

# ---------------------------------------------------------------------------
# Check name constants
# ---------------------------------------------------------------------------

CHECK_TERMINAL_COUNT_MATCHES_EXPECTED = "TERMINAL_COUNT_MATCHES_EXPECTED"
CHECK_NO_ORPHANED_STARTED_RECORDS = "NO_ORPHANED_STARTED_RECORDS"
CHECK_EVERY_TERMINAL_RUN_HAS_EVIDENCE = "EVERY_TERMINAL_RUN_HAS_EVIDENCE"
CHECK_EVERY_EVIDENCE_MAPS_TO_ONE_RUN = "EVERY_EVIDENCE_MAPS_TO_ONE_RUN"
CHECK_NO_ORPHAN_EVIDENCE = "NO_ORPHAN_EVIDENCE"
CHECK_COUNTER_RECONCILIATION = "COUNTER_RECONCILIATION"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CheckFailure:
    check: str
    expected: int | None
    actual: int | None
    detail: str


@dataclass
class GateResult:
    passed: bool
    failures: list[CheckFailure] = field(default_factory=list)
    timestamp: str = field(default_factory=utc_now_iso)


class FinalizationGateError(Exception):
    """Raised by the finalization handler when the gate returns passed=False."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__("Finalization integrity gate failed")
        self.payload = payload


# ---------------------------------------------------------------------------
# Terminal status set — derived from RUN_STATUSES, never hardcoded
# ---------------------------------------------------------------------------

_TERMINAL_RUN_STATUSES: frozenset[str] = frozenset(
    s for s in RUN_STATUSES if s != RUN_STATUS_STARTED
)


# ---------------------------------------------------------------------------
# Gate function
# ---------------------------------------------------------------------------


def finalization_integrity_gate(
    *,
    audit: dict[str, Any],
    run_records: list[dict[str, Any]],
    s3_evidence_keys: list[str],
    client_id: str,
    audit_id: str,
) -> GateResult:
    """Evaluate all six finalization integrity checks.

    Pure function — no DynamoDB or S3 calls, no writes, no side effects.

    Raises ValueError for structurally invalid inputs (programming error).
    Returns GateResult with passed=True only when all six checks pass.
    Collects ALL failures without short-circuiting.
    """
    # ------------------------------------------------------------------
    # Input structural validation
    # ------------------------------------------------------------------
    if not audit or not isinstance(audit, dict):
        raise ValueError("audit must be a non-empty dict")
    if not isinstance(run_records, list):
        raise ValueError("run_records must be a list")
    if not isinstance(s3_evidence_keys, list):
        raise ValueError("s3_evidence_keys must be a list")

    finalization = audit.get("finalization") or {}
    execution_count = finalization.get("execution_count")
    if execution_count is None or not _is_valid_positive_int(execution_count):
        raise ValueError(
            f"audit.finalization.execution_count must be a valid integer > 0; got {execution_count!r}"
        )

    expected_terminal_count = int(execution_count)

    # ------------------------------------------------------------------
    # Pre-classify run records
    # ------------------------------------------------------------------
    terminal_runs: list[dict[str, Any]] = [
        r for r in run_records if r.get("status") in _TERMINAL_RUN_STATUSES
    ]
    started_runs: list[dict[str, Any]] = [
        r for r in run_records if r.get("status") == RUN_STATUS_STARTED
    ]

    # Build lookup: run_id -> list of terminal run records
    terminal_run_id_map: dict[str, list[dict[str, Any]]] = {}
    for run in terminal_runs:
        rid = run.get("run_id", "")
        terminal_run_id_map.setdefault(rid, []).append(run)

    # Build lookup: run_id -> list of ALL run records (for Check 4)
    all_run_id_map: dict[str, list[dict[str, Any]]] = {}
    for run in run_records:
        rid = run.get("run_id", "")
        all_run_id_map.setdefault(rid, []).append(run)

    failures: list[CheckFailure] = []

    # ------------------------------------------------------------------
    # Check 1: Terminal count matches expected (finalization.execution_count)
    # ------------------------------------------------------------------
    actual_terminal_count = len(terminal_runs)
    if actual_terminal_count != expected_terminal_count:
        failures.append(
            CheckFailure(
                check=CHECK_TERMINAL_COUNT_MATCHES_EXPECTED,
                expected=expected_terminal_count,
                actual=actual_terminal_count,
                detail=(
                    f"Expected {expected_terminal_count} terminal RUN records "
                    f"(finalization.execution_count), found {actual_terminal_count} "
                    "terminal RUN records in DynamoDB"
                ),
            )
        )

    # ------------------------------------------------------------------
    # Check 2: No orphaned STARTED records
    # ------------------------------------------------------------------
    started_count = len(started_runs)
    if started_count != 0:
        started_ids = [r.get("run_id", "<unknown>") for r in started_runs]
        failures.append(
            CheckFailure(
                check=CHECK_NO_ORPHANED_STARTED_RECORDS,
                expected=0,
                actual=started_count,
                detail=(
                    f"{started_count} RUN record{'s' if started_count != 1 else ''} "
                    f"remain{'s' if started_count == 1 else ''} in STARTED state: "
                    + ", ".join(started_ids)
                ),
            )
        )

    # ------------------------------------------------------------------
    # Check 3: Every terminal RUN has a corresponding S3 evidence key
    # ------------------------------------------------------------------
    s3_key_set: frozenset[str] = frozenset(s3_evidence_keys)
    for run in terminal_runs:
        run_id = run.get("run_id", "")
        expected_key = RAW_RESULT_KEY_TEMPLATE.format(
            client_id=client_id, audit_id=audit_id, run_id=run_id
        )
        if expected_key not in s3_key_set:
            failures.append(
                CheckFailure(
                    check=CHECK_EVERY_TERMINAL_RUN_HAS_EVIDENCE,
                    expected=None,
                    actual=None,
                    detail=(
                        f"1 terminal RUN record has no corresponding S3 evidence object: "
                        f"run_id={run_id}, searched_key={expected_key}"
                    ),
                )
            )

    # ------------------------------------------------------------------
    # Check 4: Every S3 evidence key maps to exactly one RUN record
    # ------------------------------------------------------------------
    for s3_key in s3_evidence_keys:
        s3_run_id = _extract_run_id_from_s3_key(s3_key)
        matching_runs = all_run_id_map.get(s3_run_id, [])
        count = len(matching_runs)
        if count != 1:
            failures.append(
                CheckFailure(
                    check=CHECK_EVERY_EVIDENCE_MAPS_TO_ONE_RUN,
                    expected=None,
                    actual=None,
                    detail=(
                        f"S3 evidence key {s3_key} has no matching RUN record ({count} found)"
                        if count == 0
                        else (
                            f"S3 evidence key {s3_key} maps to {count} RUN records "
                            f"(expected exactly 1)"
                        )
                    ),
                )
            )

    # ------------------------------------------------------------------
    # Check 5: No orphan evidence — every S3 key maps to a terminal RUN
    # ------------------------------------------------------------------
    for s3_key in s3_evidence_keys:
        s3_run_id = _extract_run_id_from_s3_key(s3_key)
        matching_runs = all_run_id_map.get(s3_run_id, [])
        # Only report if a run was found but it is not terminal
        for run in matching_runs:
            if run.get("status") == RUN_STATUS_STARTED:
                failures.append(
                    CheckFailure(
                        check=CHECK_NO_ORPHAN_EVIDENCE,
                        expected=None,
                        actual=None,
                        detail=(
                            f"S3 evidence key {s3_key} maps to a STARTED RUN record"
                        ),
                    )
                )
                break  # one failure per S3 key is enough

    # ------------------------------------------------------------------
    # Check 6: Counter reconciliation
    # ------------------------------------------------------------------
    execution_counters = audit.get("execution_counters") or {}
    counter_total_completed = execution_counters.get("total_completed")
    if counter_total_completed is not None:
        counter_value = int(counter_total_completed)
        if counter_value != actual_terminal_count:
            failures.append(
                CheckFailure(
                    check=CHECK_COUNTER_RECONCILIATION,
                    expected=actual_terminal_count,
                    actual=counter_value,
                    detail=(
                        f"Counter total_completed={counter_value} does not match "
                        f"terminal RUN record count={actual_terminal_count}"
                    ),
                )
            )

    timestamp = utc_now_iso()
    if failures:
        return GateResult(passed=False, failures=failures, timestamp=timestamp)
    return GateResult(passed=True, failures=[], timestamp=timestamp)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_run_id_from_s3_key(s3_key: str) -> str:
    """Extract the run_id path segment from an S3 evidence key.

    Convention: raw-results/{client_id}/{audit_id}/{run_id}/results.json
    Index (0-based after split): 0=raw-results, 1=client_id, 2=audit_id, 3=run_id
    """
    parts = s3_key.split("/")
    if len(parts) >= 4:
        return parts[3]
    return ""


def _is_valid_positive_int(value: Any) -> bool:
    """Return True if value is an integer-like type > 0."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value > 0
    try:
        from decimal import Decimal

        if isinstance(value, Decimal):
            return value == value.to_integral_value() and value > 0
    except Exception:
        pass
    return False
