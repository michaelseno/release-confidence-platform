"""Phase 4A lineage manifest pagination — pure function unit tests.

Covers the bounded-header + immutable-page model from
docs/architecture/adr_phase_4a_lineage_manifest_pagination.md and
docs/architecture/phase_4a_lineage_manifest_pagination_technical_design.md.
"""

from __future__ import annotations

import json
import random

from release_confidence_platform.aggregation.constants import (
    LINEAGE_MANIFEST_VERSION_V2,
    LINEAGE_PAGE_SIZE,
    MAX_MANIFEST_BYTES,
    MAX_MANIFEST_PAGE_REF_COUNT,
)
from release_confidence_platform.aggregation.lineage import (
    build_manifest_header_v2,
    build_manifest_page,
    manifest_ref,
    paginate_records,
)
from release_confidence_platform.aggregation.models import RawAggregationRecord


def _make_record(run_id, endpoint_id="ep_a", index=0, id_len=None):
    if id_len:
        run_id = run_id.ljust(id_len, "0")[:id_len]
        endpoint_id = endpoint_id.ljust(id_len, "0")[:id_len]
        key = ("X" * id_len) if id_len else f"raw-results/client/audit/{run_id}/results.json"
        s3_version_id = "V" * 200 if id_len else None
    else:
        key = f"raw-results/client/audit/{run_id}/results.json"
        s3_version_id = None
    return RawAggregationRecord(
        raw_result_version="raw_result_v1",
        run_id=run_id,
        raw_result_s3_key=key,
        s3_version_id=s3_version_id,
        result_index=index,
        endpoint_id=endpoint_id,
        result_timestamp="2026-06-21T13:23:02.511097Z",
        duration_ms=42,
        status_code=200,
        failure_type="PASS",
    )


def _worst_case_record(index: int) -> RawAggregationRecord:
    """A record built from the maximum-length values the platform's own
    validators allow (128-char identifiers, 200-char S3 version id)."""
    run_id = "R" * 128
    return RawAggregationRecord(
        raw_result_version="raw_result_v1",
        run_id=run_id,
        raw_result_s3_key=f"raw-results/{'C' * 128}/{'A' * 128}/{run_id}/results.json",
        s3_version_id="V" * 200,
        result_index=index,
        endpoint_id="E" * 128,
        result_timestamp="2026-06-21T13:23:02.511097Z",
        duration_ms=42,
        status_code=200,
        failure_type="PASS",
    )


HEADER_KWARGS = dict(
    client_id="client",
    audit_id="audit",
    audit_execution_id="audexec_1",
    config_version="config_v1",
    aggregation_version="agg_v1",
    aggregation_job_id="job_1",
    created_at="2026-06-24T00:00:00Z",
)

# Every identifier-like field that flows into a manifest page is validated by
# IDENTIFIER_PATTERN ([A-Za-z0-9_.-]{1,128}) — client_id, audit_id, run_id,
# endpoint_id, audit_execution_id, config_version, aggregation_job_id all
# share the same 128-char enforced max. The worst-case ceiling must use the
# max for every one of them, not just the raw-result fields.
WORST_CASE_HEADER_KWARGS = dict(
    client_id="C" * 128,
    audit_id="A" * 128,
    audit_execution_id="X" * 128,
    config_version="V" * 128,
    aggregation_version="agg_v1",
    aggregation_job_id="J" * 128,
    created_at="2026-06-24T00:00:00Z",
)


# ---------------------------------------------------------------------------
# paginate_records
# ---------------------------------------------------------------------------


def test_paginate_records_partitions_955_refs_correctly():
    records = [_make_record(f"run_{i}", index=i) for i in range(955)]
    pages = paginate_records(records, page_size=200)

    assert len(pages) == 5
    assert [len(p) for p in pages] == [200, 200, 200, 200, 155]

    all_refs = [r for page in pages for r in page]
    assert len(all_refs) == 955
    assert len({r.ref_identity for r in all_refs}) == 955  # no duplicates
    assert {r.ref_identity for r in all_refs} == {r.ref_identity for r in records}


def test_paginate_records_deterministic_under_input_reordering():
    records = [_make_record(f"run_{i}", index=i) for i in range(955)]
    shuffled = list(records)
    random.Random(42).shuffle(shuffled)

    pages_a = paginate_records(records, page_size=200)
    pages_b = paginate_records(shuffled, page_size=200)

    refs_a = [[r.ref_identity for r in page] for page in pages_a]
    refs_b = [[r.ref_identity for r in page] for page in pages_b]
    assert refs_a == refs_b


def test_paginate_records_empty_returns_no_pages():
    assert paginate_records([], page_size=200) == []


# ---------------------------------------------------------------------------
# build_manifest_page
# ---------------------------------------------------------------------------


def test_build_manifest_page_hash_is_deterministic_and_excludes_itself():
    records = [_make_record(f"run_{i}", index=i) for i in range(3)]
    page_a = build_manifest_page(
        **HEADER_KWARGS, manifest_scope="audit", page_index=0, page_records=records
    )
    page_b = build_manifest_page(
        **HEADER_KWARGS, manifest_scope="audit", page_index=0, page_records=records
    )
    assert page_a["page_hash"] == page_b["page_hash"]

    without_hash = {k: v for k, v in page_a.items() if k != "page_hash"}
    recomputed = json.loads(json.dumps(without_hash, sort_keys=True))
    assert "page_hash" not in recomputed

    different_page = build_manifest_page(
        **HEADER_KWARGS, manifest_scope="audit", page_index=1, page_records=records
    )
    assert different_page["page_hash"] != page_a["page_hash"]


def test_build_manifest_page_hash_stable_across_different_job_id_and_timestamp():
    """Regression: a retry with a new job_id/timestamp but identical evidence
    must produce the same page_hash, or resume-by-hash-comparison can never
    succeed (every retry would look like a hash mismatch)."""
    records = [_make_record(f"run_{i}", index=i) for i in range(3)]
    attempt_1 = build_manifest_page(
        **{**HEADER_KWARGS, "aggregation_job_id": "job_1", "created_at": "2026-06-24T00:00:00Z"},
        manifest_scope="audit",
        page_index=0,
        page_records=records,
    )
    attempt_2 = build_manifest_page(
        **{**HEADER_KWARGS, "aggregation_job_id": "job_2", "created_at": "2026-06-24T01:00:00Z"},
        manifest_scope="audit",
        page_index=0,
        page_records=records,
    )
    assert attempt_1["page_hash"] == attempt_2["page_hash"]
    assert attempt_1["aggregation_job_id"] != attempt_2["aggregation_job_id"]


def test_build_manifest_header_v2_hash_stable_across_different_job_id_and_timestamp():
    attempt_1 = build_manifest_header_v2(
        **{**HEADER_KWARGS, "aggregation_job_id": "job_1", "created_at": "2026-06-24T00:00:00Z"},
        manifest_scope="audit",
        source_ref_count=3,
        page_size=200,
        page_hashes=["h0"],
    )
    attempt_2 = build_manifest_header_v2(
        **{**HEADER_KWARGS, "aggregation_job_id": "job_2", "created_at": "2026-06-24T01:00:00Z"},
        manifest_scope="audit",
        source_ref_count=3,
        page_size=200,
        page_hashes=["h0"],
    )
    assert attempt_1["manifest_hash"] == attempt_2["manifest_hash"]


def test_build_manifest_page_fields():
    records = [_make_record("run_0", index=0)]
    page = build_manifest_page(
        **HEADER_KWARGS, manifest_scope="endpoint:ep_a", page_index=2, page_records=records
    )
    assert page["manifest_version"] == LINEAGE_MANIFEST_VERSION_V2
    assert page["record_kind"] == "lineage_manifest_page"
    assert page["manifest_scope"] == "endpoint:ep_a"
    assert page["page_index"] == 2
    assert page["page_ref_count"] == 1
    assert len(page["source_raw_result_refs"]) == 1


# ---------------------------------------------------------------------------
# Worst-case byte-size validation (pins the documented ceiling)
# ---------------------------------------------------------------------------


def test_worst_case_page_at_documented_ceiling_stays_under_byte_cap():
    records = [_worst_case_record(i) for i in range(MAX_MANIFEST_PAGE_REF_COUNT)]
    page = build_manifest_page(
        **WORST_CASE_HEADER_KWARGS,
        manifest_scope=f"endpoint:{'E' * 128}",
        page_index=0,
        page_records=records,
    )
    size = len(json.dumps(page, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    assert size <= MAX_MANIFEST_BYTES


def test_worst_case_page_one_ref_over_ceiling_exceeds_byte_cap():
    records = [_worst_case_record(i) for i in range(MAX_MANIFEST_PAGE_REF_COUNT + 1)]
    page = build_manifest_page(
        **WORST_CASE_HEADER_KWARGS,
        manifest_scope=f"endpoint:{'E' * 128}",
        page_index=0,
        page_records=records,
    )
    size = len(json.dumps(page, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    assert size > MAX_MANIFEST_BYTES


def test_lineage_page_size_has_safety_margin_under_worst_case_ceiling():
    assert LINEAGE_PAGE_SIZE < MAX_MANIFEST_PAGE_REF_COUNT


# ---------------------------------------------------------------------------
# build_manifest_header_v2
# ---------------------------------------------------------------------------


def test_build_manifest_header_v2_is_bounded_no_ref_or_hash_list_fields():
    header = build_manifest_header_v2(
        **HEADER_KWARGS,
        manifest_scope="audit",
        source_ref_count=955,
        page_size=200,
        page_hashes=["h0", "h1", "h2", "h3", "h4"],
    )
    assert "source_raw_result_refs" not in header
    assert "page_hashes" not in header
    assert header["manifest_version"] == LINEAGE_MANIFEST_VERSION_V2
    assert header["source_ref_count"] == 955
    assert header["lineage_page_count"] == 5
    assert header["page_size"] == 200
    assert "manifest_hash" in header


def test_build_manifest_header_v2_hash_sensitive_to_page_hashes():
    header_a = build_manifest_header_v2(
        **HEADER_KWARGS,
        manifest_scope="audit",
        source_ref_count=2,
        page_size=200,
        page_hashes=["h0", "h1"],
    )
    header_b = build_manifest_header_v2(
        **HEADER_KWARGS,
        manifest_scope="audit",
        source_ref_count=2,
        page_size=200,
        page_hashes=["h0", "DIFFERENT"],
    )
    assert header_a["manifest_hash"] != header_b["manifest_hash"]


def test_build_manifest_header_v2_size_is_negligible_at_worst_case_ids():
    header = build_manifest_header_v2(
        client_id="C" * 128,
        audit_id="A" * 128,
        audit_execution_id="exec_" + "R" * 128,
        config_version="v" * 32,
        aggregation_version="agg_v1",
        aggregation_job_id="aggjob_" + "R" * 128,
        created_at="2026-06-24T00:00:00Z",
        manifest_scope=f"endpoint:{'E' * 128}",
        source_ref_count=10_000_000,
        page_size=200,
        page_hashes=["h" * 64] * 100_000,
    )
    size = len(json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    assert size < 5_000, "header must stay tiny regardless of page count"


# ---------------------------------------------------------------------------
# manifest_ref — must surface lineage_page_count when present
# ---------------------------------------------------------------------------


def test_manifest_ref_includes_lineage_page_count_for_v2_header():
    header = build_manifest_header_v2(
        **HEADER_KWARGS,
        manifest_scope="audit",
        source_ref_count=5,
        page_size=200,
        page_hashes=["h0"],
    )
    ref = manifest_ref(header, pk="CLIENT#client", sk="SK#x")
    assert ref["lineage_page_count"] == 1


def test_manifest_ref_lineage_page_count_none_for_v1_shaped_manifest():
    v1_like = {
        "manifest_version": "lineage_manifest_v1",
        "manifest_scope": "audit",
        "manifest_hash": "abc",
        "source_ref_count": 5,
    }
    ref = manifest_ref(v1_like, pk="CLIENT#client", sk="SK#x")
    assert ref["lineage_page_count"] is None
