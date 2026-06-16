"""RET-PROV01 through RET-PROV04 — provenance envelope validation tests."""

from __future__ import annotations

import json

from release_confidence_platform.retrieval.dtypes import (
    _NOTICE,
    AggregationLineageDTO,
    ProvenanceEnvelope,
    RetrievalFilter,
)
from release_confidence_platform.retrieval.formatter import RetrievalFormatter

_ENVELOPE = ProvenanceEnvelope(
    retrieved_at="2024-01-01T10:00:00.000Z",
    retrieval_version="1.0.0",
    aggregation_version="v1",
    manifest_hash="abc123",
    audit_id="audit1",
    client_id="client1",
)

_DTO = AggregationLineageDTO(
    lineage_manifest_ref={"PK": "CLIENT#client1"},
    source_ref_count=15,
    manifest_hash="abc123",
    audit_execution_id="exec1",
    config_version="cfg1",
    aggregation_version="v1",
    aggregation_job_id="job1",
    aggregation_timestamp="2024-01-01T10:00:00Z",
)


# ---------------------------------------------------------------------------
# RET-PROV01: Every JSON output includes all required provenance fields
# ---------------------------------------------------------------------------


def test_ret_prov01_all_provenance_fields_present():
    rendered = RetrievalFormatter.format_json(_DTO, _ENVELOPE)
    parsed = json.loads(rendered)
    for field in ("retrieved_at", "retrieval_version", "aggregation_version",
                  "manifest_hash", "audit_id", "client_id"):
        assert field in parsed, f"Missing provenance field: {field}"
    assert parsed["retrieved_at"] == "2024-01-01T10:00:00.000Z"
    assert parsed["retrieval_version"] == "1.0.0"
    assert parsed["aggregation_version"] == "v1"
    assert parsed["manifest_hash"] == "abc123"
    assert parsed["audit_id"] == "audit1"
    assert parsed["client_id"] == "client1"


# ---------------------------------------------------------------------------
# RET-PROV02: Every JSON output includes _notice field with exact disclaimer
# ---------------------------------------------------------------------------


def test_ret_prov02_notice_field_present_and_correct():
    rendered = RetrievalFormatter.format_json(_DTO, _ENVELOPE)
    parsed = json.loads(rendered)
    assert "_notice" in parsed
    assert parsed["_notice"] == _NOTICE


# ---------------------------------------------------------------------------
# RET-PROV03: Human-readable output includes disclaimer at top
# ---------------------------------------------------------------------------


def test_ret_prov03_human_disclaimer_at_top():
    rendered = RetrievalFormatter.format_human(_DTO, _ENVELOPE)
    assert isinstance(rendered, str)
    # Disclaimer must appear before any data fields
    notice_pos = rendered.find(_NOTICE)
    data_pos = rendered.find("--- data ---")
    assert notice_pos >= 0, "Disclaimer not found in human output"
    assert data_pos > notice_pos, "Disclaimer must appear before data section"


# ---------------------------------------------------------------------------
# RET-PROV04: manifest_hash in provenance equals aggregate_set_hash from completion
# ---------------------------------------------------------------------------


def test_ret_prov04_manifest_hash_matches_completion():
    from release_confidence_platform.retrieval.service import RetrievalService  # noqa: PLC0415
    from tests.unit.retrieval.test_retrieval_commands import _COMPLETION, MockRepo  # noqa: PLC0415

    completion_with_hash = {**_COMPLETION, "aggregate_set_hash": "hash_xyz"}
    lineage_manifest = {
        "PK": "CLIENT#client1",
        "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg1#AGG#v1#LINEAGE#audit",
        "record_kind": "lineage_manifest",
        "aggregate_type": "lineage_manifest",
        "manifest_hash": "hash_xyz",
        "source_ref_count": 5,
        "aggregation_version": "v1",
    }
    svc = RetrievalService(MockRepo(aggregate_records=[completion_with_hash, lineage_manifest]))
    filters = RetrievalFilter(client_id="client1", audit_id="audit1")
    dto = svc.get_aggregation_lineage(filters)
    assert dto.manifest_hash == "hash_xyz"
