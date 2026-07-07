"""CLI command definitions for Phase 7.6 Certification Execution CLI.

Provides parser registration and dispatch for the `rcp certify audit` subcommand.
Business logic lives in CertificationEngine.

Validation: validate_identifier is called on client_id, audit_id, and execution
before the engine is invoked. This is a pre-condition enforced at the CLI boundary.
"""

from __future__ import annotations

import argparse
from typing import Any


def build_certify_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the `certify audit` subparser on the provided subparsers action."""
    p = sub.add_parser(
        "audit",
        help="Run platform integrity certification for a completed report",
    )
    p.add_argument("--client-id", required=True, dest="client_id")
    p.add_argument("--audit-id", required=True, dest="audit_id")
    p.add_argument("--execution", required=True, help="Audit execution identity (audit_execution_id)")
    p.add_argument("--stage", required=True, choices=("dev", "staging", "prod"))
    p.add_argument(
        "--config-version",
        default="v1",
        dest="config_version",
        help="Configuration version (default: v1)",
    )
    p.add_argument(
        "--aggregation-version",
        default="agg_v1",
        dest="aggregation_version",
        help="Aggregation version (default: agg_v1)",
    )
    p.add_argument(
        "--intelligence-version",
        default="intel_v1",
        dest="intelligence_version",
        help="Intelligence version (default: intel_v1)",
    )
    p.add_argument(
        "--report-version",
        default="report_v1",
        dest="report_version",
        help="Report version (default: report_v1)",
    )
    p.add_argument(
        "--cert-version",
        default="cert_v1",
        dest="cert_version",
        help="Certificate schema version (default: cert_v1)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-certify even if a CERTIFIED record already exists",
    )
    p.add_argument(
        "--output",
        choices=("json", "human"),
        default="human",
        help="Output format (default: human)",
    )


def dispatch_certify_audit(args: argparse.Namespace, engine: Any) -> dict[str, Any]:
    """Dispatch `certify audit` arguments to CertificationEngine.certify().

    Validates identifiers at the CLI boundary, invokes the engine, and returns
    a summary dict with the key certification result fields.

    Args:
        args: Parsed argparse namespace from build_certify_parser.
        engine: A CertificationEngine instance (or duck-typed equivalent).

    Returns:
        Dict with keys: certificate_id, terminal_state, s3_cert_ref,
        disclosed_failures, domain_results, status.

    Raises:
        ValidationError: If any of client_id, audit_id, or execution fail
            identifier validation.
        CertificationGateError: If ReportMetadata.status != COMPLETE.
        CertificationAlreadyCertifiedError: If already CERTIFIED and --force
            was not passed.
        StorageError: On DynamoDB or S3 infrastructure failure.
    """
    from release_confidence_platform.core.validators import validate_identifier  # noqa: PLC0415
    from release_confidence_platform.audit_platform_integrity.identity import (  # noqa: PLC0415
        build_cert_s3_key,
    )

    validate_identifier("client_id", args.client_id)
    validate_identifier("audit_id", args.audit_id)
    validate_identifier("execution", args.execution)

    certificate = engine.certify(
        client_id=args.client_id,
        audit_id=args.audit_id,
        audit_execution_id=args.execution,
        config_version=args.config_version,
        aggregation_version=args.aggregation_version,
        intelligence_version=args.intelligence_version,
        report_version=args.report_version,
        cert_version=args.cert_version,
        force=getattr(args, "force", False),
    )

    # Reconstruct the S3 key; the engine writes it but does not return it directly.
    # certificate.certjob_id is set during the pipeline and carried in the artifact.
    s3_cert_ref = build_cert_s3_key(
        client_id=args.client_id,
        audit_id=args.audit_id,
        audit_execution_id=args.execution,
        config_version=args.config_version,
        aggregation_version=args.aggregation_version,
        intelligence_version=args.intelligence_version,
        report_version=args.report_version,
        cert_version=args.cert_version,
        certjob_id=certificate.certjob_id,
    )

    return {
        "certificate_id": certificate.identity.certificate_id,
        "terminal_state": certificate.result.terminal_state,
        "s3_cert_ref": s3_cert_ref,
        "disclosed_failures": certificate.result.disclosed_failures,
        "status": certificate.result.terminal_state,
        "domain_results": [
            {
                "domain": dr.domain,
                "status": dr.status,
                "checks_performed": dr.checks_performed,
                "checks_passed": dr.checks_passed,
                "failure_details": dr.failure_details,
            }
            for dr in certificate.domain_results
        ],
        "audit_id": args.audit_id,
        "client_id": args.client_id,
    }
