import pytest

from release_confidence_platform.aggregation.orchestrator import AggregationOrchestrator
from release_confidence_platform.aggregation.repository import (
    AggregationRepository,
    ConditionalWriteError,
)


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


def envelope(run_id="run_12345678", endpoint_id="https://unsafe.test/path?token=x"):
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
    assert endpoints[0]["lineage"]["lineage_manifest_ref"]["manifest_scope"] == "endpoint:unknown"
    assert [
        item
        for item in repo.items.values()
        if item.get("aggregate_type") == "aggregate_set_completion"
    ]


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
    repo = MemoryRepo(
        eligible_audit(finalization={"execution_count": 2, "zero_execution": False}),
        [run_meta(key=key), run_meta(key=key)],
    )
    result = invoke(repo, MemoryS3({key: envelope()}))
    assert result["status"] == "FAILED"
    assert result["reason_code"] == "DUPLICATE_RAW_RESULT_REFERENCE"
    assert not [item for item in repo.items.values() if item.get("record_kind") == "aggregate"]


def test_partial_evidence_execution_count_mismatch_blocks_aggregation():
    key = "raw-results/client/audit/run/results.json"
    repo = MemoryRepo(
        eligible_audit(finalization={"execution_count": 2, "zero_execution": False}),
        [run_meta(key=key)],
    )
    result = invoke(repo, MemoryS3({key: envelope()}))
    assert result["status"] == "FAILED"
    assert result["reason_code"] == "EXECUTION_COUNT_MISMATCH_COMPLETED_RUNS"
    job = repo.items[("CLIENT#client", "AUDIT#audit#AGGJOB#job_123")]
    assert job["failure_category"] == "EVIDENCE_PRODUCING"
    assert not [item for item in repo.items.values() if item.get("record_kind") == "aggregate"]


def test_raw_result_count_mismatch_blocks_aggregation():
    key = "raw-results/client/audit/run/results.json"
    raw = envelope()
    raw["results"].append(raw["results"][0].copy())
    repo = MemoryRepo(eligible_audit(), [run_meta(key=key)])
    result = invoke(repo, MemoryS3({key: raw}))
    assert result["status"] == "FAILED"
    assert result["reason_code"] == "EXECUTION_COUNT_MISMATCH_RAW_RESULTS"
    assert not [item for item in repo.items.values() if item.get("record_kind") == "aggregate"]


def test_missing_raw_evidence_blocks_without_outputs():
    key = "raw-results/client/audit/missing/results.json"
    repo = MemoryRepo(eligible_audit(), [run_meta(key=key)])
    result = invoke(repo, MemoryS3({}))
    assert result["status"] == "FAILED"
    assert result["reason_code"] == "MISSING_RAW_EVIDENCE"
    assert not [
        item
        for item in repo.items.values()
        if item.get("record_kind")
        in {"aggregate", "lineage_manifest", "aggregate_set_completion"}
    ]


def test_missing_config_version_blocks_as_evidence_producing():
    key = "raw-results/client/audit/run/results.json"
    repo = MemoryRepo(eligible_audit(config_version=None), [run_meta(key=key)])
    result = invoke(repo, MemoryS3({key: envelope()}))
    assert result["status"] == "FAILED"
    assert result["reason_code"] == "MISSING_CONFIG_VERSION"
    assert (
        repo.items[("CLIENT#client", "AUDIT#audit#AGGJOB#job_123")]["failure_category"]
        == "EVIDENCE_PRODUCING"
    )


class MissingIdentityRepo(MemoryRepo):
    def put_audit_execution_identity_once(self, item):  # noqa: ARG002
        raise RuntimeError("identity write unavailable")


def test_missing_audit_execution_id_blocks_when_unresolved():
    key = "raw-results/client/audit/run/results.json"
    repo = MissingIdentityRepo(eligible_audit(audit_execution_id=None), [run_meta(key=key)])
    result = invoke(repo, MemoryS3({key: envelope()}))
    assert result["status"] == "FAILED"
    assert result["reason_code"] == "MISSING_AUDIT_EXECUTION_ID"
    assert (
        repo.items[("CLIENT#client", "AUDIT#audit#AGGJOB#job_123")]["failure_category"]
        == "EVIDENCE_PRODUCING"
    )


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


class FailingTransactionalRepo(MemoryRepo):
    def put_records_once(self, records):  # noqa: ARG002
        raise ConditionalWriteError()


def test_transaction_write_failure_leaves_no_partial_manifest_or_aggregates():
    key = "raw-results/client/audit/run/results.json"
    repo = FailingTransactionalRepo(eligible_audit(), [run_meta(key=key)])

    result = invoke(repo, MemoryS3({key: envelope()}))

    assert result["status"] == "CONFLICT"
    assert result["reason_code"] == "AGGREGATE_SET_INCOMPLETE_CONFLICT"
    assert not [item for item in repo.items.values() if item.get("record_kind") == "aggregate"]
    assert not [
        item for item in repo.items.values() if item.get("record_kind") == "lineage_manifest"
    ]


class CompleteOnConflictRepo(MemoryRepo):
    def put_records_once(self, records):
        for item in records:
            self.items[(item["PK"], item["SK"])] = item
        raise ConditionalWriteError()


def test_concurrent_conflict_reload_detects_completed_set_as_duplicate():
    key = "raw-results/client/audit/run/results.json"
    repo = CompleteOnConflictRepo(eligible_audit(), [run_meta(key=key)])
    result = invoke(repo, MemoryS3({key: envelope()}))
    assert result["status"] == "DUPLICATE_COMPLETED"
    assert len([item for item in repo.items.values() if item.get("aggregate_type") == "audit"]) == 1


def test_same_job_duplicate_event_is_controlled_conflict_when_active():
    key = "raw-results/client/audit/run/results.json"
    repo = MemoryRepo(eligible_audit(), [run_meta(key=key)])
    job_key = repo.job_keys("client", "audit", "job_123")
    repo.put_job_once({**job_key, "status": "STARTED", "aggregation_job_id": "job_123"})
    result = invoke(repo, MemoryS3({key: envelope()}))
    assert result["status"] == "CONFLICT"
    assert result["reason_code"] == "AGGREGATE_WRITE_CONFLICT"


def test_endpoint_lineage_exactness_for_each_endpoint():
    key1 = "raw-results/client/audit/run1/results.json"
    key2 = "raw-results/client/audit/run2/results.json"
    repo = MemoryRepo(
        eligible_audit(finalization={"execution_count": 2, "zero_execution": False}),
        [run_meta("run_1", key1), run_meta("run_2", key2)],
    )
    result = invoke(
        repo,
        MemoryS3({key1: envelope("run_1", "endpoint_a"), key2: envelope("run_2", "endpoint_b")}),
    )
    assert result["status"] == "COMPLETED"
    endpoint_items = [
        item for item in repo.items.values() if item.get("aggregate_type") == "endpoint"
    ]
    assert {item["lineage"]["source_ref_count"] for item in endpoint_items} == {1}
    manifests = [
        item for item in repo.items.values() if item.get("record_kind") == "lineage_manifest"
    ]
    assert {item["manifest_scope"] for item in manifests} >= {
        "endpoint:endpoint_a",
        "endpoint:endpoint_b",
    }


def test_unsafe_raw_result_key_fails_closed_before_lineage_or_s3_read():
    unsafe_key = "raw-results/client/audit/run/results-token=supersecret.json"
    repo = MemoryRepo(eligible_audit(), [run_meta(key=unsafe_key)])
    s3 = MemoryS3({unsafe_key: envelope()})

    result = invoke(repo, s3)

    assert result["status"] == "FAILED"
    assert result["reason_code"] == "UNSAFE_RAW_RESULT_S3_KEY"
    assert not [item for item in repo.items.values() if item.get("record_kind") == "aggregate"]
    assert not [
        item for item in repo.items.values() if item.get("record_kind") == "lineage_manifest"
    ]


def test_sensitive_canaries_are_absent_from_persisted_outputs_and_response():
    key = "raw-results/client/audit/run/results.json"
    canaries = [
        "token=supersecret",
        "authorization",
        "session_cookie",
        "request_body",
        "response_body",
        "payload_secret",
        "ssn-123-45-6789",
    ]
    raw = envelope()
    raw["results"][0].update(
        {
            "endpoint_id": "https://api.example.test/path?token=supersecret",
            "headers": {"Authorization": "Bearer supersecret"},
            "cookies": "session_cookie=supersecret",
            "request_body": "payload_secret",
            "response_body": "ssn-123-45-6789",
        }
    )
    repo = MemoryRepo(eligible_audit(), [run_meta(key=key)])

    result = invoke(repo, MemoryS3({key: raw}))

    persisted = repr(list(repo.items.values())) + repr(result)
    for canary in canaries:
        assert canary not in persisted.lower()


class DynamoTransactClient:
    def __init__(self):
        self.transact_items = None

    def transact_write_items(self, *, TransactItems):
        self.transact_items = TransactItems
        return {}


def test_repository_writes_complete_aggregate_set_as_single_transaction():
    client = DynamoTransactClient()
    repository = AggregationRepository("metadata-table", client)

    repository.put_records_once(
        [
            {"PK": "CLIENT#client", "SK": "AUDIT#audit#LINEAGE#audit", "value": 1},
            {"PK": "CLIENT#client", "SK": "AUDIT#audit#AUDIT", "value": 2},
        ]
    )

    assert client.transact_items is not None
    assert len(client.transact_items) == 2
    assert all("Put" in item for item in client.transact_items)
    assert all(
        item["Put"]["ConditionExpression"]
        == "attribute_not_exists(PK) AND attribute_not_exists(SK)"
        for item in client.transact_items
    )
