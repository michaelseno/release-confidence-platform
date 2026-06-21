"""Fail-closed Phase 4 evidence integrity validation gate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from release_confidence_platform.aggregation.eligibility import validate_eligibility
from release_confidence_platform.aggregation.models import RawAggregationRecord
from release_confidence_platform.core.exceptions import ValidationError


@dataclass(frozen=True)
class EvidenceIntegrityResult:
    expected_execution_count: int
    source_run_count: int
    source_raw_result_count: int


def validate_evidence_integrity(
    *,
    audit: dict[str, Any],
    runs: list[dict[str, Any]],
    records: list[RawAggregationRecord],
    audit_execution_id: str | None,
    config_version: str | None,
) -> EvidenceIntegrityResult:
    """Validate all required evidence gates before computation or writes."""

    validate_eligibility(audit)
    if not audit_execution_id:
        raise ValidationError("Missing audit_execution_id", "MISSING_AUDIT_EXECUTION_ID")
    if not config_version:
        raise ValidationError("Missing config_version", "MISSING_CONFIG_VERSION")

    finalization = audit.get("finalization")
    expected = finalization.get("execution_count") if isinstance(finalization, dict) else None
    if not isinstance(expected, int) or isinstance(expected, bool) or expected <= 0:
        raise ValidationError("Incomplete execution evidence", "INCOMPLETE_EXECUTION_EVIDENCE")

    if not runs:
        raise ValidationError("Missing completed run evidence", "MISSING_RAW_EVIDENCE")
    if not records:
        raise ValidationError("Missing raw evidence", "MISSING_RAW_EVIDENCE")
    if expected != len(runs):
        raise ValidationError(
            "Execution count does not match completed runs",
            "EXECUTION_COUNT_MISMATCH_COMPLETED_RUNS",
        )

    expected_run_ids = {run["run_id"] for run in runs}
    record_run_ids = {r.run_id for r in records}

    # Every endpoint-level record must belong to a known completed run.
    if not record_run_ids.issubset(expected_run_ids):
        raise ValidationError(
            "Raw result records reference unknown runs",
            "ORPHANED_RAW_RESULT_RECORDS",
        )
    # Every completed run must have contributed at least one evidence record (1 envelope each).
    if not expected_run_ids.issubset(record_run_ids):
        raise ValidationError(
            "Execution count does not match raw results",
            "EXECUTION_COUNT_MISMATCH_RAW_RESULTS",
        )

    seen = set()
    for record in records:
        if record.ref_identity in seen:
            raise ValidationError(
                "Duplicate raw result reference", "DUPLICATE_RAW_RESULT_REFERENCE"
            )
        seen.add(record.ref_identity)
        if (
            record.raw_result_version != "v1"
            or not record.run_id
            or not record.raw_result_s3_key
            or record.result_index < 0
            or not record.endpoint_id
        ):
            raise ValidationError("Lineage incomplete", "LINEAGE_INCOMPLETE")

    return EvidenceIntegrityResult(
        expected_execution_count=expected,
        source_run_count=len(runs),
        source_raw_result_count=len(records),
    )
