"""Phase 4A.4 integration tests.

AGG-I1 and AGG-I2 — end-to-end multi-run / multi-endpoint aggregation
persistence and idempotency.
"""


from release_confidence_platform.aggregation.orchestrator import AggregationOrchestrator
from release_confidence_platform.aggregation.repository import ConditionalWriteError

# ---------------------------------------------------------------------------
# Shared in-memory fakes
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


def _make_audit(execution_count=2):
    return {
        "client_id": "client",
        "audit_id": "audit",
        "lifecycle_state": "COMPLETED",
        "audit_execution_id": "audexec_i1",
        "config_version": "config_v1",
        "finalization": {"execution_count": execution_count, "zero_execution": False},
        "lifecycle_history": [{"to_state": "COMPLETED", "reason": "finalization_completed"}],
    }


def _make_run_meta(run_id, key):
    return {
        "run_id": run_id,
        "status": "COMPLETED",
        "raw_result_version": "v1",
        "raw_result_s3_key": key,
    }


def _make_envelope(run_id, endpoint_id):
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
                "duration_ms": 100,
                "timestamp": "2026-06-07T00:00:00Z",
            }
        ],
    }


def _run(repo, s3, job_id):
    return AggregationOrchestrator(repository=repo, s3_storage=s3).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "aggregation_version": "agg_v1",
            "aggregation_job_id": job_id,
        }
    )


# ---------------------------------------------------------------------------
# AGG-I1: end-to-end complete aggregate set written for multi-run/multi-endpoint
# ---------------------------------------------------------------------------


def test_agg_i1_end_to_end_aggregation_complete_aggregate_set_written():
    """Multi-run, multi-endpoint scenario writes a fully-populated aggregate set."""
    key1 = "raw-results/client/audit/run1/results.json"
    key2 = "raw-results/client/audit/run2/results.json"

    repo = MemoryRepo(
        _make_audit(execution_count=2),
        [
            _make_run_meta("run_1", key1),
            _make_run_meta("run_2", key2),
        ],
    )
    s3 = MemoryS3(
        {
            key1: _make_envelope("run_1", "endpoint_a"),
            key2: _make_envelope("run_2", "endpoint_b"),
        }
    )

    result = _run(repo, s3, job_id="job_i1")
    assert result["status"] == "COMPLETED"

    all_items = list(repo.items.values())

    # Exactly one aggregate_set_completion with COMPLETE status
    completions = [i for i in all_items if i.get("aggregate_type") == "aggregate_set_completion"]
    assert len(completions) == 1
    assert completions[0]["completion_status"] == "COMPLETE"

    # Exactly one AuditAggregate with total request_count == 2 (one per run)
    audit_aggs = [i for i in all_items if i.get("aggregate_type") == "audit"]
    assert len(audit_aggs) == 1
    assert audit_aggs[0]["request_counts"]["total"] == 2

    # Exactly 2 EndpointAggregate records (one per endpoint)
    endpoint_aggs = [i for i in all_items if i.get("aggregate_type") == "endpoint"]
    assert len(endpoint_aggs) == 2

    # At least one FailureClassificationAggregate with audit scope
    fc_audit = [
        i
        for i in all_items
        if i.get("aggregate_type") == "failure_classification" and i.get("scope") == "audit"
    ]
    assert len(fc_audit) >= 1

    # At least 3 LineageManifest records: 1 audit + 1 endpoint_a + 1 endpoint_b
    manifests = [i for i in all_items if i.get("record_kind") == "lineage_manifest"]
    assert len(manifests) >= 3
    manifest_scopes = {i["manifest_scope"] for i in manifests}
    assert "audit" in manifest_scopes
    assert "endpoint:endpoint_a" in manifest_scopes
    assert "endpoint:endpoint_b" in manifest_scopes


# ---------------------------------------------------------------------------
# AGG-I2: end-to-end idempotency — second run returns DUPLICATE_COMPLETED
# ---------------------------------------------------------------------------


def test_agg_i2_end_to_end_idempotency():
    """Running aggregation twice produces DUPLICATE_COMPLETED and exactly one aggregate set."""
    key1 = "raw-results/client/audit/run1/results.json"
    key2 = "raw-results/client/audit/run2/results.json"

    repo = MemoryRepo(
        _make_audit(execution_count=2),
        [
            _make_run_meta("run_1", key1),
            _make_run_meta("run_2", key2),
        ],
    )
    s3 = MemoryS3(
        {
            key1: _make_envelope("run_1", "endpoint_a"),
            key2: _make_envelope("run_2", "endpoint_b"),
        }
    )

    first = _run(repo, s3, job_id="job_123")
    assert first["status"] == "COMPLETED"

    second = _run(repo, s3, job_id="job_456")
    assert second["status"] == "DUPLICATE_COMPLETED"

    completions = [
        i for i in repo.items.values() if i.get("aggregate_type") == "aggregate_set_completion"
    ]
    assert len(completions) == 1, "Exactly one completion marker must exist after idempotent re-run"

    audit_aggs = [
        i for i in repo.items.values() if i.get("aggregate_type") == "audit"
    ]
    assert len(audit_aggs) == 1, "Exactly one audit aggregate must exist after idempotent re-run"
