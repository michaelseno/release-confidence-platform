"""Evidence Governance Workstream A1.3b -- AggregationRepository.update_job
retention-governed-field denylist guard (Technical Design Section 18.7).

AggregationJob is Category 3 (operational coordination metadata, Technical
Design Section 18.1) and is permanently excluded from custody-field
treatment. update_job accepts a caller-supplied `dict[str, Any]` with no
field allowlist otherwise, so the guard below is the only thing stopping a
future caller from smuggling ttl_disposal_at/custody_expires_at through it.
"""

from __future__ import annotations

from typing import Any

import pytest

from release_confidence_platform.aggregation.repository import AggregationRepository


@pytest.mark.parametrize("forbidden_field", ["ttl_disposal_at", "custody_expires_at"])
def test_update_job_rejects_retention_governed_fields(forbidden_field: str) -> None:
    repo = AggregationRepository("table", None)

    with pytest.raises(AssertionError, match=forbidden_field):
        repo.update_job(
            {"PK": "CLIENT#c1", "SK": "AUDIT#a1#AGGJOB#j1"},
            {forbidden_field: 1753000000, "status": "COMPLETED"},
        )


def test_update_job_rejects_when_both_retention_governed_fields_present() -> None:
    repo = AggregationRepository("table", None)

    with pytest.raises(AssertionError):
        repo.update_job(
            {"PK": "CLIENT#c1", "SK": "AUDIT#a1#AGGJOB#j1"},
            {"ttl_disposal_at": 1, "custody_expires_at": 2, "status": "FAILED"},
        )


def test_update_job_guard_raises_before_any_dynamodb_call() -> None:
    """dynamodb_client is intentionally None -- if the guard did not raise
    before reaching _call(), this would blow up with an unrelated
    AttributeError instead of the expected AssertionError, so a passing
    AssertionError here also proves the rejection happens pre-write."""
    repo = AggregationRepository("table", None)

    with pytest.raises(AssertionError):
        repo.update_job(
            {"PK": "CLIENT#c1", "SK": "AUDIT#a1#AGGJOB#j1"},
            {"ttl_disposal_at": 1},
        )


class _RecordingDynamoClient:
    """Minimal low-level-shaped stub recording update_item calls, so the
    "does not raise for real caller field sets" tests can exercise
    update_job's real UpdateExpression construction end to end."""

    def __init__(self) -> None:
        self.update_item_calls: list[dict[str, Any]] = []

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.update_item_calls.append(kwargs)
        return {}


# Exact field sets release_confidence_platform/aggregation/orchestrator.py's
# real callers pass to update_job today -- read directly from that module
# (not guessed) as required by this subphase's instructions:
#   - lines ~114-121: job claim -> STARTED
#   - lines ~144-147: execution-identity/config-version attach
#   - lines ~363-378: failure path
#   - lines ~752-764: _complete_job (the 9-field call)
_REAL_UPDATE_JOB_CALL_FIELD_SETS: list[dict[str, Any]] = [
    {
        "status": "STARTED",
        "started_at": "2026-07-21T00:00:00Z",
        "reason_code": None,
        "failure_category": None,
    },
    {
        "audit_execution_id": "exec_1",
        "config_version": "v1",
    },
    {
        "status": "FAILED",
        "reason_code": "SOME_REASON",
        "failure_category": "some_category",
        "completed_at": "2026-07-21T00:10:00Z",
        "source_run_count": 3,
        "source_raw_result_count": 3,
        "error_summary": {
            "reason_code": "SOME_REASON",
            "component": "AggregationOrchestrator",
            "aggregation_job_id": "job_1",
        },
    },
    {
        "status": "COMPLETED",
        "reason_code": None,
        "failure_category": None,
        "completed_at": "2026-07-21T00:10:00Z",
        "source_run_count": 3,
        "source_raw_result_count": 3,
        "aggregate_record_count": 5,
        "lineage_manifest_ref": "manifest_ref",
        "aggregate_set_ref": "aggregate_set_ref",
    },
]


@pytest.mark.parametrize("updates", _REAL_UPDATE_JOB_CALL_FIELD_SETS)
def test_update_job_does_not_raise_for_real_caller_field_sets(updates: dict[str, Any]) -> None:
    client = _RecordingDynamoClient()
    repo = AggregationRepository("table", client)

    repo.update_job({"PK": "CLIENT#c1", "SK": "AUDIT#a1#AGGJOB#j1"}, updates)

    assert len(client.update_item_calls) == 1
