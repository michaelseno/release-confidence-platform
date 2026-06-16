"""CLI command definitions for the Engineering Retrieval Layer.

All commands are read-only. This module owns argument parsing and output
formatting only. Business logic lives in RetrievalService.
"""

from __future__ import annotations

import argparse
from typing import Any

from release_confidence_platform.operator_cli.result import CommandResult
from release_confidence_platform.retrieval.filters import parse_filters
from release_confidence_platform.retrieval.formatter import RetrievalFormatter
from release_confidence_platform.retrieval.service import RetrievalService

_COMMANDS = [
    ("aggregation-results", "Return aggregate artifact set for an audit"),
    ("aggregation-metadata", "Return aggregation job metadata: status, counts, timestamps"),
    ("aggregation-lineage", "Return lineage manifest references and source ref counts"),
    ("aggregation-status", "Return current aggregation job status and reason code"),
    ("orchestration-timeline", "Return chronological orchestration events"),
    ("lifecycle-transitions", "Return lifecycle state history for an audit"),
    ("execution-summary", "Return execution counts, durations, and outcome summary"),
    ("audit-event-timeline", "Return ordered event timeline across audit lifecycle"),
    ("engineering-logs", "Return consolidated sanitized engineering log events"),
    ("retry-history", "Return aggregation job retry attempts and outcomes"),
    ("aggregation-generation-status", "Return aggregation completeness and generation state"),
    ("aggregation-version", "Return aggregation version metadata"),
    ("evidence-references", "Return bounded lineage manifest source references"),
    ("failure-summaries", "Return failure classification counts and reason codes"),
    ("processing-timeline", "Return per-stage processing timestamps"),
]


def build_retrieve_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register all retrieve subcommands on the provided subparser action."""
    for name, help_text in _COMMANDS:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--client", required=True, help="Client ID to retrieve data for")
        p.add_argument("--audit", required=True, help="Audit ID to retrieve data for")
        p.add_argument(
            "--stage", required=True, choices=("dev", "staging", "prod"), help="Deployment stage"
        )
        p.add_argument(
            "--output",
            choices=("json", "human"),
            default="human",
            help="Output format (default: human)",
        )
        if name in (
            "aggregation-results",
            "engineering-logs",
            "execution-summary",
            "audit-event-timeline",
        ):
            p.add_argument("--run", default=None, help="Filter by run ID")
            p.add_argument("--endpoint", default=None, help="Filter by endpoint ID")
            p.add_argument("--scenario", default=None, help="Filter by scenario ID")
        if name in ("execution-summary", "audit-event-timeline", "engineering-logs"):
            p.add_argument(
                "--window",
                default=None,
                help=(
                    "ISO-8601 window range (start/end), "
                    "e.g. 2024-01-01T00:00:00Z/2024-01-02T00:00:00Z"
                ),
            )


def dispatch_retrieve(
    args: argparse.Namespace, service: RetrievalService
) -> CommandResult:
    """Route retrieve args to the correct service method and return a CommandResult."""
    command_name = getattr(args, "retrieve_command", None) or ""
    filters = parse_filters(args)
    output_format = getattr(args, "output", "human")
    stage = getattr(args, "stage", None)

    dto: Any
    aggregation_version: str | None = None
    manifest_hash: str | None = None

    if command_name == "aggregation-results":
        dto = service.get_aggregation_results(filters)
        manifest_hash = None
    elif command_name == "aggregation-metadata":
        dto = service.get_aggregation_metadata(filters)
        aggregation_version = dto.aggregation_version
    elif command_name == "aggregation-lineage":
        dto = service.get_aggregation_lineage(filters)
        aggregation_version = dto.aggregation_version
        manifest_hash = dto.manifest_hash
    elif command_name == "aggregation-status":
        dto = service.get_aggregation_status(filters)
        aggregation_version = dto.aggregation_version
    elif command_name == "orchestration-timeline":
        dto = service.get_orchestration_timeline(filters)
    elif command_name == "lifecycle-transitions":
        dto = service.get_lifecycle_transitions(filters)
    elif command_name == "execution-summary":
        dto = service.get_execution_summary(filters)
    elif command_name == "audit-event-timeline":
        dto = service.get_audit_event_timeline(filters)
    elif command_name == "engineering-logs":
        dto = service.get_engineering_logs(filters)
    elif command_name == "retry-history":
        dto = service.get_retry_history(filters)
    elif command_name == "aggregation-generation-status":
        dto = service.get_aggregation_generation_status(filters)
        aggregation_version = dto.aggregation_version
    elif command_name == "aggregation-version":
        dto = service.get_aggregation_version(filters)
        aggregation_version = dto.aggregation_version
    elif command_name == "evidence-references":
        dto = service.get_evidence_references(filters)
        manifest_hash = dto.manifest_hash
    elif command_name == "failure-summaries":
        dto = service.get_failure_summaries(filters)
    elif command_name == "processing-timeline":
        dto = service.get_processing_timeline(filters)
    else:
        raise AssertionError(f"Unknown retrieve command: {command_name!r}")

    envelope = RetrievalFormatter.build_envelope(filters, aggregation_version, manifest_hash)

    if output_format == "json":
        rendered = RetrievalFormatter.format_json(dto, envelope)
        summary = f"retrieve {command_name}: json output"
    else:
        rendered = RetrievalFormatter.format_human(dto, envelope)
        summary = f"retrieve {command_name}: human output"

    return CommandResult(
        command=f"retrieve {command_name}",
        stage=stage,
        status="success",
        summary=summary,
        data={"output_format": output_format, "rendered": rendered},
    )
