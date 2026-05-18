"""S3-backed Phase 2 data-pool loading and deterministic assignment."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from packages.core.exceptions import EngineError

SAFE_POOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class DataPoolError(EngineError):
    def __init__(self, message: str = "Data pool validation failed"):
        super().__init__("PAYLOAD_VALIDATION_ERROR", message)


class DataPoolLoader:
    def __init__(self, s3_storage: Any):
        self.s3_storage = s3_storage
        self._cache: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def build_key(self, client_id: str, pool_name: str) -> str:
        if not isinstance(pool_name, str) or not SAFE_POOL_NAME.fullmatch(pool_name):
            raise DataPoolError("Invalid data_pool_name")
        return f"data-pools/{client_id}/{pool_name}.json"

    def load(self, client_id: str, pool_name: str) -> list[dict[str, Any]]:
        cache_key = (client_id, pool_name)
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            raw = self.s3_storage.read_json(self.build_key(client_id, pool_name))
        except Exception as exc:
            raise DataPoolError("Data pool could not be loaded") from exc
        records = normalize_data_pool(raw)
        self._cache[cache_key] = records
        return records


def normalize_data_pool(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        records = raw
    elif isinstance(raw, dict):
        records = raw.get("records")
    else:
        records = None
    if not isinstance(records, list) or not records:
        raise DataPoolError("Data pool records must be a non-empty list")
    if not all(isinstance(record, dict) and record for record in records):
        raise DataPoolError("Data pool records must be non-empty objects")
    return records


def select_record(
    records: list[dict[str, Any]],
    *,
    client_id: str,
    audit_id: str,
    run_id: str,
    endpoint_id: str,
    scenario_type: str,
    iteration: int,
) -> dict[str, Any]:
    seed = "|".join([client_id, audit_id, run_id, endpoint_id, scenario_type, str(iteration)])
    index = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % len(records)
    return records[index]
