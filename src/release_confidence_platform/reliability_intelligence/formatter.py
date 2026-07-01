"""IntelligenceFormatter — canonical serialization and provenance envelope.

Produces byte-identical JSON output for identical input DTOs.
Must not mutate intelligence retrieval DTOs.

Requirements: IRET-F01, IRET-F02, IRET-F03, IRET-F04, IRET-PROV01, IRET-PROV02,
IRET-PROV03, IRET-REPR01.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import Any

from release_confidence_platform.reliability_intelligence.dtypes import (
    _INTELLIGENCE_NOTICE,
    INTELLIGENCE_RETRIEVAL_VERSION,
    IntelligenceFilter,
    IntelligenceProvenanceEnvelope,
)


class IntelligenceFormatter:
    """Stateless formatter for Phase 5.7 Intelligence Retrieval Layer output."""

    @staticmethod
    def build_envelope(
        filters: IntelligenceFilter,
        metadata: dict | None,
    ) -> IntelligenceProvenanceEnvelope:
        """Build a provenance envelope from filters and optional metadata dict."""
        md = metadata or {}
        return IntelligenceProvenanceEnvelope(
            _notice=_INTELLIGENCE_NOTICE,
            retrieved_at=datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            retrieval_version=INTELLIGENCE_RETRIEVAL_VERSION,
            intelligence_version=md.get("intelligence_version") or filters.intelligence_version,
            aggregation_version=md.get("aggregation_version") or filters.aggregation_version,
            aggregate_set_hash=md.get("aggregate_set_hash"),
            audit_id=filters.audit_id,
            client_id=filters.client_id,
            intelligence_job_id=md.get("intelligence_job_id"),
        )

    @classmethod
    def format_json(cls, data: Any, envelope: IntelligenceProvenanceEnvelope) -> str:
        """Return canonical JSON — byte-identical for identical inputs (IRET-F01, IRET-F03, IRET-REPR01)."""
        payload = {
            "_notice": envelope._notice,
            "retrieved_at": envelope.retrieved_at,
            "retrieval_version": envelope.retrieval_version,
            "intelligence_version": envelope.intelligence_version,
            "aggregation_version": envelope.aggregation_version,
            "aggregate_set_hash": envelope.aggregate_set_hash,
            "audit_id": envelope.audit_id,
            "client_id": envelope.client_id,
            "intelligence_job_id": envelope.intelligence_job_id,
            "data": cls._to_dict(data),
        }
        return json.dumps(payload, sort_keys=True, default=str)

    @classmethod
    def format_human(cls, data: Any, envelope: IntelligenceProvenanceEnvelope) -> str:
        """Return human-readable output with disclaimer at top (IRET-F02, IRET-F04, IRET-PROV03)."""
        lines = [
            envelope._notice,
            "",
            f"Retrieved at : {envelope.retrieved_at}",
            f"Client       : {envelope.client_id}",
            f"Audit        : {envelope.audit_id}",
            f"Intel version: {envelope.intelligence_version}",
            "",
            json.dumps(cls._to_dict(data), indent=2, sort_keys=True, default=str),
        ]
        return "\n".join(lines)

    @classmethod
    def _to_dict(cls, obj: Any) -> Any:
        """Recursively convert frozen dataclasses to plain dicts."""
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            result = {}
            for f in dataclasses.fields(obj):
                result[f.name] = cls._to_dict(getattr(obj, f.name))
            return result
        if isinstance(obj, dict):
            return {k: cls._to_dict(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [cls._to_dict(item) for item in obj]
        return obj
