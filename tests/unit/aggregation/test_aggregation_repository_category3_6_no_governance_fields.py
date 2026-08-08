"""Evidence Governance Workstream A1.3e -- negative regression coverage for
the remaining `AggregationRepository` write paths not already covered by
`test_update_job_custody_guard.py` (Technical Design Section 18.1, 18.3).

Two categories from the six-way classification (Section 18.1) are exercised
here, both governed by `AggregationRepository`:

- Category 3 (operational coordination metadata): `AggregationJob`
  (`put_job_once`, item 6). Permanently excluded from custody-field
  treatment.
- Category 6 (`AuditExecutionIdentity`, item 9): `put_audit_execution_identity_once`
  -- a one-line delegate to `_put_once`, sharing its production class with
  `AggregationJob`/`update_job`, hence covered in this file rather than
  alongside `AuditMetadataRepository`'s own Category 6 coverage (which
  governs `AuditMetadata`, a structurally distinct record type in a
  different repository class).

This file also extends the already-merged, narrowly-authorized
`update_job` runtime denylist guard's own regression proof
(`test_update_job_custody_guard.py`, Technical Design Section 18.7) from
its existing 2-element check (`ttl_disposal_at`/`custody_expires_at`) to
the full 4-element governance-field set, at the same method, same
boundary, over the SAME real caller field sets already derived from
`aggregation/orchestrator.py` -- this does not modify `update_job`'s
existing guard or add a new one; it is additional proof that the guard's
existing, narrower field set also happens to hold for the two fields it
does not explicitly check (`evidence_class`, `hold_version`), across every
field set `update_job`'s real callers actually pass today.

Per Section 18.3, `put_job_once`/`put_audit_execution_identity_once` have
no runtime guard at all (unlike `update_job`) -- their write methods are
existing, locked code this workstream does not modify, and their Category
3/6 semantics already prevent the invariant by simple omission. Test-level
enforcement, as here, is Section 18.3's chosen mechanism for exactly this
situation.
"""

from __future__ import annotations

from typing import Any

import pytest

from release_confidence_platform.aggregation.repository import AggregationRepository

try:
    # Reuse the exact real caller field sets test_update_job_custody_guard.py
    # already carefully derived from aggregation/orchestrator.py, rather
    # than silently diverging from them. Confirmed importable given this
    # repo's pytest pythonpath config (pyproject.toml
    # [tool.pytest.ini_options] pythonpath = ["src", "."]), which puts the
    # repo root on sys.path and makes `tests` resolve as an implicit
    # namespace package.
    from tests.unit.aggregation.test_update_job_custody_guard import (
        _REAL_UPDATE_JOB_CALL_FIELD_SETS,
    )
except ImportError:  # pragma: no cover - defensive fallback, not expected to trigger
    # Intentionally kept identical to test_update_job_custody_guard.py's own
    # fixture (lines ~75-110 there, read directly from
    # aggregation/orchestrator.py's real update_job call sites: job claim ->
    # STARTED, execution-identity/config-version attach, the failure path,
    # and _complete_job's 9-field call).
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


class _RecordingDynamoClient:
    """Minimal low-level-shaped stub recording put_item/update_item calls,
    identical in style to test_update_job_custody_guard.py's own
    `_RecordingDynamoClient`.
    """

    def __init__(self) -> None:
        self.put_item_calls: list[dict[str, Any]] = []
        self.update_item_calls: list[dict[str, Any]] = []

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        self.put_item_calls.append(kwargs)
        return {}

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.update_item_calls.append(kwargs)
        return {}


# Category 3 -- AggregationJob (item 6).


def test_put_job_once_carries_no_governance_fields() -> None:
    client = _RecordingDynamoClient()
    repo = AggregationRepository("table", client)

    item = {
        "PK": "CLIENT#c1",
        "SK": "AUDIT#a1#AGGJOB#job1",
        "client_id": "c1",
        "audit_id": "a1",
        "aggregation_job_id": "job1",
        "status": "PENDING",
        "created_at": "2026-07-21T00:00:00Z",
    }

    repo.put_job_once(item)

    assert len(client.put_item_calls) == 1
    captured_item = client.put_item_calls[0]["Item"]
    for field in ("custody_expires_at", "ttl_disposal_at", "evidence_class", "hold_version"):
        assert field not in captured_item, (
            f"unexpected governance field {field!r} present in put_job_once's PutItem Item"
        )


# Category 6 -- AuditExecutionIdentity (item 9).


def test_put_audit_execution_identity_once_carries_no_governance_fields() -> None:
    client = _RecordingDynamoClient()
    repo = AggregationRepository("table", client)

    item = {
        "PK": "CLIENT#c1",
        "SK": "AUDIT#a1#EXECUTION_ID",
        "client_id": "c1",
        "audit_id": "a1",
        "audit_execution_id": "exec_1",
        "config_version": "v1",
        "created_at": "2026-07-21T00:00:00Z",
    }

    repo.put_audit_execution_identity_once(item)

    assert len(client.put_item_calls) == 1
    captured_item = client.put_item_calls[0]["Item"]
    for field in ("custody_expires_at", "ttl_disposal_at", "evidence_class", "hold_version"):
        assert field not in captured_item, (
            "unexpected governance field "
            f"{field!r} present in put_audit_execution_identity_once's PutItem Item"
        )


# Category 3 -- AggregationJob.update_job (item 7), extending the
# already-merged runtime guard's own regression proof to the full 4-element
# governance-field set. Does not modify update_job's existing denylist
# guard (Technical Design Section 18.7) -- exercises the real,
# already-passing (2-element-checked) method and additionally verifies
# `evidence_class`/`hold_version` never leak through it either, for every
# real caller field set the guard test file itself proved does not raise.


@pytest.mark.parametrize("updates", _REAL_UPDATE_JOB_CALL_FIELD_SETS)
def test_update_job_does_not_leak_evidence_class_or_hold_version_for_real_caller_field_sets(
    updates: dict[str, Any],
) -> None:
    client = _RecordingDynamoClient()
    repo = AggregationRepository("table", client)

    repo.update_job({"PK": "CLIENT#c1", "SK": "AUDIT#a1#AGGJOB#job1"}, updates)

    assert len(client.update_item_calls) == 1
    mapped_field_names = set(client.update_item_calls[0]["ExpressionAttributeNames"].values())
    assert "evidence_class" not in mapped_field_names
    assert "hold_version" not in mapped_field_names
