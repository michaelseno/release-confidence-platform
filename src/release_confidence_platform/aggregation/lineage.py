"""Lineage manifest construction."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from release_confidence_platform.aggregation.constants import LINEAGE_MANIFEST_VERSION
from release_confidence_platform.aggregation.models import RawAggregationRecord


def canonical_json_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def build_manifest(
    *,
    client_id: str,
    audit_id: str,
    audit_execution_id: str,
    config_version: str,
    aggregation_version: str,
    aggregation_job_id: str,
    created_at: str,
    manifest_scope: str,
    records: list[RawAggregationRecord],
) -> dict[str, Any]:
    refs = [
        record.source_ref() for record in sorted(records, key=lambda record: record.ref_identity)
    ]
    base = {
        "manifest_version": LINEAGE_MANIFEST_VERSION,
        "manifest_scope": manifest_scope,
        "client_id": client_id,
        "audit_id": audit_id,
        "audit_execution_id": audit_execution_id,
        "config_version": config_version,
        "aggregation_version": aggregation_version,
        "aggregation_job_id": aggregation_job_id,
        "created_at": created_at,
        "source_ref_count": len(refs),
        "source_raw_result_refs": refs,
    }
    base["manifest_hash"] = canonical_json_hash(base)
    return base


def manifest_ref(manifest: dict[str, Any], *, pk: str, sk: str) -> dict[str, Any]:
    return {
        "manifest_version": manifest["manifest_version"],
        "manifest_scope": manifest["manifest_scope"],
        "manifest_hash": manifest["manifest_hash"],
        "source_ref_count": manifest["source_ref_count"],
        "storage": "dynamodb",
        "PK": pk,
        "SK": sk,
    }
