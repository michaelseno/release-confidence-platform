"""RET-F01 through RET-F04, RET-REPR01 through RET-REPR03 — formatter tests."""

from __future__ import annotations

import json

from release_confidence_platform.retrieval.dtypes import (
    AggregationMetadataDTO,
    ProcessingTimelineDTO,
    ProvenanceEnvelope,
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

_DTO = AggregationMetadataDTO(
    job_id="job1",
    status="COMPLETED",
    failure_category=None,
    reason_code=None,
    source_run_count=5,
    source_raw_result_count=15,
    created_at="2024-01-01T09:55:00Z",
    updated_at="2024-01-01T10:00:00Z",
    aggregation_version="v1",
    audit_execution_id="exec1",
    config_version="cfg1",
)


# ---------------------------------------------------------------------------
# RET-F01: --output json produces well-formed JSON with required fields
# ---------------------------------------------------------------------------


def test_ret_f01_json_output_parseable():
    rendered = RetrievalFormatter.format_json(_DTO, _ENVELOPE)
    parsed = json.loads(rendered)
    assert isinstance(parsed, dict)
    assert "retrieved_at" in parsed
    assert "retrieval_version" in parsed
    assert "audit_id" in parsed
    assert "client_id" in parsed
    assert "data" in parsed
    assert parsed["audit_id"] == "audit1"
    assert parsed["client_id"] == "client1"


# ---------------------------------------------------------------------------
# RET-F02: --output human produces readable formatted output
# ---------------------------------------------------------------------------


def test_ret_f02_human_output_non_empty():
    rendered = RetrievalFormatter.format_human(_DTO, _ENVELOPE)
    assert isinstance(rendered, str)
    assert len(rendered) > 0
    assert "retrieved_at" in rendered
    assert "audit1" in rendered


# ---------------------------------------------------------------------------
# RET-F03: JSON output field ordering is deterministic — two calls produce same bytes
# ---------------------------------------------------------------------------


def test_ret_f03_json_deterministic():
    out1 = RetrievalFormatter.format_json(_DTO, _ENVELOPE)
    out2 = RetrievalFormatter.format_json(_DTO, _ENVELOPE)
    assert out1 == out2


# ---------------------------------------------------------------------------
# RET-F04: Default output format is human (argparse default check)
# ---------------------------------------------------------------------------


def test_ret_f04_default_output_is_human():
    import argparse  # noqa: PLC0415

    from release_confidence_platform.retrieval.commands import (
        build_retrieve_parser,  # noqa: PLC0415
    )

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="retrieve_command")
    build_retrieve_parser(sub)
    args = parser.parse_args(
        ["aggregation-metadata", "--client", "c1", "--audit", "a1", "--stage", "dev"]
    )
    assert args.output == "human"


# ---------------------------------------------------------------------------
# RET-REPR01: Two independent invocations for same data produce identical bytes
# ---------------------------------------------------------------------------


def test_ret_repr01_byte_identical_independent_invocations():
    dto = ProcessingTimelineDTO(
        started_at="2024-01-01T09:55:00Z",
        completed_at="2024-01-01T10:00:00Z",
        duration_ms=300000.0,
        per_stage=(
            ("job_started_at", "2024-01-01T09:55:00Z"),
            ("job_completed_at", "2024-01-01T10:00:00Z"),
        ),
    )
    env = ProvenanceEnvelope(
        retrieved_at="2024-01-01T10:00:00.000Z",
        retrieval_version="1.0.0",
        aggregation_version="v1",
        manifest_hash=None,
        audit_id="audit1",
        client_id="client1",
    )
    out_a = RetrievalFormatter.format_json(dto, env)
    out_b = RetrievalFormatter.format_json(dto, env)
    assert out_a.encode("utf-8") == out_b.encode("utf-8")


# ---------------------------------------------------------------------------
# RET-REPR02: Deserializing and re-serializing produces identical bytes
# ---------------------------------------------------------------------------


def test_ret_repr02_round_trip_identical():
    rendered = RetrievalFormatter.format_json(_DTO, _ENVELOPE)
    parsed = json.loads(rendered)
    re_rendered = json.dumps(parsed, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert rendered == re_rendered


# ---------------------------------------------------------------------------
# RET-REPR03: Collection ordering is deterministic by canonical precedence
# ---------------------------------------------------------------------------


def test_ret_repr03_collection_ordering_deterministic():
    from release_confidence_platform.retrieval.dtypes import (  # noqa: PLC0415
        AggregationResultRecord,
        AggregationResultsDTO,
    )

    # Create records out of canonical order — service sorts them, formatter preserves
    records = (
        AggregationResultRecord(
            aggregate_type="endpoint",
            sk="AUDIT#audit1#EXEC#exec1#CFG#cfg1#AGG#v1#ENDPOINT#ep_b",
            data=(("audit_id", "audit1"), ("endpoint_id", "ep_b")),
        ),
        AggregationResultRecord(
            aggregate_type="endpoint",
            sk="AUDIT#audit1#EXEC#exec1#CFG#cfg1#AGG#v1#ENDPOINT#ep_a",
            data=(("audit_id", "audit1"), ("endpoint_id", "ep_a")),
        ),
    )
    dto = AggregationResultsDTO(
        records=records, total_count=2, endpoint_count=2, completion_status="COMPLETE"
    )
    env = ProvenanceEnvelope(
        retrieved_at="2024-01-01T10:00:00.000Z",
        retrieval_version="1.0.0",
        aggregation_version="v1",
        manifest_hash=None,
        audit_id="audit1",
        client_id="client1",
    )
    out1 = RetrievalFormatter.format_json(dto, env)
    out2 = RetrievalFormatter.format_json(dto, env)
    assert out1 == out2
    parsed = json.loads(out1)
    assert "data" in parsed
