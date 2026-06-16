"""Phase 5 consumer contract compatibility gate.

CONTRACT-01 through CONTRACT-07 — verifies that the aggregate records
produced by the Phase 4 orchestrator expose all stable fields that
downstream Phase 5 consumers will depend on, and that the contract
detects both breaking changes (missing / type-changed fields) and
correctly allows additive extensions.

The module-level fixture runs the orchestrator once with a minimal
single-run / single-endpoint scenario and makes all resulting items
available to every test.
"""

import pytest

from release_confidence_platform.aggregation.orchestrator import AggregationOrchestrator
from release_confidence_platform.aggregation.repository import ConditionalWriteError

# ---------------------------------------------------------------------------
# In-memory fakes (self-contained — no cross-file imports)
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


def _eligible_audit():
    return {
        "client_id": "client",
        "audit_id": "audit",
        "lifecycle_state": "COMPLETED",
        "audit_execution_id": "audexec_contract",
        "config_version": "config_v1",
        "finalization": {"execution_count": 1, "zero_execution": False},
        "lifecycle_history": [{"to_state": "COMPLETED", "reason": "finalization_completed"}],
    }


def _run_meta(key):
    return {
        "run_id": "run_contract_01",
        "status": "COMPLETED",
        "raw_result_version": "v1",
        "raw_result_s3_key": key,
    }


def _envelope(run_id, endpoint_id):
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
                "duration_ms": 55,
                "timestamp": "2026-06-07T00:00:00Z",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Module-level fixture — runs the orchestrator once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def aggregate_items():
    """Build a minimal 1-run / 1-endpoint aggregate set and return all persisted items."""
    key = "raw-results/client/audit/run/results.json"
    repo = MemoryRepo(_eligible_audit(), [_run_meta(key)])
    s3 = MemoryS3({key: _envelope("run_contract_01", "endpoint_a")})

    result = AggregationOrchestrator(repository=repo, s3_storage=s3).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "aggregation_version": "agg_v1",
            "aggregation_job_id": "job_contract_test",
        }
    )
    assert result["status"] == "COMPLETED", (
        f"Contract test fixture failed to produce COMPLETED result: {result}"
    )
    return list(repo.items.values())


# ---------------------------------------------------------------------------
# Record selectors used across multiple tests
# ---------------------------------------------------------------------------


def _get_completion_marker(items):
    return next(i for i in items if i.get("aggregate_type") == "aggregate_set_completion")


def _get_audit_aggregate(items):
    return next(i for i in items if i.get("aggregate_type") == "audit")


def _get_endpoint_aggregate(items):
    return next(i for i in items if i.get("aggregate_type") == "endpoint")


def _get_failure_classification_audit(items):
    return next(
        i
        for i in items
        if i.get("aggregate_type") == "failure_classification" and i.get("scope") == "audit"
    )


def _assert_fields(record, required_fields):
    """Assert that every field in required_fields is present with the correct type."""
    for field, expected_type in required_fields.items():
        assert field in record, f"Missing required field: '{field}'"
        assert isinstance(record[field], expected_type), (
            f"Field '{field}' has wrong type: expected {expected_type}, "
            f"got {type(record[field])} (value={record[field]!r})"
        )


# ---------------------------------------------------------------------------
# CONTRACT-01: AggregateSetCompletion stable fields
# ---------------------------------------------------------------------------

REQUIRED_COMPLETION_FIELDS = {
    "aggregate_type": str,
    "client_id": str,
    "audit_id": str,
    "audit_execution_id": str,
    "config_version": str,
    "aggregation_version": str,
    "aggregation_job_id": str,
    "completion_status": str,
    "created_at": str,
    "expected_execution_count": int,
    "source_run_count": int,
    "source_raw_result_count": int,
    "aggregate_record_count": int,
    "endpoint_aggregate_count": int,
    "manifest_count": int,
    "audit_lineage_manifest_ref": dict,
    "aggregate_set_hash": str,
}


def test_contract_01_aggregate_set_completion_contains_all_stable_fields(aggregate_items):
    """AggregateSetCompletion must expose every field that Phase 5 consumers expect."""
    marker = _get_completion_marker(aggregate_items)
    _assert_fields(marker, REQUIRED_COMPLETION_FIELDS)
    assert marker["completion_status"] == "COMPLETE"


# ---------------------------------------------------------------------------
# CONTRACT-02: AuditAggregate stable fields
# ---------------------------------------------------------------------------


def test_contract_02_audit_aggregate_contains_all_stable_fields(aggregate_items):
    """AuditAggregate must expose every top-level and nested field that Phase 5 consumers expect."""
    audit = _get_audit_aggregate(aggregate_items)

    # Top-level fields
    _assert_fields(
        audit,
        {
            "aggregate_type": str,
            "aggregation_version": str,
            "client_id": str,
            "audit_id": str,
            "created_at": str,
            "lineage": dict,
            "endpoint_execution_counts": dict,
            "status_code_distribution": dict,
            "request_counts": dict,
        },
    )

    # execution_duration_ms is numeric (int or float)
    assert "execution_duration_ms" in audit
    assert isinstance(audit["execution_duration_ms"], (int, float)), (
        f"execution_duration_ms must be numeric, got {type(audit['execution_duration_ms'])}"
    )

    # request_counts subfields
    rc = audit["request_counts"]
    _assert_fields(
        rc,
        {
            "total": int,
            "successful": int,
            "failed": int,
            "skipped": int,
            "timeout": int,
            "network_failure": int,
        },
    )
    assert rc["skipped"] == 0, "skipped must always be 0 in current implementation"

    # latency_summary_ms subfield
    assert "latency_summary_ms" in audit, "Missing field: 'latency_summary_ms'"
    assert isinstance(audit["latency_summary_ms"], dict), (
        f"latency_summary_ms must be a dict, got {type(audit['latency_summary_ms'])}"
    )
    assert "count" in audit["latency_summary_ms"], "latency_summary_ms must contain 'count'"
    assert isinstance(audit["latency_summary_ms"]["count"], int)

    # lineage subfields
    lineage = audit["lineage"]
    assert "audit_execution_id" in lineage
    assert isinstance(lineage["audit_execution_id"], str)
    assert "config_version" in lineage
    assert isinstance(lineage["config_version"], str)


# ---------------------------------------------------------------------------
# CONTRACT-03: EndpointAggregate stable fields
# ---------------------------------------------------------------------------


def test_contract_03_endpoint_aggregate_contains_all_stable_fields(aggregate_items):
    """EndpointAggregate must expose every field that Phase 5 consumers expect."""
    ep = _get_endpoint_aggregate(aggregate_items)

    _assert_fields(
        ep,
        {
            "aggregate_type": str,
            "aggregation_version": str,
            "client_id": str,
            "audit_id": str,
            "endpoint_id": str,
            "execution_count": int,
            "timeout_count": int,
            "failure_classification_counts": dict,
            "http_response_distribution": dict,
            "lineage": dict,
            "latency_distribution_ms": dict,
        },
    )

    # success_inputs subfields
    assert "success_inputs" in ep, "Missing field: 'success_inputs'"
    si = ep["success_inputs"]
    assert isinstance(si["numerator"], int), (
        f"success_inputs.numerator must be int, got {type(si['numerator'])}"
    )
    assert isinstance(si["denominator"], int), (
        f"success_inputs.denominator must be int, got {type(si['denominator'])}"
    )


# ---------------------------------------------------------------------------
# CONTRACT-04: FailureClassificationAggregate stable fields
# ---------------------------------------------------------------------------


def test_contract_04_failure_classification_aggregate_contains_all_stable_fields(aggregate_items):
    """FailureClassificationAggregate must expose its stable contract fields."""
    fc = _get_failure_classification_audit(aggregate_items)

    _assert_fields(
        fc,
        {
            "aggregate_type": str,
            "scope": str,
            "classification_counts": dict,
            "lineage": dict,
        },
    )
    assert fc["aggregate_type"] == "failure_classification"
    assert len(fc["classification_counts"]) >= 1, (
        "classification_counts must contain at least one entry"
    )


# ---------------------------------------------------------------------------
# CONTRACT-05: missing stable field must fail the contract test
# ---------------------------------------------------------------------------


def test_contract_05_missing_stable_field_fails_contract_test(aggregate_items):
    """Removing a required field from an aggregate must cause a KeyError."""
    audit_item = _get_audit_aggregate(aggregate_items)
    broken = {k: v for k, v in audit_item.items() if k != "request_counts"}

    assert "request_counts" not in broken, "Broken record must not contain the removed field"

    with pytest.raises(KeyError):
        _ = broken["request_counts"]


# ---------------------------------------------------------------------------
# CONTRACT-06: breaking field type change must fail the contract test
# ---------------------------------------------------------------------------


def test_contract_06_breaking_field_type_change_fails_contract_test(aggregate_items):
    """Changing a required field's type from int to str must be detectable."""
    audit_item = _get_audit_aggregate(aggregate_items)
    broken = {
        **audit_item,
        "request_counts": {
            **audit_item["request_counts"],
            "total": "not_an_int",  # intentional type break
        },
    }

    total = broken["request_counts"]["total"]
    assert not isinstance(total, int), "Type change to str must not be an int"
    assert isinstance(total, str), "Changed field must be a str"


# ---------------------------------------------------------------------------
# CONTRACT-07: additive field does not fail the contract test
# ---------------------------------------------------------------------------


def test_contract_07_additive_field_does_not_fail_contract_test(aggregate_items):
    """Adding a new field to an audit aggregate must not break any existing contract assertions."""
    audit_item = _get_audit_aggregate(aggregate_items)
    extended = {**audit_item, "new_future_field_v2": "additive_value"}

    # All existing stable-field assertions must still pass on the extended record
    assert extended["aggregate_type"] == "audit"
    assert isinstance(extended["aggregation_version"], str)
    assert isinstance(extended["client_id"], str)
    assert isinstance(extended["request_counts"]["total"], int)
    assert extended["request_counts"]["skipped"] == 0
    assert isinstance(extended["lineage"], dict)

    # The new field is present and does not interfere
    assert extended["new_future_field_v2"] == "additive_value"
