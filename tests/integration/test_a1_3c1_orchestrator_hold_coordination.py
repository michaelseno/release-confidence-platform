"""Evidence Governance Workstream A1.3c.1 — orchestrator-level integration
coverage exercising the REAL AggregationRepository (not a MemoryRepo fake)
through the corrected 31/32-endpoint transaction budget (Technical Design
Section 19.16.1/19.16.4) and the lineage-page reconciliation path
(_write_lineage_pages, Section 19.4/19.16.5).
"""

from __future__ import annotations

import pytest

from release_confidence_platform.aggregation.orchestrator import AggregationOrchestrator
from release_confidence_platform.aggregation.repository import AggregationRepository
from release_confidence_platform.core.exceptions import ValidationError
from release_confidence_platform.evidence_retention.hold_coordination import (
    HoldStateConcurrencyExceededError,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from tests.unit.aggregation._hold_coordination_double import (
    RecordingHoldAwareClient,
    place_hold,
)

CLIENT_ID = "client"
AUDIT_ID = "audit"


class MemoryS3:
    def __init__(self, objects):
        self.objects = objects

    def read_json(self, key):
        return self.objects[key]


def _eligible_audit(**overrides):
    audit = {
        "client_id": CLIENT_ID,
        "audit_id": AUDIT_ID,
        "lifecycle_state": "COMPLETED",
        "audit_execution_id": "audexec_123",
        "config_version": "config_v1",
        "finalization": {"execution_count": 1, "zero_execution": False},
        "lifecycle_history": [{"to_state": "COMPLETED", "reason": "finalization_completed"}],
    }
    audit.update(overrides)
    return audit


def _runs_with_distinct_endpoints(n: int):
    """n runs, each contributing exactly one raw result to its OWN distinct
    endpoint -- produces exactly n distinct endpoints, so the aggregate
    set's governed-item count is exactly 4 + 3n (Technical Design Section
    19.16)."""
    runs = []
    objects = {}
    for i in range(n):
        run_id = f"run_{i:06d}"
        endpoint_id = f"endpoint_{i:03d}"
        key = f"raw-results/{CLIENT_ID}/{AUDIT_ID}/{run_id}/results.json"
        runs.append(
            {
                "run_id": run_id,
                "status": "COMPLETED",
                "raw_result_version": "v1",
                "raw_result_s3_key": key,
            }
        )
        objects[key] = {
            "raw_result_version": "v1",
            "client_id": CLIENT_ID,
            "audit_id": AUDIT_ID,
            "run_id": run_id,
            "results": [
                {
                    "endpoint_id": endpoint_id,
                    "failure_type": "PASS",
                    "status_code": 200,
                    "duration_ms": 1,
                    "timestamp": "2026-06-21T13:23:02.511097Z",
                }
            ],
        }
    return runs, objects


def _seed_audit_and_runs(client, audit, runs):
    """Directly seed the real AggregationRepository's backing store with the
    audit metadata and completed RunMetadata records this orchestrator run
    needs -- bypassing Phase 1/2's own write paths, which are out of this
    subphase's scope."""
    from release_confidence_platform.storage.dynamodb_codec import encode_item

    audit_key = {"PK": f"CLIENT#{CLIENT_ID}", "SK": f"AUDIT#{AUDIT_ID}"}
    client.storage[(audit_key["PK"], audit_key["SK"])] = encode_item({**audit_key, **audit})
    for run in runs:
        run_key = {"PK": f"CLIENT#{CLIENT_ID}", "SK": f"AUDIT#{AUDIT_ID}#RUN#{run['run_id']}"}
        client.storage[(run_key["PK"], run_key["SK"])] = encode_item({**run_key, **run})


def _run_real_aggregation(n_endpoints: int, *, hold_before: bool = False):
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repository = AggregationRepository("metadata-table", client, hold_repository)
    runs, objects = _runs_with_distinct_endpoints(n_endpoints)
    audit = _eligible_audit(
        finalization={"execution_count": n_endpoints, "zero_execution": False}
    )
    _seed_audit_and_runs(client, audit, runs)
    if hold_before:
        place_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=1)

    orchestrator = AggregationOrchestrator(repository=repository, s3_storage=MemoryS3(objects))
    result = orchestrator.run(
        {
            "client_id": CLIENT_ID,
            "audit_id": AUDIT_ID,
            "aggregation_version": "agg_v1",
            "aggregation_job_id": "job_1",
        }
    )
    return result, client, repository


def test_31_endpoints_produces_98_item_transaction_and_succeeds():
    result, client, _ = _run_real_aggregation(31)

    assert result["status"] == "COMPLETED"
    # 4 + 3*31 = 97 governed Puts + 1 appended LegalHold ConditionCheck = 98.
    assert len(client.transact_calls[-1]) == 98


def test_32_endpoints_rejected_before_any_aws_request():
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repository = AggregationRepository("metadata-table", client, hold_repository)
    runs, objects = _runs_with_distinct_endpoints(32)
    audit = _eligible_audit(finalization={"execution_count": 32, "zero_execution": False})
    _seed_audit_and_runs(client, audit, runs)

    orchestrator = AggregationOrchestrator(repository=repository, s3_storage=MemoryS3(objects))

    result = orchestrator.run(
        {
            "client_id": CLIENT_ID,
            "audit_id": AUDIT_ID,
            "aggregation_version": "agg_v1",
            "aggregation_job_id": "job_1",
        }
    )

    # AggregationOrchestrator.run() catches ValidationError internally and
    # returns a FAILED result dict rather than propagating -- the 100-item
    # (4 + 3*32) governed set is rejected by _build_persisted_records'
    # existing MAX_AGGREGATE_RECORDS check before AggregationRepository is
    # ever called.
    assert result["status"] == "FAILED"
    assert result["reason_code"] == "AGGREGATE_SET_TOO_LARGE"
    # Zero LegalHold reads specifically (the item-count rejection happens in
    # _build_persisted_records, entirely before AggregationRepository's
    # governed write methods -- and therefore before any hold-state read --
    # are ever reached). Other, unrelated get_item calls (audit metadata,
    # execution identity, aggregate_set_exists probing) are expected and out
    # of scope for this assertion.
    hold_reads = [call for call in client.get_item_calls if call["SK"]["S"].endswith("LEGALHOLD")]
    assert hold_reads == [], "zero hold reads -- rejected in _build_persisted_records"
    assert client.transact_calls == [], "zero AWS calls on 32-endpoint rejection"


def test_31_endpoints_under_active_hold_omits_ttl_disposal_at():
    result, client, _ = _run_real_aggregation(31, hold_before=True)

    assert result["status"] == "COMPLETED"
    audit_agg_key = None
    for (pk, sk), _item in client.storage.items():
        if sk.endswith("#AUDIT") and "LEGALHOLD" not in sk:
            audit_agg_key = (pk, sk)
            break
    assert audit_agg_key is not None
    assert "ttl_disposal_at" not in client.storage[audit_agg_key]
    assert client.storage[audit_agg_key]["evidence_class"]["S"] == "aggregate_metadata"


# ---------------------------------------------------------------------------
# Lineage-page reconciliation through _write_lineage_pages
# ---------------------------------------------------------------------------


def test_lineage_page_write_success_and_identical_hash_retry_is_idempotent():
    """A retry with the SAME page_hash after a partial prior success must be
    accepted (idempotent resume), not treated as a conflict."""
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repository = AggregationRepository("metadata-table", client, hold_repository)

    page = {
        "PK": f"CLIENT#{CLIENT_ID}",
        "SK": f"AUDIT#{AUDIT_ID}#LINEAGE#audit#PAGE#0",
        "page_hash": "hash-1",
        "manifest_scope": "audit",
        "page_index": 0,
    }
    from release_confidence_platform.aggregation.orchestrator import AggregationOrchestrator as _AO

    orchestrator = _AO(repository=repository, s3_storage=MemoryS3({}))
    orchestrator._write_lineage_pages([page], client_id=CLIENT_ID, audit_id=AUDIT_ID)
    # Retry with the identical page (same page_hash) must not raise.
    orchestrator._write_lineage_pages([page], client_id=CLIENT_ID, audit_id=AUDIT_ID)

    stored = client.storage[(page["PK"], page["SK"])]
    assert stored["page_hash"]["S"] == "hash-1"


def test_lineage_page_conflicting_hash_raises_hash_mismatch():
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repository = AggregationRepository("metadata-table", client, hold_repository)

    from release_confidence_platform.aggregation.orchestrator import AggregationOrchestrator as _AO

    key = {"PK": f"CLIENT#{CLIENT_ID}", "SK": f"AUDIT#{AUDIT_ID}#LINEAGE#audit#PAGE#0"}
    page_a = {**key, "page_hash": "hash-1", "manifest_scope": "audit", "page_index": 0}
    page_b = {**key, "page_hash": "hash-2", "manifest_scope": "audit", "page_index": 0}

    orchestrator = _AO(repository=repository, s3_storage=MemoryS3({}))
    orchestrator._write_lineage_pages([page_a], client_id=CLIENT_ID, audit_id=AUDIT_ID)

    with pytest.raises(ValidationError) as exc_info:
        orchestrator._write_lineage_pages([page_b], client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert exc_info.value.error_type == "LINEAGE_PAGE_HASH_MISMATCH"


def test_lineage_page_hold_only_race_transparently_retried():
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repository = AggregationRepository("metadata-table", client, hold_repository)
    from release_confidence_platform.aggregation.orchestrator import AggregationOrchestrator as _AO

    page = {
        "PK": f"CLIENT#{CLIENT_ID}",
        "SK": f"AUDIT#{AUDIT_ID}#LINEAGE#audit#PAGE#0",
        "page_hash": "hash-1",
        "manifest_scope": "audit",
        "page_index": 0,
    }
    # Fail only the hold-check (index 1 of a 2-item transaction) on attempt 1.
    client.force_fail_indices_by_attempt = {1: {1}}

    orchestrator = _AO(repository=repository, s3_storage=MemoryS3({}))
    orchestrator._write_lineage_pages([page], client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert len(client.transact_calls) == 2
    assert (page["PK"], page["SK"]) in client.storage


def test_lineage_page_retry_exhaustion_fails_closed():
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repository = AggregationRepository("metadata-table", client, hold_repository)
    from release_confidence_platform.aggregation.orchestrator import AggregationOrchestrator as _AO

    page = {
        "PK": f"CLIENT#{CLIENT_ID}",
        "SK": f"AUDIT#{AUDIT_ID}#LINEAGE#audit#PAGE#0",
        "page_hash": "hash-1",
        "manifest_scope": "audit",
        "page_index": 0,
    }
    client.force_fail_indices_by_attempt = {1: {1}, 2: {1}, 3: {1}}

    orchestrator = _AO(repository=repository, s3_storage=MemoryS3({}))
    with pytest.raises(HoldStateConcurrencyExceededError):
        orchestrator._write_lineage_pages([page], client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert (page["PK"], page["SK"]) not in client.storage, "no partial write observable"


def test_lineage_page_governed_conflict_raises_conditional_write_error_not_masked():
    """A genuine duplicate page write (governed condition failure) must
    surface through _write_lineage_pages's own reconciliation logic (hash
    comparison), not be silently retried as a hold race."""
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repository = AggregationRepository("metadata-table", client, hold_repository)
    from release_confidence_platform.aggregation.orchestrator import AggregationOrchestrator as _AO

    key = {"PK": f"CLIENT#{CLIENT_ID}", "SK": f"AUDIT#{AUDIT_ID}#LINEAGE#audit#PAGE#0"}
    page_a = {**key, "page_hash": "hash-1", "manifest_scope": "audit", "page_index": 0}
    page_b = {**key, "page_hash": "hash-2", "manifest_scope": "audit", "page_index": 0}

    orchestrator = _AO(repository=repository, s3_storage=MemoryS3({}))
    orchestrator._write_lineage_pages([page_a], client_id=CLIENT_ID, audit_id=AUDIT_ID)

    # Force BOTH the governed item and the hold-check to fail in the same
    # attempt -- the governed failure must still win (surfaced as
    # LINEAGE_PAGE_HASH_MISMATCH via the orchestrator's own reconciliation,
    # never masked as a hold-version retry).
    with pytest.raises(ValidationError) as exc_info:
        orchestrator._write_lineage_pages([page_b], client_id=CLIENT_ID, audit_id=AUDIT_ID)
    assert exc_info.value.error_type == "LINEAGE_PAGE_HASH_MISMATCH"
    assert len(client.transact_calls) == 2, "governed conflict must never trigger a hold retry"
