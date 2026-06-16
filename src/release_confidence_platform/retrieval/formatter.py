"""RetrievalFormatter — canonical serialization and provenance envelope.

Produces byte-identical JSON output for identical input DTOs.
Must not mutate retrieval DTOs.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import Any

from release_confidence_platform.retrieval.dtypes import (
    _NOTICE,
    RETRIEVAL_VERSION,
    ProvenanceEnvelope,
    RetrievalFilter,
)

_JSON_SEPARATORS = (",", ":")


class RetrievalFormatter:
    """Stateless formatter for Engineering Retrieval Layer output."""

    @staticmethod
    def build_envelope(
        filters: RetrievalFilter,
        aggregation_version: str | None,
        manifest_hash: str | None,
    ) -> ProvenanceEnvelope:
        return ProvenanceEnvelope(
            retrieved_at=datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            retrieval_version=RETRIEVAL_VERSION,
            aggregation_version=aggregation_version,
            manifest_hash=manifest_hash,
            audit_id=filters.audit_id,
            client_id=filters.client_id,
        )

    @staticmethod
    def dto_to_dict(dto: Any) -> Any:
        """Recursively convert frozen dataclasses to plain dicts."""
        if dataclasses.is_dataclass(dto) and not isinstance(dto, type):
            result = {}
            for f in dataclasses.fields(dto):
                result[f.name] = RetrievalFormatter.dto_to_dict(getattr(dto, f.name))
            return result
        if isinstance(dto, tuple):
            # Check if it looks like a list of tuples (sorted key-value pairs)
            if dto and isinstance(dto[0], tuple) and len(dto[0]) == 2:
                return {k: RetrievalFormatter.dto_to_dict(v) for k, v in dto}
            return [RetrievalFormatter.dto_to_dict(item) for item in dto]
        if isinstance(dto, (list,)):
            return [RetrievalFormatter.dto_to_dict(item) for item in dto]
        return dto

    @classmethod
    def format_json(cls, dto: Any, envelope: ProvenanceEnvelope) -> str:
        """Return canonical JSON — byte-identical for identical inputs."""
        env_dict = cls.dto_to_dict(envelope)
        data_dict = cls.dto_to_dict(dto)
        payload = {**env_dict, "data": data_dict}
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=_JSON_SEPARATORS)

    @classmethod
    def format_human(cls, dto: Any, envelope: ProvenanceEnvelope) -> str:
        """Return human-readable formatted output with disclaimer at top."""
        lines: list[str] = [
            _NOTICE,
            "",
            f"retrieved_at:         {envelope.retrieved_at}",
            f"retrieval_version:    {envelope.retrieval_version}",
            f"aggregation_version:  {envelope.aggregation_version or 'n/a'}",
            f"manifest_hash:        {envelope.manifest_hash or 'n/a'}",
            f"audit_id:             {envelope.audit_id or 'n/a'}",
            f"client_id:            {envelope.client_id or 'n/a'}",
            "",
            "--- data ---",
        ]
        data_dict = cls.dto_to_dict(dto)
        cls._append_dict_lines(lines, data_dict, indent=0)
        return "\n".join(lines)

    @classmethod
    def _append_dict_lines(
        cls, lines: list[str], data: Any, indent: int = 0
    ) -> None:
        prefix = "  " * indent
        if isinstance(data, dict):
            for key in sorted(data.keys()):
                value = data[key]
                if isinstance(value, (dict, list)):
                    lines.append(f"{prefix}{key}:")
                    cls._append_dict_lines(lines, value, indent + 1)
                else:
                    lines.append(f"{prefix}{key}: {value}")
        elif isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, (dict, list)):
                    lines.append(f"{prefix}[{i}]:")
                    cls._append_dict_lines(lines, item, indent + 1)
                else:
                    lines.append(f"{prefix}- {item}")
        else:
            lines.append(f"{prefix}{data}")
