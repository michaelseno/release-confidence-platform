"""DTO helpers for Phase 4 aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RawAggregationRecord:
    raw_result_version: str
    run_id: str
    raw_result_s3_key: str
    s3_version_id: str | None
    result_index: int
    endpoint_id: str
    result_timestamp: str | None
    duration_ms: int | float | None
    status_code: int | None
    failure_type: str

    @property
    def ref_identity(self) -> tuple[str, str | None, str, int]:
        return (self.raw_result_s3_key, self.s3_version_id, self.run_id, self.result_index)

    def source_ref(self) -> dict[str, Any]:
        return {
            "raw_result_version": self.raw_result_version,
            "run_id": self.run_id,
            "raw_result_s3_key": self.raw_result_s3_key,
            "s3_version_id": self.s3_version_id,
            "object_version_lineage_available": self.s3_version_id is not None,
            "result_index": self.result_index,
            "endpoint_id": self.endpoint_id,
            "result_timestamp": self.result_timestamp,
        }
