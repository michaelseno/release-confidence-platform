import pytest

from release_confidence_platform.aggregation.orchestrator import AggregationOrchestrator
from release_confidence_platform.aggregation.repository import ConditionalWriteError


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

    def list_completed_runs(self, client_id, audit_id):
        return self.runs

    def aggregate_set_exists(self, client_id, audit_id, exec_id, cfg, ver):
        return (
            f"CLIENT#{client_id}",
            f"AUDIT#{audit_id}#EXEC#{exec_id}#CFG#{cfg}#AGG#{ver}#AUDIT",
        ) in self.items

    def put_records_once(self, records):
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
        self.writes = []

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


def envelope(run_id="run_12345678"):
    return {
        "raw_result_version": "v1",
        "client_id": "client",
        "audit_id": "audit",
        "run_id": run_id,
        "results": [
            {
                "endpoint_id": "https://unsafe.test/path?token=x",
                "failure_type": "PASS",
                "status_code": 200,
                "duration_ms": 1,
                "timestamp": "2026-06-07T00:00:00Z",
            }
        ],
    }


def invoke(repo, s3):
    return AggregationOrchestrator(repository=repo, s3_storage=s3).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "aggregation_version": "agg_v1",
            "aggregation_job_id": "job_123",
        }
    )


def test_success_creates_bounded_manifest_and_sanitized_endpoint():
    key = "raw-results/client/audit/run/results.json"
    repo = MemoryRepo(eligible_audit(), [run_meta(key=key)])
    result = invoke(repo, MemoryS3({key: envelope()}))
    assert result["status"] == "COMPLETED"
    assert result["audit_execution_id"] == "audexec_123"
    assert result["config_version"] == "config_v1"
    audit_items = [item for item in repo.items.values() if item.get("aggregate_type") == "audit"]
    assert audit_items[0]["request_counts"]["skipped"] == 0
    assert "source_raw_result_refs" not in audit_items[0]
    assert audit_items[0]["lineage"]["lineage_manifest_ref"]["source_ref_count"] == 1
    endpoints = [item for item in repo.items.values() if item.get("aggregate_type") == "endpoint"]
    assert endpoints[0]["endpoint_id"] == "unknown"


@pytest.mark.parametrize(
    "audit,reason",
    [
        (eligible_audit(audit_execution_id=None, config_version=None), "MISSING_CONFIG_VERSION"),
        (eligible_audit(lifecycle_state="FAILED"), "AUDIT_NOT_COMPLETED"),
        (
            eligible_audit(finalization={"execution_count": 0, "zero_execution": True}),
            "ZERO_EXECUTION_AUDIT_INELIGIBLE",
        ),
    ],
)
def test_guardrails_fail_without_aggregates(audit, reason):
    key = "raw-results/client/audit/run/results.json"
    repo = MemoryRepo(audit, [run_meta(key=key)])
    result = invoke(repo, MemoryS3({key: envelope()}))
    assert result["status"] in {"FAILED", "INELIGIBLE"}
    assert result["reason_code"] == reason
    assert not [item for item in repo.items.values() if item.get("record_kind") == "aggregate"]


def test_duplicate_raw_reference_fails_before_aggregate_creation():
    key = "raw-results/client/audit/run/results.json"
    repo = MemoryRepo(eligible_audit(), [run_meta(key=key), run_meta(key=key)])
    result = invoke(repo, MemoryS3({key: envelope()}))
    assert result["status"] == "FAILED"
    assert result["reason_code"] == "DUPLICATE_RAW_RESULT_REFERENCE"
    assert not [item for item in repo.items.values() if item.get("record_kind") == "aggregate"]


def test_repeated_aggregation_is_duplicate_completed_no_double_count():
    key = "raw-results/client/audit/run/results.json"
    repo = MemoryRepo(eligible_audit(), [run_meta(key=key)])
    s3 = MemoryS3({key: envelope()})
    assert invoke(repo, s3)["status"] == "COMPLETED"
    duplicate = AggregationOrchestrator(repository=repo, s3_storage=s3).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "aggregation_version": "agg_v1",
            "aggregation_job_id": "job_456",
        }
    )
    assert duplicate["status"] == "DUPLICATE_COMPLETED"
    assert len([item for item in repo.items.values() if item.get("aggregate_type") == "audit"]) == 1
