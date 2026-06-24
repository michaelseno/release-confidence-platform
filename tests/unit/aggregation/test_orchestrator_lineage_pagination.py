"""Orchestrator-level tests for Phase 4A lineage manifest pagination (v2).

Covers the required validation checklist from
docs/architecture/adr_phase_4a_lineage_manifest_pagination.md /
phase_4a_lineage_manifest_pagination_technical_design.md:
955+ ref aggregation, retry/resume, hash-mismatch fail-closed, and
diagnostic context on LINEAGE_MANIFEST_TOO_LARGE.
"""

from __future__ import annotations

import pytest

from release_confidence_platform.aggregation.lineage import build_manifest_page
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


def _eligible_audit(**overrides):
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


def _many_runs(n: int, endpoint_id: str = "endpoint_a"):
    """n runs, each contributing exactly one raw result to the same endpoint."""
    runs = []
    objects = {}
    for i in range(n):
        run_id = f"run_{i:06d}"
        key = f"raw-results/client/audit/{run_id}/results.json"
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
            "client_id": "client",
            "audit_id": "audit",
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


def _invoke(repo, s3, job_id="job_1"):
    return AggregationOrchestrator(repository=repo, s3_storage=s3).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "aggregation_version": "agg_v1",
            "aggregation_job_id": job_id,
        }
    )


# ---------------------------------------------------------------------------
# 955+ ref end-to-end aggregation (Campaign 2 scale)
# ---------------------------------------------------------------------------


def test_955_refs_aggregation_completes_with_correct_pagination():
    runs, objects = _many_runs(955)
    repo = MemoryRepo(
        _eligible_audit(finalization={"execution_count": 955, "zero_execution": False}), runs
    )
    s3 = MemoryS3(objects)

    result = _invoke(repo, s3)

    assert result["status"] == "COMPLETED", result.get("reason_code")

    headers = [
        i for i in repo.items.values() if i.get("record_kind") == "lineage_manifest"
    ]
    audit_header = next(h for h in headers if h["manifest_scope"] == "audit")
    assert audit_header["source_ref_count"] == 955
    assert audit_header["lineage_page_count"] == 5
    assert audit_header["page_size"] == 200
    assert "source_raw_result_refs" not in audit_header
    assert "page_hashes" not in audit_header

    pages = [
        i for i in repo.items.values() if i.get("record_kind") == "lineage_manifest_page"
    ]
    audit_pages = sorted(
        (p for p in pages if p["manifest_scope"] == "audit"), key=lambda p: p["page_index"]
    )
    assert len(audit_pages) == 5
    assert [p["page_ref_count"] for p in audit_pages] == [200, 200, 200, 200, 155]
    all_refs = [ref for page in audit_pages for ref in page["source_raw_result_refs"]]
    assert len(all_refs) == 955
    assert len({(r["run_id"], r["result_index"]) for r in all_refs}) == 955

    completions = [
        i for i in repo.items.values() if i.get("aggregate_type") == "aggregate_set_completion"
    ]
    assert len(completions) == 1


# ---------------------------------------------------------------------------
# Retry/resume after a simulated mid-write crash
# ---------------------------------------------------------------------------


class _CrashOnThirdPageWriteRepo(MemoryRepo):
    """Simulates a Lambda crash partway through the page-writing phase."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._page_put_calls = 0

    def put_lineage_page_once(self, item):
        self._page_put_calls += 1
        if self._page_put_calls == 3:
            raise RuntimeError("simulated mid-write crash")
        self._put(item)


def test_retry_resumes_after_partial_page_write_crash_without_duplication():
    runs, objects = _many_runs(955)
    repo = _CrashOnThirdPageWriteRepo(
        _eligible_audit(finalization={"execution_count": 955, "zero_execution": False}), runs
    )
    s3 = MemoryS3(objects)

    with pytest.raises(RuntimeError):
        _invoke(repo, s3, job_id="job_1")

    pages_after_crash = [
        i for i in repo.items.values() if i.get("record_kind") == "lineage_manifest_page"
    ]
    assert len(pages_after_crash) == 2, "exactly 2 pages should have been written before the crash"

    result = _invoke(repo, s3, job_id="job_2")
    assert result["status"] == "COMPLETED", result.get("reason_code")

    all_pages = [
        i for i in repo.items.values() if i.get("record_kind") == "lineage_manifest_page"
    ]
    audit_pages = [p for p in all_pages if p["manifest_scope"] == "audit"]
    assert len(audit_pages) == 5, "no duplicate pages after resume"
    assert len({p["page_index"] for p in audit_pages}) == 5

    completions = [
        i for i in repo.items.values() if i.get("aggregate_type") == "aggregate_set_completion"
    ]
    assert len(completions) == 1


# ---------------------------------------------------------------------------
# Page hash mismatch must fail closed, never overwrite
# ---------------------------------------------------------------------------


def test_page_hash_mismatch_fails_closed_without_overwriting():
    runs, objects = _many_runs(3)
    repo = MemoryRepo(
        _eligible_audit(finalization={"execution_count": 3, "zero_execution": False}), runs
    )
    s3 = MemoryS3(objects)

    prefix = repo.aggregate_prefix("client", "audit", "audexec_123", "config_v1", "agg_v1")
    forged_sk = f"{prefix}#LINEAGE#audit#PAGE#0"
    forged_page = build_manifest_page(
        client_id="client",
        audit_id="audit",
        audit_execution_id="audexec_123",
        config_version="config_v1",
        aggregation_version="agg_v1",
        aggregation_job_id="some_other_job",
        created_at="2026-01-01T00:00:00Z",
        manifest_scope="audit",
        page_index=0,
        page_records=[],  # deliberately wrong content -> wrong hash vs. fresh recompute
    )
    repo.items[("CLIENT#client", forged_sk)] = {
        **forged_page,
        "PK": "CLIENT#client",
        "SK": forged_sk,
    }

    result = _invoke(repo, s3, job_id="job_1")

    assert result["status"] == "FAILED"
    assert result["reason_code"] == "LINEAGE_PAGE_HASH_MISMATCH"
    assert not [i for i in repo.items.values() if i.get("record_kind") == "aggregate"]
    assert not [
        i for i in repo.items.values() if i.get("aggregate_type") == "aggregate_set_completion"
    ]


# ---------------------------------------------------------------------------
# Diagnostic context on LINEAGE_MANIFEST_TOO_LARGE
# ---------------------------------------------------------------------------


def test_diagnostic_context_present_on_lineage_manifest_too_large(monkeypatch):
    monkeypatch.setattr(
        "release_confidence_platform.aggregation.orchestrator.MAX_MANIFEST_BYTES", 10
    )
    runs, objects = _many_runs(2)
    repo = MemoryRepo(
        _eligible_audit(finalization={"execution_count": 2, "zero_execution": False}), runs
    )
    s3 = MemoryS3(objects)

    result = _invoke(repo, s3, job_id="job_1")

    assert result["status"] == "FAILED"
    assert result["reason_code"] == "LINEAGE_MANIFEST_TOO_LARGE"

    job = repo.items[("CLIENT#client", "AUDIT#audit#AGGJOB#job_1")]
    error_summary = job["error_summary"]
    assert error_summary["manifest_scope"] == "audit"
    assert error_summary["source_ref_count"] == 2
    assert error_summary["estimated_size_bytes"] > 10
    assert error_summary["max_bytes"] == 10
    assert error_summary["page_size"] == 200
