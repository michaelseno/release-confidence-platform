"""RET-S01 through RET-S06 — sensitive data exclusion tests."""

from __future__ import annotations

import json

from release_confidence_platform.retrieval.dtypes import (
    ProvenanceEnvelope,
    RetrievalFilter,
)
from release_confidence_platform.retrieval.formatter import RetrievalFormatter
from release_confidence_platform.retrieval.service import RetrievalService
from tests.unit.retrieval.test_retrieval_commands import MockRepo

_FILTERS = RetrievalFilter(client_id="client1", audit_id="audit1")

_ENVELOPE = ProvenanceEnvelope(
    retrieved_at="2024-01-01T10:00:00.000Z",
    retrieval_version="1.0.0",
    aggregation_version="v1",
    manifest_hash=None,
    audit_id="audit1",
    client_id="client1",
)

# Sensitive canary value injected into fixture data — must never appear in output
_CANARY = "CANARY_SENSITIVE_VALUE_DO_NOT_EXPOSE_12345"

_AGGREGATE_WITH_SENSITIVE = {
    "PK": "CLIENT#client1",
    "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg1#AGG#v1#AUDIT",
    "record_kind": "aggregate",
    "aggregate_type": "audit",
    "client_id": "client1",
    "audit_id": "audit1",
    "aggregation_version": "v1",
    "created_at": "2024-01-01T10:00:00Z",
    # Sensitive fields that must be stripped
    "request_body": f"raw_body_{_CANARY}",
    "response_body": f"raw_response_{_CANARY}",
    "headers": {"Authorization": f"Bearer {_CANARY}"},
    "request_counts": {"total": 10, "successful": 8, "failed": 2},
}

_LINEAGE_WITH_RAW_S3 = {
    "PK": "CLIENT#client1",
    "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg1#AGG#v1#LINEAGE#audit",
    "record_kind": "lineage_manifest",
    "aggregate_type": "lineage_manifest",
    "manifest_hash": "hash_abc",
    "source_ref_count": 2,
    "aggregation_version": "v1",
    "source_refs": [
        {
            "run_id": "run1",
            "result_index": 0,
            "endpoint_id": "ep1",
            "raw_result_s3_key": f"raw-results/client1/audit1/{_CANARY}.json",
            "result_timestamp": "2024-01-01T09:00:00Z",
        }
    ],
}

_LOG_WITH_SENSITIVE_JOB = {
    "PK": "CLIENT#client1",
    "SK": "AUDIT#audit1#AGGJOB#job1",
    "aggregation_job_id": "job1",
    "status": "COMPLETED",
    "started_at": "2024-01-01T09:55:00Z",
    "completed_at": "2024-01-01T10:00:00Z",
    "aggregation_version": "v1",
    # Headers must never appear in log events
    "headers": {"Authorization": f"Bearer {_CANARY}"},
}


def _assert_canary_absent(text: str, label: str) -> None:
    assert _CANARY not in text, f"Canary found in {label}: {text[:200]}"


# ---------------------------------------------------------------------------
# RET-S01: Aggregation results output contains no raw request bodies
# ---------------------------------------------------------------------------


def test_ret_s01_no_raw_request_bodies():
    svc = RetrievalService(MockRepo(aggregate_records=[_AGGREGATE_WITH_SENSITIVE]))
    dto = svc.get_aggregation_results(_FILTERS)
    rendered = RetrievalFormatter.format_json(dto, _ENVELOPE)
    assert "raw_body" not in rendered
    _assert_canary_absent(rendered, "aggregation-results json")


# ---------------------------------------------------------------------------
# RET-S02: Aggregation results output contains no raw response bodies
# ---------------------------------------------------------------------------


def test_ret_s02_no_raw_response_bodies():
    svc = RetrievalService(MockRepo(aggregate_records=[_AGGREGATE_WITH_SENSITIVE]))
    dto = svc.get_aggregation_results(_FILTERS)
    rendered = RetrievalFormatter.format_json(dto, _ENVELOPE)
    assert "response_body" not in rendered
    _assert_canary_absent(rendered, "aggregation-results response_body")


# ---------------------------------------------------------------------------
# RET-S03: Engineering logs output contains no raw headers
# ---------------------------------------------------------------------------


def test_ret_s03_no_raw_headers_in_logs():
    svc = RetrievalService(MockRepo(jobs=[_LOG_WITH_SENSITIVE_JOB]))
    dto = svc.get_engineering_logs(_FILTERS)
    rendered = RetrievalFormatter.format_json(dto, _ENVELOPE)
    assert "headers" not in rendered or "Authorization" not in rendered
    _assert_canary_absent(rendered, "engineering-logs")


# ---------------------------------------------------------------------------
# RET-S04: Evidence references output contains no raw S3 key values
# ---------------------------------------------------------------------------


def test_ret_s04_no_raw_s3_keys_in_evidence_references():
    svc = RetrievalService(MockRepo(aggregate_records=[_LINEAGE_WITH_RAW_S3]))
    dto = svc.get_evidence_references(_FILTERS)
    rendered = RetrievalFormatter.format_json(dto, _ENVELOPE)
    # Raw S3 key path must not appear
    assert "raw-results/" not in rendered
    # Canary embedded in S3 key must not appear
    _assert_canary_absent(rendered, "evidence-references")
    # Sanitized ref should be present instead
    parsed = json.loads(rendered)
    refs = parsed.get("data", {}).get("source_refs", [])
    if refs:
        for ref in refs:
            s3_ref = ref.get("s3_key_ref")
            if s3_ref is not None:
                assert s3_ref.startswith("s3ref:")


# ---------------------------------------------------------------------------
# RET-S05: Canary token injection — canary value not present in any retrieval output
# ---------------------------------------------------------------------------


def test_ret_s05_canary_injection_all_commands():
    sensitive_agg = {**_AGGREGATE_WITH_SENSITIVE}
    svc = RetrievalService(
        MockRepo(
            aggregate_records=[sensitive_agg, _LINEAGE_WITH_RAW_S3],
            jobs=[_LOG_WITH_SENSITIVE_JOB],
        )
    )

    for get_method in (
        svc.get_aggregation_results,
        svc.get_aggregation_metadata,
        svc.get_engineering_logs,
        svc.get_evidence_references,
        svc.get_aggregation_lineage,
        svc.get_failure_summaries,
    ):
        dto = get_method(_FILTERS)
        rendered = RetrievalFormatter.format_json(dto, _ENVELOPE)
        _assert_canary_absent(rendered, get_method.__name__)


# ---------------------------------------------------------------------------
# RET-S06: Endpoint IDs in retrieval output are sanitized (no raw URL patterns)
# ---------------------------------------------------------------------------


def test_ret_s06_endpoint_ids_sanitized():
    # Aggregation engine already sanitizes endpoint IDs via _safe_endpoint_id
    # We verify the retrieval layer passes through what's stored without re-injecting raw URLs
    safe_endpoint_record = {
        "PK": "CLIENT#client1",
        "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg1#AGG#v1#ENDPOINT#ep_safe",
        "record_kind": "aggregate",
        "aggregate_type": "endpoint",
        "client_id": "client1",
        "audit_id": "audit1",
        "endpoint_id": "ep_safe",
        "aggregation_version": "v1",
    }
    svc = RetrievalService(MockRepo(aggregate_records=[safe_endpoint_record]))
    dto = svc.get_aggregation_results(_FILTERS)
    rendered = RetrievalFormatter.format_json(dto, _ENVELOPE)
    # No raw URL patterns
    assert "https://" not in rendered
    assert "http://" not in rendered
