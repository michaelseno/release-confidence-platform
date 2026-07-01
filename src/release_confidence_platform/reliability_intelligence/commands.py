"""CLI command definitions for Phase 5.7 Intelligence Retrieval Layer.

All commands are read-only. This module owns argument parsing and output
formatting only. Business logic lives in IntelligenceRetrievalService.
"""
from __future__ import annotations

import argparse
from typing import Any

from release_confidence_platform.reliability_intelligence.dtypes import IntelligenceNotFoundDTO

_INTELLIGENCE_COMMANDS = [
    ("intelligence-status", "Return current intelligence job status and identifiers"),
    ("intelligence-summary", "Return full IntelligenceMetadata record fields"),
    ("intelligence-detail", "Return full S3 intelligence artifact content"),
    ("intelligence-methodology", "Return methodology_disclosure section from S3 artifact"),
]


def build_intelligence_retrieve_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register all intelligence retrieve subcommands on the provided subparser action."""
    for name, help_text in _INTELLIGENCE_COMMANDS:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--client", required=True)
        p.add_argument("--audit", required=True)
        p.add_argument("--execution", required=True)
        p.add_argument(
            "--stage", required=True, choices=("dev", "staging", "prod")
        )
        p.add_argument("--output", choices=("json", "human"), default="human")
        p.add_argument("--endpoint", default=None)
        p.add_argument(
            "--intelligence-version",
            default="intel_v1",
            dest="intelligence_version",
        )


def dispatch_intelligence_retrieve(args, service, formatter) -> str:
    """Route intelligence retrieve args to service and return formatted output."""
    from release_confidence_platform.reliability_intelligence.filters import (  # noqa: PLC0415
        parse_intelligence_filters,
    )

    filters = parse_intelligence_filters(args)
    output_format = getattr(args, "output", "human")
    command = getattr(args, "retrieve_command", "") or ""

    dto: Any
    metadata_for_envelope: dict | None = None

    if command == "intelligence-status":
        dto = service.retrieve_status(filters)
        if hasattr(dto, "intelligence_job_id"):
            metadata_for_envelope = {
                "intelligence_job_id": dto.intelligence_job_id,
                "aggregate_set_hash": None,
                "intelligence_version": filters.intelligence_version,
                "aggregation_version": filters.aggregation_version,
            }
    elif command == "intelligence-summary":
        dto = service.retrieve_summary(filters)
        if hasattr(dto, "aggregate_set_hash"):
            metadata_for_envelope = {
                "intelligence_job_id": dto.intelligence_job_id,
                "aggregate_set_hash": dto.aggregate_set_hash,
                "intelligence_version": dto.intelligence_version,
                "aggregation_version": dto.aggregation_version,
            }
    elif command == "intelligence-detail":
        dto = service.retrieve_detail(filters)
        if isinstance(dto, dict):
            cs = dto.get("composite_score", {}) or {}
            metadata_for_envelope = {
                "intelligence_job_id": None,
                "aggregate_set_hash": cs.get("aggregate_set_hash"),
                "intelligence_version": dto.get("intelligence_version"),
                "aggregation_version": dto.get("aggregation_version"),
            }
    elif command == "intelligence-methodology":
        dto = service.retrieve_methodology(filters)
        metadata_for_envelope = None
    else:
        dto = IntelligenceNotFoundDTO(
            reason="UNKNOWN_COMMAND",
            client_id=filters.client_id,
            audit_id=filters.audit_id,
        )

    envelope = formatter.build_envelope(filters, metadata_for_envelope)
    if output_format == "json":
        rendered = formatter.format_json(dto, envelope)
    else:
        rendered = formatter.format_human(dto, envelope)
    return rendered
