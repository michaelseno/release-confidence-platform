"""Phase 4A.4 persistence unit tests.

AGG-P1 through AGG-P9 — named persistence correctness, idempotency,
and integrity-gate tests.
"""

import pytest
from botocore.exceptions import ClientError

from release_confidence_platform.aggregation.orchestrator import AggregationOrchestrator
from release_confidence_platform.aggregation.repository import (
    AggregationRepository,
    ConditionalWriteError,
)

# ---------------------------------------------------------------------------
# Helpers (duplicated from test_phase4_orchestrator.py to avoid import-path
# fragility — the originals live in the same package but path resolution is
# tricky when called from within the aggregation/ sub-directory).
# ---------------------------------------------------------------------------


class MemoryRepo:
    def __init__(self, audit, runs):
        self.audit = audit
        self.runs = runs
        self.items = {}

    def audit_keys(self, client_id, audit_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}"}

    def execution_identity_keys(self, client_id, audit_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#EXECUTION_ID"}

    def job_keys(self, client_id, audit_id, job_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#AGGJOB#{job_id}"}

    def aggregate_prefix(self, client_id, audit_id, exec_id, cfg, ver):
        return f"AUDIT#{audit_id}#EXEC#{exec_id}#CFG#{cfg}#AGG#{ver}"

    def get_audit_metadata(self, client_id, audit_id):
        return self.audit

    def get_audit_execution_identity(self, client_id, audit_id):
        return self.items.get((f"CLIENT#{client_id}", f"AUDIT#{audit_id}#EXECUTION_ID"))

    def put_audit_execution_identity_once(self, item):
        self._put(item)

    def put_job_once(self, item):
        self._put(item)

    def update_job(self, key, updates):
        self.items[(key["PK"], key["SK"])].update(updates)

    def get_job(self, key):
        return self.items.get((key["PK"], key["SK"]))

    def list_completed_runs(self, client_id, audit_id):
        return self.runs

    def aggregate_set_exists(self, client_id, audit_id, exec_id, cfg, ver):
        pk = f"CLIENT#{client_id}"
        prefix = f"AUDIT#{audit_id}#EXEC#{exec_id}#CFG#{cfg}#AGG#{ver}"
        return (pk, f"{prefix}#SET") in self.items

    def put_records_once(self, records):
        keys = [(item["PK"], item["SK"]) for item in records]
        if any(key in self.items for key in keys):
            raise ConditionalWriteError()
        for item in records:
            self._put(item)

    def put_lineage_page_once(self, item):
        self._put(item)

    def get_lineage_page(self, key):
        return self.items.get((key["PK"], key["SK"]))

    def _put(self, item):
        key = (item["PK"], item["SK"])
        if key in self.items:
            raise ConditionalWriteError()
        self.items[key] = item


class MemoryS3:
    def __init__(self, objects):
        self.objects = objects

    def read_json(self, key):
        return self.objects[key]


def eligible_audit(**overrides):
    audit = {
        "client_id": "client",
        "audit_id": "audit",
        "lifecycle_state": "COMPLETED",
        "audit_execution_id": "audexec_123",
        "config_version": "config_v1",
        "finalization": {"execution_count": 1, "zero_execution": False},
        "lifecycle_history": [{"to_state": "COMPLETED", "reason": "finalization_completed"}],
    }
    audit.update(overrides)
    return audit


def run_meta(run_id="run_12345678", key="raw-results/client/audit/run/results.json"):
    return {
        "run_id": run_id,
        "status": "COMPLETED",
        "raw_result_version": "v1",
        "raw_result_s3_key": key,
    }


def envelope(run_id="run_12345678", endpoint_id="endpoint_a"):
    return {
        "raw_result_version": "v1",
        "client_id": "client",
        "audit_id": "audit",
        "run_id": run_id,
        "results": [
            {
                "endpoint_id": endpoint_id,
                "failure_type": "PASS",
                "status_code": 200,
                "duration_ms": 42,
                "timestamp": "2026-06-07T00:00:00Z",
            }
        ],
    }


def _run(repo, s3, job_id="job_123"):
    return AggregationOrchestrator(repository=repo, s3_storage=s3).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "aggregation_version": "agg_v1",
            "aggregation_job_id": job_id,
        }
    )


# ---------------------------------------------------------------------------
# AGG-P1: write produces all required record types
# ---------------------------------------------------------------------------


def test_agg_p1_write_produces_all_required_record_types():
    """One successful run must produce every required record kind/type."""
    key = "raw-results/client/audit/run/results.json"
    repo = MemoryRepo(eligible_audit(), [run_meta(key=key)])
    s3 = MemoryS3({key: envelope("run_12345678", "endpoint_a")})

    result = _run(repo, s3)
    assert result["status"] == "COMPLETED"

    all_items = list(repo.items.values())

    audit_aggs = [i for i in all_items if i.get("aggregate_type") == "audit"]
    assert len(audit_aggs) == 1, "Expected exactly one audit aggregate"

    endpoint_aggs = [i for i in all_items if i.get("aggregate_type") == "endpoint"]
    assert len(endpoint_aggs) >= 1, "Expected at least one endpoint aggregate"

    fc_audit = [
        i
        for i in all_items
        if i.get("aggregate_type") == "failure_classification" and i.get("scope") == "audit"
    ]
    assert len(fc_audit) >= 1, "Expected at least one audit-scope failure_classification aggregate"

    audit_manifests = [
        i
        for i in all_items
        if i.get("record_kind") == "lineage_manifest" and i.get("manifest_scope") == "audit"
    ]
    assert len(audit_manifests) >= 1, "Expected at least one audit lineage_manifest"

    completion = [
        i for i in all_items if i.get("aggregate_type") == "aggregate_set_completion"
    ]
    assert len(completion) == 1, "Expected exactly one aggregate_set_completion marker"


# ---------------------------------------------------------------------------
# AGG-P2: duplicate trigger — same job_id returns DUPLICATE_COMPLETED
# ---------------------------------------------------------------------------


def test_agg_p2_duplicate_trigger_same_job_id_produces_duplicate_completed():
    """Second invocation with the same job_id must return DUPLICATE_COMPLETED."""
    key = "raw-results/client/audit/run/results.json"
    repo = MemoryRepo(eligible_audit(), [run_meta(key=key)])
    s3 = MemoryS3({key: envelope()})

    first = _run(repo, s3, job_id="job_123")
    assert first["status"] == "COMPLETED"

    second = _run(repo, s3, job_id="job_123")
    assert second["status"] == "DUPLICATE_COMPLETED"

    audit_aggs = [i for i in repo.items.values() if i.get("aggregate_type") == "audit"]
    assert len(audit_aggs) == 1, "Duplicate must not create a second audit aggregate"


# ---------------------------------------------------------------------------
# AGG-P3: new job_id for same audit set — returns DUPLICATE_COMPLETED
# ---------------------------------------------------------------------------


def test_agg_p3_new_job_id_same_aggregate_set_produces_duplicate_completed():
    """A new job_id targeting the same completed aggregate set must return DUPLICATE_COMPLETED."""
    key = "raw-results/client/audit/run/results.json"
    repo = MemoryRepo(eligible_audit(), [run_meta(key=key)])
    s3 = MemoryS3({key: envelope()})

    first = _run(repo, s3, job_id="job_123")
    assert first["status"] == "COMPLETED"

    second = _run(repo, s3, job_id="job_456")
    assert second["status"] == "DUPLICATE_COMPLETED"

    audit_aggs = [i for i in repo.items.values() if i.get("aggregate_type") == "audit"]
    assert len(audit_aggs) == 1, "New job_id must not create a second audit aggregate"


# ---------------------------------------------------------------------------
# AGG-P4: conditional write prevents overwrite via DynamoDB TransactWriteItems
# ---------------------------------------------------------------------------


class _FailOnSecondTransactClient:
    """Fake DynamoDB client that raises TransactionCanceledException on the 2nd call."""

    def __init__(self):
        self.call_count = 0

    def transact_write_items(self, *, TransactItems):
        self.call_count += 1
        if self.call_count > 1:
            raise ClientError(
                {
                    "Error": {
                        "Code": "TransactionCanceledException",
                        "Message": "conflict",
                    }
                },
                "TransactWriteItems",
            )
        return {}


def test_agg_p4_conditional_write_prevents_overwrite():
    """put_records_once must raise ConditionalWriteError on the second call."""
    client = _FailOnSecondTransactClient()
    repo = AggregationRepository("metadata-table", client)

    records = [
        {"PK": "CLIENT#c", "SK": "AUDIT#a#AUDIT", "value": 1},
        {"PK": "CLIENT#c", "SK": "AUDIT#a#SET", "value": 2},
    ]

    repo.put_records_once(records)  # first call succeeds

    with pytest.raises(ConditionalWriteError):
        repo.put_records_once(records)  # second call must raise


# ---------------------------------------------------------------------------
# AGG-P5: retry after pre-write failure produces exactly one aggregate set
# ---------------------------------------------------------------------------


class _FailFirstPutRepo(MemoryRepo):
    """Raises ConditionalWriteError on the very first put_records_once call."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._put_records_once_count = 0

    def put_records_once(self, records):
        self._put_records_once_count += 1
        if self._put_records_once_count == 1:
            raise ConditionalWriteError()
        super().put_records_once(records)


def test_agg_p5_retry_after_pre_write_failure_produces_exactly_one_aggregate_set():
    """After a first-call ConditionalWriteError then a successful retry, only one set exists."""
    key = "raw-results/client/audit/run/results.json"
    repo = _FailFirstPutRepo(eligible_audit(), [run_meta(key=key)])
    s3 = MemoryS3({key: envelope()})

    # First invocation: put_records_once raises -> aggregate_set_exists is False
    # -> orchestrator returns CONFLICT (AGGREGATE_SET_INCOMPLETE_CONFLICT)
    first = _run(repo, s3, job_id="job_123")
    assert first["status"] == "CONFLICT"
    assert first["reason_code"] == "AGGREGATE_SET_INCOMPLETE_CONFLICT"

    # Second invocation (new job_id): put_records_once succeeds -> COMPLETED
    second = _run(repo, s3, job_id="job_456")
    assert second["status"] == "COMPLETED"

    completion_markers = [
        i for i in repo.items.values() if i.get("aggregate_type") == "aggregate_set_completion"
    ]
    assert len(completion_markers) == 1, "Exactly one completion marker must exist after retry"


# ---------------------------------------------------------------------------
# AGG-P6: no completion marker when put_records_once always fails
# ---------------------------------------------------------------------------


class _AlwaysFailingPutRepo(MemoryRepo):
    """put_records_once always raises ConditionalWriteError; aggregate_set_exists always False."""

    def put_records_once(self, records):  # noqa: ARG002
        raise ConditionalWriteError()


def test_agg_p6_no_completion_marker_for_partial_sets():
    """When put_records_once always fails, no aggregate_set_completion must be persisted."""
    key = "raw-results/client/audit/run/results.json"
    repo = _AlwaysFailingPutRepo(eligible_audit(), [run_meta(key=key)])

    result = _run(repo, MemoryS3({key: envelope()}))

    assert result["status"] == "CONFLICT"

    completion_markers = [
        i for i in repo.items.values() if i.get("aggregate_type") == "aggregate_set_completion"
    ]
    assert len(completion_markers) == 0, "No completion marker must exist when write always fails"

    aggregate_items = [
        i for i in repo.items.values() if i.get("record_kind") == "aggregate"
    ]
    assert len(aggregate_items) == 0, "No aggregate records must exist when write always fails"


# ---------------------------------------------------------------------------
# AGG-P7: integrity gate blocks write on execution count mismatch
# ---------------------------------------------------------------------------


def test_agg_p7_integrity_gate_blocks_write_on_count_mismatch():
    """Execution count mismatch must produce FAILED with EXECUTION_COUNT_MISMATCH_COMPLETED_RUNS."""
    key = "raw-results/client/audit/run/results.json"
    # finalization says 2 runs are required, but only 1 run is provided
    repo = MemoryRepo(
        eligible_audit(finalization={"execution_count": 2, "zero_execution": False}),
        [run_meta(key=key)],
    )
    s3 = MemoryS3({key: envelope()})

    result = _run(repo, s3)

    assert result["status"] == "FAILED"
    assert result["reason_code"] == "EXECUTION_COUNT_MISMATCH_COMPLETED_RUNS"

    job = repo.items[("CLIENT#client", "AUDIT#audit#AGGJOB#job_123")]
    assert job["failure_category"] == "EVIDENCE_PRODUCING"

    aggregate_records = [
        i for i in repo.items.values() if i.get("record_kind") == "aggregate"
    ]
    assert len(aggregate_records) == 0, "No aggregate records must be written on integrity failure"


# ---------------------------------------------------------------------------
# AGG-P8: missing audit_execution_id blocks aggregation
# ---------------------------------------------------------------------------


class _MissingIdentityRepo(MemoryRepo):
    """Simulates failure to assign an audit execution identity."""

    def put_audit_execution_identity_once(self, item):  # noqa: ARG002
        raise RuntimeError("identity write unavailable")


def test_agg_p8_missing_audit_execution_id_blocks_aggregation():
    """When audit_execution_id cannot be resolved, aggregation must fail with the correct code."""
    key = "raw-results/client/audit/run/results.json"
    repo = _MissingIdentityRepo(
        eligible_audit(audit_execution_id=None),
        [run_meta(key=key)],
    )
    s3 = MemoryS3({key: envelope()})

    result = _run(repo, s3)

    assert result["status"] == "FAILED"
    assert result["reason_code"] == "MISSING_AUDIT_EXECUTION_ID"

    aggregate_records = [
        i for i in repo.items.values() if i.get("record_kind") == "aggregate"
    ]
    assert len(aggregate_records) == 0, "No aggregate records must be written when id is missing"


# ---------------------------------------------------------------------------
# AGG-P9: missing config_version blocks aggregation
# ---------------------------------------------------------------------------


def test_agg_p9_missing_config_version_blocks_aggregation():
    """When config_version is absent from the audit, aggregation must fail with the correct code."""
    key = "raw-results/client/audit/run/results.json"
    repo = MemoryRepo(
        eligible_audit(config_version=None),
        [run_meta(key=key)],
    )
    s3 = MemoryS3({key: envelope()})

    result = _run(repo, s3)

    assert result["status"] == "FAILED"
    assert result["reason_code"] == "MISSING_CONFIG_VERSION"

    aggregate_records = [
        i for i in repo.items.values() if i.get("record_kind") == "aggregate"
    ]
    assert len(aggregate_records) == 0, "No aggregate records must be written when version missing"


# ---------------------------------------------------------------------------
# AGG-R01: multi-endpoint envelope must produce COMPLETED, not mismatch error
# Regression for EXECUTION_COUNT_MISMATCH_RAW_RESULTS on multi-endpoint audits.
# ---------------------------------------------------------------------------


def test_agg_r01_multi_endpoint_envelope_succeeds():
    """One run whose S3 envelope contains two endpoint results must produce COMPLETED."""
    key = "raw-results/client/audit/run_12345678/results.json"
    multi_envelope = {
        "raw_result_version": "v1",
        "client_id": "client",
        "audit_id": "audit",
        "run_id": "run_12345678",
        "results": [
            {
                "endpoint_id": "endpoint_a",
                "failure_type": "PASS",
                "status_code": 200,
                "duration_ms": 42,
                "timestamp": "2026-06-07T00:00:00Z",
            },
            {
                "endpoint_id": "endpoint_b",
                "failure_type": "PASS",
                "status_code": 200,
                "duration_ms": 38,
                "timestamp": "2026-06-07T00:00:01Z",
            },
        ],
    }
    repo = MemoryRepo(eligible_audit(), [run_meta(key=key)])
    s3 = MemoryS3({key: multi_envelope})

    result = _run(repo, s3)

    assert result["status"] == "COMPLETED", (
        f"Multi-endpoint audit must succeed — got {result['status']} / {result.get('reason_code')}"
    )

    endpoint_aggs = [i for i in repo.items.values() if i.get("aggregate_type") == "endpoint"]
    assert len(endpoint_aggs) == 2, "Must produce one endpoint aggregate per distinct endpoint_id"


# ---------------------------------------------------------------------------
# AGG-R02: FAILED run counted in finalization.execution_count must fail at
# Check 1 (EXECUTION_COUNT_MISMATCH_COMPLETED_RUNS), not Check 2.
# ---------------------------------------------------------------------------


def test_agg_r02_failed_run_counted_in_expected_causes_check1_mismatch():
    """finalization.execution_count=2 but list_completed_runs returns 1 → MISMATCH_COMPLETED_RUNS."""
    key = "raw-results/client/audit/run/results.json"
    repo = MemoryRepo(
        eligible_audit(finalization={"execution_count": 2, "zero_execution": False}),
        [run_meta(key=key)],  # only 1 COMPLETED run — 1 FAILED run was counted in expected
    )
    s3 = MemoryS3({key: envelope()})

    result = _run(repo, s3)

    assert result["status"] == "FAILED"
    assert result["reason_code"] == "EXECUTION_COUNT_MISMATCH_COMPLETED_RUNS"

    aggregate_records = [i for i in repo.items.values() if i.get("record_kind") == "aggregate"]
    assert len(aggregate_records) == 0


# ---------------------------------------------------------------------------
# AGG-R03: orphaned record (run_id not in runs) raises ORPHANED_RAW_RESULT_RECORDS.
# Tests the new check added to validate_evidence_integrity.
# ---------------------------------------------------------------------------


from release_confidence_platform.aggregation.integrity import validate_evidence_integrity  # noqa: E402
from release_confidence_platform.aggregation.models import RawAggregationRecord  # noqa: E402
from release_confidence_platform.core.exceptions import ValidationError  # noqa: E402


def _make_record(run_id, endpoint_id="ep_a", index=0):
    return RawAggregationRecord(
        raw_result_version="v1",
        run_id=run_id,
        raw_result_s3_key=f"raw-results/client/audit/{run_id}/results.json",
        s3_version_id=None,
        result_index=index,
        endpoint_id=endpoint_id,
        result_timestamp=None,
        duration_ms=None,
        status_code=200,
        failure_type="PASS",
    )


def test_agg_r03_orphaned_record_raises_correct_error():
    """A record whose run_id is absent from runs must raise ORPHANED_RAW_RESULT_RECORDS."""
    known_run = run_meta(run_id="run_known", key="raw-results/client/audit/run_known/results.json")

    with pytest.raises(ValidationError) as exc_info:
        validate_evidence_integrity(
            audit=eligible_audit(),
            runs=[known_run],
            records=[
                _make_record("run_known"),
                _make_record("run_orphan"),  # not in runs → must trigger orphan check
            ],
            audit_execution_id="audexec_123",
            config_version="config_v1",
        )

    assert exc_info.value.error_type == "ORPHANED_RAW_RESULT_RECORDS"


# ---------------------------------------------------------------------------
# AGG-R04: integrity gate failure must persist diagnostic counts to AGGJOB.
# Verifies the fix that populates source_run_count and source_raw_result_count
# on the failure path so aggregation-generation-status can surface them.
# ---------------------------------------------------------------------------


def test_agg_r04_failure_persists_diagnostic_counts_to_aggjob():
    """On integrity failure, AGGJOB must record observed source_run_count and source_raw_result_count."""
    key = "raw-results/client/audit/run/results.json"
    # finalization expects 2 runs; only 1 completed run exists → EXECUTION_COUNT_MISMATCH_COMPLETED_RUNS
    repo = MemoryRepo(
        eligible_audit(finalization={"execution_count": 2, "zero_execution": False}),
        [run_meta(key=key)],
    )
    s3 = MemoryS3({key: envelope()})

    result = _run(repo, s3)

    assert result["status"] == "FAILED"

    job = repo.items[("CLIENT#client", "AUDIT#audit#AGGJOB#job_123")]
    assert job.get("source_run_count") == 1, "source_run_count must reflect completed runs observed"
    assert job.get("source_raw_result_count") == 1, (
        "source_raw_result_count must reflect records loaded before failure"
    )
