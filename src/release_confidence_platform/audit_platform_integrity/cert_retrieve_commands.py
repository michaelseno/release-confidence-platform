"""CLI command definitions for Phase 7.7 Certification Retrieval CLI.

All commands are unconditionally read-only. This module owns argument parsing,
service routing, and output formatting. Business logic lives in
CertificationRetrievalService.

Four subcommands registered under the `retrieve` group:
    cert-status   DynamoDB only: terminal_state, certificate_id, certjob_id,
                  s3_cert_ref, s3_report_artifact_ref, timestamps
    cert-summary  DynamoDB only: full CertificationMetadata record fields
    cert-domains  DynamoDB + S3: domain_results[] array from the certificate artifact
    cert-json     DynamoDB + S3: complete certificate artifact JSON (no envelope)

Provenance envelope (human output): certificate_version, certificate_id,
terminal_state, report_id, generated_at.

No CertificationJob, CertificationMetadata, ReportMetadata, or any other DynamoDB
record may be written, updated, or deleted by any code in this module.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from release_confidence_platform.core.exceptions import ValidationError

_CERT_COMMANDS = [
    ("cert-status", "Return CertificationMetadata status and identifiers (DynamoDB only)"),
    ("cert-summary", "Return full CertificationMetadata record fields (DynamoDB only)"),
    ("cert-domains", "Return full per-domain verification results from certificate artifact (S3)"),
    ("cert-json", "Return full Platform Integrity Certificate JSON artifact (S3)"),
]

_CERT_VERSION_DEFAULT = "cert_v1"


# ---------------------------------------------------------------------------
# CertificationRetrievalService
# ---------------------------------------------------------------------------


class CertificationRetrievalService:
    """Read-only query service for the Phase 7 Certification Retrieval Layer.

    Never writes, updates, or deletes any record. All S3 reads use the
    s3_certificate_ref stored in CertificationMetadata — the key is never
    constructed independently.
    """

    def __init__(
        self,
        repository: Any,
        publisher: Any,
    ) -> None:
        self._repository = repository
        self._publisher = publisher

    def _get_metadata_or_raise(
        self,
        client_id: str,
        audit_id: str,
        exec_id: str,
        config_v: str,
        agg_v: str,
        intel_v: str,
        report_v: str,
        cert_v: str,
    ) -> dict[str, Any]:
        """Fetch CertificationMetadata or raise CERTIFICATION_NOT_FOUND."""
        metadata = self._repository.get_cert_metadata(
            client_id, audit_id, exec_id, config_v, agg_v, intel_v, report_v, cert_v
        )
        if metadata is None:
            raise ValidationError("CERTIFICATION_NOT_FOUND", "CERTIFICATION_NOT_FOUND")
        return metadata

    def get_cert_status(
        self,
        client_id: str,
        audit_id: str,
        exec_id: str,
        config_v: str,
        agg_v: str,
        intel_v: str,
        report_v: str,
        cert_v: str,
    ) -> dict[str, Any]:
        """Return key CertificationMetadata fields. DynamoDB-only read.

        Raises:
            ValidationError: If no CertificationMetadata record exists.
        """
        metadata = self._get_metadata_or_raise(
            client_id, audit_id, exec_id, config_v, agg_v, intel_v, report_v, cert_v
        )
        return {
            "terminal_state": metadata.get("terminal_state"),
            "certificate_id": metadata.get("certificate_id"),
            "certjob_id": metadata.get("certjob_id"),
            "s3_cert_ref": metadata.get("s3_certificate_ref"),
            "s3_report_artifact_ref": metadata.get("s3_report_artifact_ref"),
            "certificate_version": metadata.get("certificate_version"),
            "report_id": metadata.get("report_id"),
            "generated_at": metadata.get("completed_at"),
        }

    def get_cert_summary(
        self,
        client_id: str,
        audit_id: str,
        exec_id: str,
        config_v: str,
        agg_v: str,
        intel_v: str,
        report_v: str,
        cert_v: str,
    ) -> dict[str, Any]:
        """Return full CertificationMetadata record. DynamoDB-only read.

        Raises:
            ValidationError: If no CertificationMetadata record exists.
        """
        return self._get_metadata_or_raise(
            client_id, audit_id, exec_id, config_v, agg_v, intel_v, report_v, cert_v
        )

    def get_cert_domains(
        self,
        client_id: str,
        audit_id: str,
        exec_id: str,
        config_v: str,
        agg_v: str,
        intel_v: str,
        report_v: str,
        cert_v: str,
    ) -> dict[str, Any]:
        """Return domain_results[] from the S3 certificate artifact.

        DynamoDB read for s3_certificate_ref; S3 read for artifact content.

        Returns:
            Dict with provenance fields and domain_results list.

        Raises:
            ValidationError: If CertificationMetadata absent or has no s3_certificate_ref.
            StorageError: On S3 read failure.
        """
        metadata = self._get_metadata_or_raise(
            client_id, audit_id, exec_id, config_v, agg_v, intel_v, report_v, cert_v
        )
        s3_ref = metadata.get("s3_certificate_ref")
        if not s3_ref:
            raise ValidationError(
                "CertificationMetadata has no s3_certificate_ref", "CERTIFICATION_NOT_FOUND"
            )
        artifact = self._publisher.read_artifact(s3_ref)
        return {
            "certificate_id": metadata.get("certificate_id"),
            "certificate_version": metadata.get("certificate_version"),
            "terminal_state": metadata.get("terminal_state"),
            "report_id": metadata.get("report_id"),
            "generated_at": metadata.get("completed_at"),
            "domain_results": artifact.get("domain_results", []),
        }

    def get_cert_json(
        self,
        client_id: str,
        audit_id: str,
        exec_id: str,
        config_v: str,
        agg_v: str,
        intel_v: str,
        report_v: str,
        cert_v: str,
    ) -> dict[str, Any]:
        """Return the complete certificate artifact dict from S3.

        DynamoDB read for s3_certificate_ref; S3 read for artifact content.

        Returns:
            Parsed certificate artifact dict.

        Raises:
            ValidationError: If CertificationMetadata absent or has no s3_certificate_ref.
            StorageError: On S3 read failure.
        """
        metadata = self._get_metadata_or_raise(
            client_id, audit_id, exec_id, config_v, agg_v, intel_v, report_v, cert_v
        )
        s3_ref = metadata.get("s3_certificate_ref")
        if not s3_ref:
            raise ValidationError(
                "CertificationMetadata has no s3_certificate_ref", "CERTIFICATION_NOT_FOUND"
            )
        return self._publisher.read_artifact(s3_ref)


# ---------------------------------------------------------------------------
# Parser registration
# ---------------------------------------------------------------------------


def _add_shared_args(p: argparse.ArgumentParser) -> None:
    """Add the shared argument set to all cert retrieve subcommand parsers."""
    p.add_argument("--client-id", required=True, dest="client_id")
    p.add_argument("--audit-id", required=True, dest="audit_id")
    p.add_argument("--execution", required=True)
    p.add_argument("--stage", required=True, choices=("dev", "staging", "prod"))
    p.add_argument(
        "--config-version",
        default="v1",
        dest="config_version",
    )
    p.add_argument(
        "--aggregation-version",
        default="agg_v1",
        dest="aggregation_version",
    )
    p.add_argument(
        "--intelligence-version",
        default="intel_v1",
        dest="intelligence_version",
    )
    p.add_argument(
        "--report-version",
        default="report_v1",
        dest="report_version",
    )
    p.add_argument(
        "--cert-version",
        default=_CERT_VERSION_DEFAULT,
        dest="cert_version",
    )
    p.add_argument("--output", choices=("json", "human"), default="human")


def build_cert_retrieve_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register all four cert-* retrieve subcommands on the provided subparser action."""
    for name, help_text in _CERT_COMMANDS:
        p = sub.add_parser(name, help=help_text)
        _add_shared_args(p)


# ---------------------------------------------------------------------------
# Provenance envelope
# ---------------------------------------------------------------------------


def _provenance_envelope(
    certificate_id: str | None,
    certificate_version: str | None,
    terminal_state: str | None,
    report_id: str | None,
    generated_at: str | None,
) -> str:
    """Render the provenance envelope header for human output."""
    lines = [
        f"Certificate ID:      {certificate_id or 'N/A'}",
        f"Certificate Version: {certificate_version or 'N/A'}",
        f"Terminal State:      {terminal_state or 'N/A'}",
        f"Report ID:           {report_id or 'N/A'}",
        f"Generated At:        {generated_at or 'N/A'}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Service call argument extractor
# ---------------------------------------------------------------------------


def _svc_args(args: Any) -> tuple:
    """Extract ordered service call arguments from a parsed args namespace."""
    return (
        args.client_id,
        args.audit_id,
        args.execution,
        args.config_version,
        args.aggregation_version,
        args.intelligence_version,
        args.report_version,
        args.cert_version,
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_cert_status(args: Any, svc: CertificationRetrievalService) -> str:
    """Render cert-status: key fields from CertificationMetadata."""
    data = svc.get_cert_status(*_svc_args(args))
    envelope = _provenance_envelope(
        certificate_id=data.get("certificate_id"),
        certificate_version=data.get("certificate_version"),
        terminal_state=data.get("terminal_state"),
        report_id=data.get("report_id"),
        generated_at=data.get("generated_at"),
    )
    lines = [
        envelope,
        "",
        f"Terminal State:          {data.get('terminal_state', 'N/A')}",
        f"Certificate ID:          {data.get('certificate_id', 'N/A')}",
        f"Cert Job ID:             {data.get('certjob_id', 'N/A')}",
        f"S3 Cert Ref:             {data.get('s3_cert_ref', 'N/A')}",
        f"S3 Report Artifact Ref:  {data.get('s3_report_artifact_ref', 'N/A')}",
    ]
    return "\n".join(lines)


def _handle_cert_summary(args: Any, svc: CertificationRetrievalService) -> str:
    """Render cert-summary: all CertificationMetadata fields."""
    data = svc.get_cert_summary(*_svc_args(args))
    envelope = _provenance_envelope(
        certificate_id=data.get("certificate_id"),
        certificate_version=data.get("certificate_version"),
        terminal_state=data.get("terminal_state"),
        report_id=data.get("report_id"),
        generated_at=data.get("completed_at"),
    )
    lines = [
        envelope,
        "",
        f"Client ID:               {data.get('client_id', 'N/A')}",
        f"Audit ID:                {data.get('audit_id', 'N/A')}",
        f"Audit Execution ID:      {data.get('audit_execution_id', 'N/A')}",
        f"Config Version:          {data.get('config_version', 'N/A')}",
        f"Aggregation Version:     {data.get('aggregation_version', 'N/A')}",
        f"Intelligence Version:    {data.get('intelligence_version', 'N/A')}",
        f"Report Version:          {data.get('report_version', 'N/A')}",
        f"Cert Version:            {data.get('cert_version', 'N/A')}",
        f"Terminal State:          {data.get('terminal_state', 'N/A')}",
        f"Cert Job ID:             {data.get('certjob_id', 'N/A')}",
        f"Certificate ID:          {data.get('certificate_id', 'N/A')}",
        f"Certificate Version:     {data.get('certificate_version', 'N/A')}",
        f"Report ID:               {data.get('report_id', 'N/A')}",
        f"S3 Cert Ref:             {data.get('s3_certificate_ref', 'N/A')}",
        f"S3 Report Artifact Ref:  {data.get('s3_report_artifact_ref', 'N/A')}",
        f"Aggregate Set Hash:      {data.get('aggregate_set_hash', 'N/A')}",
        f"Created At:              {data.get('created_at', 'N/A')}",
        f"Completed At:            {data.get('completed_at', 'N/A')}",
    ]
    return "\n".join(lines)


def _handle_cert_domains(args: Any, svc: CertificationRetrievalService) -> str:
    """Render cert-domains: full domain_results[] from S3 artifact."""
    data = svc.get_cert_domains(*_svc_args(args))
    envelope = _provenance_envelope(
        certificate_id=data.get("certificate_id"),
        certificate_version=data.get("certificate_version"),
        terminal_state=data.get("terminal_state"),
        report_id=data.get("report_id"),
        generated_at=data.get("generated_at"),
    )
    domain_results = data.get("domain_results", [])
    lines = [envelope, ""]
    if not domain_results:
        lines.append("No domain results found.")
    else:
        for dr in domain_results:
            domain = dr.get("domain", "UNKNOWN") if isinstance(dr, dict) else getattr(dr, "domain", "UNKNOWN")
            status = dr.get("status", "N/A") if isinstance(dr, dict) else getattr(dr, "status", "N/A")
            checks_performed = dr.get("checks_performed", 0) if isinstance(dr, dict) else getattr(dr, "checks_performed", 0)
            checks_passed = dr.get("checks_passed", 0) if isinstance(dr, dict) else getattr(dr, "checks_passed", 0)
            failure_details = dr.get("failure_details", []) if isinstance(dr, dict) else getattr(dr, "failure_details", [])
            lines.append(f"Domain: {domain}")
            lines.append(f"  Status:            {status}")
            lines.append(f"  Checks Performed:  {checks_performed}")
            lines.append(f"  Checks Passed:     {checks_passed}")
            if failure_details:
                lines.append("  Failure Details:")
                for detail in failure_details:
                    lines.append(f"    - {detail}")
            else:
                lines.append("  Failure Details:   (none)")
            lines.append("")
    return "\n".join(lines)


def _handle_cert_json(args: Any, svc: CertificationRetrievalService) -> str:
    """Return the full certificate artifact as pretty-printed JSON (no envelope)."""
    artifact = svc.get_cert_json(*_svc_args(args))
    return json.dumps(artifact, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Dispatch table and main dispatch
# ---------------------------------------------------------------------------

_DISPATCH_TABLE: dict[str, Any] = {
    "cert-status": _handle_cert_status,
    "cert-summary": _handle_cert_summary,
    "cert-domains": _handle_cert_domains,
    "cert-json": _handle_cert_json,
}


def dispatch_cert_retrieve(args: Any, svc: CertificationRetrievalService) -> str:
    """Route retrieve cert-* args to the appropriate handler.

    Validates client_id, audit_id, and execution at the CLI boundary before
    any DynamoDB or S3 call.

    Args:
        args: Parsed argparse namespace with retrieve_command and shared cert args.
        svc: CertificationRetrievalService instance (or duck-typed equivalent).

    Returns:
        Rendered string output suitable for direct printing.

    Raises:
        ValidationError: If identifiers are invalid, command is unknown, or
            CertificationMetadata is not found (CERTIFICATION_NOT_FOUND).
        StorageError: On S3 read failure.
    """
    from release_confidence_platform.core.validators import validate_identifier  # noqa: PLC0415

    validate_identifier("client_id", args.client_id)
    validate_identifier("audit_id", args.audit_id)
    validate_identifier("execution", args.execution)

    command = getattr(args, "retrieve_command", "") or ""
    handler = _DISPATCH_TABLE.get(command)
    if handler is None:
        raise ValidationError(f"Unknown cert retrieve command: {command!r}", "UNKNOWN_COMMAND")
    return handler(args, svc)
