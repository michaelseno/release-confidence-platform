"""CLI command definitions for Phase 6.7 Engineering Retrieval CLI.

All commands are read-only. This module owns argument parsing and output
formatting only. Business logic lives in ReportRetrievalService.

Seven subcommands are registered under the `retrieve` group:
    report-status       DynamoDB only: status, identifiers, score fields
    report-summary      DynamoDB + S3: executive_summary section
    report-endpoints    DynamoDB + S3: per-endpoint scores table
    report-methodology  DynamoDB + S3: methodology_disclosure section
    report-lineage      DynamoDB + S3: input_lineage section
    report-json         DynamoDB + S3: full artifact JSON (no envelope)
    report-markdown     DynamoDB + S3: MarkdownFormatter output (no envelope)
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from release_confidence_platform.core.exceptions import ValidationError

_REPORT_COMMANDS = [
    ("report-status", "Return report status and identifiers (DynamoDB only)"),
    ("report-summary", "Return executive summary section"),
    ("report-endpoints", "Return all endpoint scores"),
    ("report-methodology", "Return full methodology_disclosure section"),
    ("report-lineage", "Return input_lineage section"),
    ("report-json", "Return full report JSON artifact (pretty-printed)"),
    ("report-markdown", "Return Markdown-formatted report"),
]

_REPORT_VERSION_DEFAULT = "report_v1"


# ---------------------------------------------------------------------------
# Parser registration
# ---------------------------------------------------------------------------


def _add_shared_args(p: argparse.ArgumentParser) -> None:
    """Add the shared argument set to a report retrieve subcommand parser."""
    p.add_argument("--client-id", required=True, dest="client_id")
    p.add_argument("--audit-id", required=True, dest="audit_id")
    p.add_argument("--execution", required=True)
    p.add_argument("--config-version", required=True, dest="config_version")
    p.add_argument("--aggregation-version", required=True, dest="aggregation_version")
    p.add_argument("--intelligence-version", required=True, dest="intelligence_version")
    p.add_argument(
        "--report-version",
        default=_REPORT_VERSION_DEFAULT,
        dest="report_version",
    )
    p.add_argument("--stage", required=True, choices=("dev", "staging", "prod"))
    p.add_argument("--output", choices=("text", "json"), default="text")


def build_report_retrieve_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register all seven retrieve report-* subcommands on the provided subparser action."""
    for name, help_text in _REPORT_COMMANDS:
        p = sub.add_parser(name, help=help_text)
        _add_shared_args(p)


# ---------------------------------------------------------------------------
# Provenance envelope
# ---------------------------------------------------------------------------


def _provenance_envelope(
    report_id: str,
    report_version: str,
    intelligence_version: str,
    audit_id: str,
    generated_at: str,
) -> str:
    """Render the 5-line provenance envelope header."""
    lines = [
        f"Report ID:             {report_id}",
        f"Report Version:        {report_version}",
        f"Intelligence Version:  {intelligence_version}",
        f"Audit ID:              {audit_id}",
        f"Generated At:          {generated_at}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Service call argument extractor
# ---------------------------------------------------------------------------


def _svc_args(args: Any) -> tuple:
    """Extract the ordered service call arguments from a parsed args namespace."""
    return (
        args.client_id,
        args.audit_id,
        args.execution,
        args.config_version,
        args.aggregation_version,
        args.intelligence_version,
        args.report_version,
    )


# ---------------------------------------------------------------------------
# Handler: report-status (DynamoDB only)
# ---------------------------------------------------------------------------


def _handle_report_status(args: Any, svc: Any) -> str:
    metadata = svc.get_report_status(*_svc_args(args))
    if metadata is None:
        raise ValidationError("REPORT_NOT_FOUND")
    envelope = _provenance_envelope(
        report_id=metadata.get("report_id", "N/A"),
        report_version=metadata.get("report_version", "N/A"),
        intelligence_version=metadata.get("intelligence_version", "N/A"),
        audit_id=metadata.get("audit_id", "N/A"),
        generated_at=metadata.get("completed_at", "N/A"),
    )
    lines = [
        envelope,
        "",
        f"Status:        {metadata.get('status', 'N/A')}",
        f"Score Label:   {metadata.get('score_label', 'N/A')}",
        f"Report Job ID: {metadata.get('report_job_id', 'N/A')}",
        f"Report ID:     {metadata.get('report_id', 'N/A')}",
        f"Completed At:  {metadata.get('completed_at', 'N/A')}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Handler: report-summary
# ---------------------------------------------------------------------------


def _handle_report_summary(args: Any, svc: Any) -> str:
    dto = svc.get_report_dto(*_svc_args(args))
    envelope = _provenance_envelope(
        report_id=dto.identity.report_id,
        report_version=dto.identity.report_version,
        intelligence_version=dto.intelligence_provenance.intelligence_version,
        audit_id=dto.intelligence_provenance.audit_id,
        generated_at=dto.identity.generated_at,
    )
    es = dto.executive_summary
    lines = [
        envelope,
        "",
        f"Score Label:              {es.score_label}",
        f"Composite Score:          {es.composite_score_value:.3f}",
        f"Endpoint Count:           {es.endpoint_count}",
        f"Audit Success Rate:       {es.audit_success_rate:.3f}",
        f"Total Executions:         {es.total_executions}",
        f"Score Label Description:  {es.score_label_description}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Handler: report-endpoints
# ---------------------------------------------------------------------------


def _handle_report_endpoints(args: Any, svc: Any) -> str:
    dto = svc.get_report_dto(*_svc_args(args))
    envelope = _provenance_envelope(
        report_id=dto.identity.report_id,
        report_version=dto.identity.report_version,
        intelligence_version=dto.intelligence_provenance.intelligence_version,
        audit_id=dto.intelligence_provenance.audit_id,
        generated_at=dto.identity.generated_at,
    )
    col_w = 42
    header = (
        f"{'Endpoint ID':<{col_w}} {'Composite':>10} {'Reliability':>12}"
        f" {'Stability':>10} {'Burst':>8} {'Consistency':>12}"
    )
    separator = "-" * len(header)
    rows = [header, separator]
    for ep in dto.endpoints:
        sc = ep.endpoint_score
        rows.append(
            f"{ep.endpoint_id:<{col_w}} {sc.composite_score:>10.3f}"
            f" {sc.reliability_score:>12.3f} {sc.stability_score:>10.3f}"
            f" {sc.burst_score:>8.3f} {sc.consistency_score:>12.3f}"
        )
    return envelope + "\n\n" + "\n".join(rows)


# ---------------------------------------------------------------------------
# Handler: report-methodology
# ---------------------------------------------------------------------------


def _handle_report_methodology(args: Any, svc: Any) -> str:
    dto = svc.get_report_dto(*_svc_args(args))
    envelope = _provenance_envelope(
        report_id=dto.identity.report_id,
        report_version=dto.identity.report_version,
        intelligence_version=dto.intelligence_provenance.intelligence_version,
        audit_id=dto.intelligence_provenance.audit_id,
        generated_at=dto.identity.generated_at,
    )
    md = dto.methodology_disclosure
    limitations = "\n".join(f"  - {lim}" for lim in md.limitations)
    lines = [
        envelope,
        "",
        f"Intelligence Version:  {md.intelligence_version}",
        "",
        "Limitations:",
        limitations,
        "",
        "Scoring:",
        json.dumps(md.scoring, indent=2, sort_keys=True),
        "",
        "Stability Label Definitions:",
        json.dumps(md.stability_label_definitions, indent=2, sort_keys=True),
        "",
        "Burst Label Definitions:",
        json.dumps(md.burst_label_definitions, indent=2, sort_keys=True),
        "",
        "Consistency Label Definitions:",
        json.dumps(md.consistency_label_definitions, indent=2, sort_keys=True),
        "",
        "Label to Score Mapping:",
        json.dumps(md.label_to_score_mapping, indent=2, sort_keys=True),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Handler: report-lineage
# ---------------------------------------------------------------------------


def _handle_report_lineage(args: Any, svc: Any) -> str:
    dto = svc.get_report_dto(*_svc_args(args))
    envelope = _provenance_envelope(
        report_id=dto.identity.report_id,
        report_version=dto.identity.report_version,
        intelligence_version=dto.intelligence_provenance.intelligence_version,
        audit_id=dto.intelligence_provenance.audit_id,
        generated_at=dto.identity.generated_at,
    )
    il = dto.input_lineage
    lines = [
        envelope,
        "",
        f"Aggregate Set Hash:              {il.aggregate_set_hash}",
        f"Aggregation Job ID:              {il.aggregation_job_id}",
        f"Aggregation Version:             {il.aggregation_version}",
        f"Aggregate Set Completion:        {il.aggregate_set_completion_created_at}",
        f"Endpoint Aggregate Count:        {il.endpoint_aggregate_count}",
        f"Source Raw Result Count:         {il.source_raw_result_count}",
        f"Audit Lineage Manifest Ref:      "
        f"{json.dumps(il.audit_lineage_manifest_ref, sort_keys=True)}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Handler: report-json (no envelope)
# ---------------------------------------------------------------------------


def _handle_report_json(args: Any, svc: Any) -> str:
    artifact = svc.get_report_artifact(*_svc_args(args))
    return json.dumps(artifact, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Handler: report-markdown (no envelope)
# ---------------------------------------------------------------------------


def _handle_report_markdown(args: Any, svc: Any, formatter: Any) -> str:
    dto = svc.get_report_dto(*_svc_args(args))
    return formatter.render(dto)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_DISPATCH_TABLE: dict[str, Any] = {
    "report-status": _handle_report_status,
    "report-summary": _handle_report_summary,
    "report-endpoints": _handle_report_endpoints,
    "report-methodology": _handle_report_methodology,
    "report-lineage": _handle_report_lineage,
    "report-json": _handle_report_json,
    "report-markdown": _handle_report_markdown,
}


def dispatch_report_retrieve(args: Any, svc: Any, formatter: Any = None) -> str:
    """Route retrieve report-* args to the appropriate handler.

    Args:
        args: Parsed argparse namespace containing retrieve_command and all
              shared report retrieve arguments.
        svc: ReportRetrievalService instance (or duck-typed equivalent).
        formatter: MarkdownFormatter instance required for report-markdown;
                   unused by all other commands.

    Returns:
        Rendered string output suitable for direct printing.

    Raises:
        ValidationError: If the command is unknown, or if the report is not found.
    """
    command = getattr(args, "retrieve_command", "") or ""
    handler = _DISPATCH_TABLE.get(command)
    if handler is None:
        raise ValidationError(f"Unknown report retrieve command: {command!r}")
    if command == "report-markdown":
        return handler(args, svc, formatter)
    return handler(args, svc)
