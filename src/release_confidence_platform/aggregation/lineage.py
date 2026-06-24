"""Lineage manifest construction.

v1 (lineage_manifest_v1) embedded every raw-result ref inline on a single
DynamoDB item. That format is read-only going forward (existing v1 records
are immutable and never migrated) — see
docs/architecture/adr_phase_4_evidence_lineage_aggregation.md and
docs/architecture/adr_phase_4a_lineage_manifest_pagination.md.

v2 (lineage_manifest_v2) is a bounded header plus immutable, fixed-size,
independently-hashed pages. All new aggregation writes use v2.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from release_confidence_platform.aggregation.constants import (
    LINEAGE_MANIFEST_VERSION_V2,
    LINEAGE_PAGE_SIZE,
)
from release_confidence_platform.aggregation.models import RawAggregationRecord


def canonical_json_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def paginate_records(
    records: list[RawAggregationRecord], *, page_size: int = LINEAGE_PAGE_SIZE
) -> list[list[RawAggregationRecord]]:
    """Partition records into deterministic, fixed-size pages.

    Records are sorted by canonical ref_identity first, so identical raw
    evidence always produces identical page boundaries regardless of input
    order or retry.
    """
    ordered = sorted(records, key=lambda record: record.ref_identity)
    if not ordered:
        return []
    return [ordered[i : i + page_size] for i in range(0, len(ordered), page_size)]


def build_manifest_page(
    *,
    client_id: str,
    audit_id: str,
    audit_execution_id: str,
    config_version: str,
    aggregation_version: str,
    aggregation_job_id: str,
    created_at: str,
    manifest_scope: str,
    page_index: int,
    page_records: list[RawAggregationRecord],
) -> dict[str, Any]:
    """Build one immutable lineage manifest page.

    `page_hash` is computed only over content that is a pure function of the
    raw evidence (excludes `aggregation_job_id` and `created_at`, which vary
    between retry attempts of the same logical aggregation) so a retry can
    detect "this page already exists and matches" rather than always seeing
    a spurious mismatch because a different job/timestamp produced it.
    """
    refs = [record.source_ref() for record in page_records]
    hashable = {
        "manifest_version": LINEAGE_MANIFEST_VERSION_V2,
        "record_kind": "lineage_manifest_page",
        "manifest_scope": manifest_scope,
        "client_id": client_id,
        "audit_id": audit_id,
        "audit_execution_id": audit_execution_id,
        "config_version": config_version,
        "aggregation_version": aggregation_version,
        "page_index": page_index,
        "page_ref_count": len(refs),
        "source_raw_result_refs": refs,
    }
    return {
        **hashable,
        "aggregation_job_id": aggregation_job_id,
        "created_at": created_at,
        "page_hash": canonical_json_hash(hashable),
    }


def build_manifest_header_v2(
    *,
    client_id: str,
    audit_id: str,
    audit_execution_id: str,
    config_version: str,
    aggregation_version: str,
    aggregation_job_id: str,
    created_at: str,
    manifest_scope: str,
    source_ref_count: int,
    page_size: int,
    page_hashes: list[str],
) -> dict[str, Any]:
    """Build a bounded lineage manifest header.

    `page_hashes` is used only to compute `manifest_hash` (an ordered
    hash-of-hashes committing to every page's exact content) — it is
    deliberately NOT a field on the returned header, so the persisted header
    stays a fixed, tiny size regardless of how many pages exist.

    `manifest_hash` excludes `aggregation_job_id` and `created_at` (which
    vary between retry attempts of the same logical aggregation) so that
    identical raw evidence always produces an identical hash, regardless of
    which attempt/timestamp ultimately wrote it.
    """
    hashable = {
        "manifest_version": LINEAGE_MANIFEST_VERSION_V2,
        "record_kind": "lineage_manifest",
        "manifest_scope": manifest_scope,
        "client_id": client_id,
        "audit_id": audit_id,
        "audit_execution_id": audit_execution_id,
        "config_version": config_version,
        "aggregation_version": aggregation_version,
        "source_ref_count": source_ref_count,
        "lineage_page_count": len(page_hashes),
        "page_size": page_size,
    }
    manifest_hash = canonical_json_hash({**hashable, "page_hashes": page_hashes})
    return {
        **hashable,
        "aggregation_job_id": aggregation_job_id,
        "created_at": created_at,
        "manifest_hash": manifest_hash,
    }


def manifest_ref(manifest: dict[str, Any], *, pk: str, sk: str) -> dict[str, Any]:
    return {
        "manifest_version": manifest["manifest_version"],
        "manifest_scope": manifest["manifest_scope"],
        "manifest_hash": manifest["manifest_hash"],
        "source_ref_count": manifest["source_ref_count"],
        "lineage_page_count": manifest.get("lineage_page_count"),
        "storage": "dynamodb",
        "PK": pk,
        "SK": sk,
    }
