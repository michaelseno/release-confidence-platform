"""Phase 7 Certification Engine.

Orchestrates the full 15-step platform integrity certification pipeline:
  log invocation → prerequisite gate → idempotency gate → write PENDING →
  IN_PROGRESS → S3 artifact read → domain checks → terminal state →
  disclosed failures → build certificate → S3 write → metadata write →
  COMPLETE → log terminal state

Owns all status lifecycle transitions for CertificationJob records.
Catches pipeline failures after PENDING is written and updates the job to FAILED
before re-raising.

Phase 6 non-mutation is unconditional: the engine reads Phase 6 ReportMetadata
via the repository's read-only gate method and never writes to Phase 6 SK namespaces.
All engine writes target only #CERTJOB# and #CERT# SK patterns.

Pipeline steps (per technical design Section 7):
  1.  Log invocation (CERT_INVOKED)
  2.  Read ReportMetadata — abort with CertificationGateError if absent or status != COMPLETE
  3.  Check CertificationMetadata for prior CERTIFIED record
  4.  Generate certjob_id
  5.  Write CertificationJob PENDING
  6.  Update CertificationJob IN_PROGRESS
  7.  Read Phase 6 S3 report artifact and construct ReleaseConfidenceReport
  8.  Execute all 8 domain checks
  9.  Determine terminal_state from domain results
  10. Populate disclosed_failures
  11. Generate certificate_id; construct PlatformIntegrityCertificate
  12. Build S3 key via build_cert_s3_key()
  13. Write certificate to S3 via publisher
  14. Write CertificationMetadata record
  15. Update CertificationJob COMPLETE; log terminal state

On unrecoverable exception after step 5: update CertificationJob FAILED, re-raise.
"""

from __future__ import annotations

from typing import Any

from release_confidence_platform.audit_platform_integrity import events as evt
from release_confidence_platform.audit_platform_integrity.constants import (
    CERT_DOMAIN_IDENTIFIERS,
    CERTIFICATION_SUMMARY_MAP,
)
from release_confidence_platform.audit_platform_integrity.domains import (
    check_evidence_completeness,
    check_evidence_integrity,
    check_evidence_lineage,
    check_methodology_compliance,
    check_observation_coverage,
    check_report_integrity,
    check_runner_health,
    check_scheduler_integrity,
)
from release_confidence_platform.audit_platform_integrity.identity import (
    build_cert_s3_key,
    generate_certificate_id,
    generate_certjob_id,
)
from release_confidence_platform.audit_platform_integrity.models import (
    CertificationAuditProvenance,
    CertificationDomainResult,
    CertificationIdentity,
    CertificationResult,
    CertificationReportReference,
    PlatformIntegrityCertificate,
)
from release_confidence_platform.core.constants.engine import LOG_CATEGORY_INTERNAL
from release_confidence_platform.core.exceptions import ValidationError
from release_confidence_platform.core.logging import StructuredLogger
from release_confidence_platform.core.time import utc_now_iso
from release_confidence_platform.deterministic_reporting.models import ReleaseConfidenceReport


# ---------------------------------------------------------------------------
# Exception classes
# ---------------------------------------------------------------------------


class CertificationGateError(ValidationError):
    """Raised when ReportMetadata.status != COMPLETE.

    No CertificationJob is created when this error is raised. The prerequisite
    gate is unconditional per FR-1 in the technical design.
    """

    def __init__(
        self,
        message: str = "ReportMetadata prerequisite not satisfied",
        error_type: str = "REPORT_NOT_COMPLETE",
    ) -> None:
        super().__init__(message, error_type)


class CertificationAlreadyCertifiedError(ValidationError):
    """Raised when terminal_state=CERTIFIED exists and --force is not supplied.

    No new CertificationJob is created when this error is raised. Callers should
    use the existing certificate_id and s3_certificate_ref from the error context.
    """

    def __init__(
        self,
        message: str = "Audit already certified",
        error_type: str = "CERTIFICATION_ALREADY_CERTIFIED",
    ) -> None:
        super().__init__(message, error_type)


class CertificationInProgressError(ValidationError):
    """Raised when a CertificationJob is already IN_PROGRESS (concurrency guard).

    Reserved for future concurrency protection. Not raised in the current pipeline.
    """

    def __init__(
        self,
        message: str = "Certification already in progress",
        error_type: str = "CERTIFICATION_IN_PROGRESS",
    ) -> None:
        super().__init__(message, error_type)


# ---------------------------------------------------------------------------
# Terminal state determination (pure function — no side effects)
# ---------------------------------------------------------------------------


def _determine_terminal_state(domain_results: list[Any]) -> str:
    """Determine the certification terminal state from domain results.

    Priority: CERTIFICATION_BLOCKED > CERTIFICATION_FAILED > CERTIFIED

    Args:
        domain_results: List of CertificationDomainResult objects.

    Returns:
        One of: 'CERTIFICATION_BLOCKED', 'CERTIFICATION_FAILED', 'CERTIFIED'
    """
    statuses = {r.status for r in domain_results}
    if "BLOCKED" in statuses:
        return "CERTIFICATION_BLOCKED"
    if "FAILED" in statuses:
        return "CERTIFICATION_FAILED"
    return "CERTIFIED"


# ---------------------------------------------------------------------------
# Certification Engine
# ---------------------------------------------------------------------------


class CertificationEngine:
    """Orchestrates the Phase 7 platform integrity certification pipeline."""

    def __init__(
        self,
        repository: Any,
        publisher: Any,
        logger: Any = None,
        platform_version: str = "unknown",
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.logger = logger or StructuredLogger()
        self.platform_version = platform_version

    def certify(
        self,
        client_id: str,
        audit_id: str,
        audit_execution_id: str,
        config_version: str,
        aggregation_version: str,
        intelligence_version: str,
        report_version: str,
        cert_version: str,
        force: bool = False,
    ) -> PlatformIntegrityCertificate:
        """Run the full Phase 7 certification pipeline.

        Args:
            client_id: Validated client identifier.
            audit_id: Validated audit identifier.
            audit_execution_id: Durable execution identity.
            config_version: Configuration version.
            aggregation_version: Phase 4 aggregation version.
            intelligence_version: Phase 5 intelligence version.
            report_version: Phase 6 report version.
            cert_version: Certificate schema version (cert_v1).
            force: Re-certify even if a CERTIFIED record already exists.

        Returns:
            PlatformIntegrityCertificate for the certification event.

        Raises:
            CertificationGateError: When ReportMetadata prerequisite is not satisfied.
            CertificationAlreadyCertifiedError: When prior CERTIFIED record exists without force.
            StorageError: On DynamoDB or S3 failure.
        """
        invoked_at = utc_now_iso()

        # ------------------------------------------------------------------
        # Step 1: Log invocation
        # ------------------------------------------------------------------
        self.logger.log(
            evt.CERT_INVOKED,
            event_type=evt.CERT_INVOKED,
            log_category=LOG_CATEGORY_INTERNAL,
            level="INFO",
            service="CertificationEngine",
            client_id=client_id,
            audit_id=audit_id,
            audit_execution_id=audit_execution_id,
            aggregation_version=aggregation_version,
            intelligence_version=intelligence_version,
            report_version=report_version,
            cert_version=cert_version,
            force=force,
        )

        # ------------------------------------------------------------------
        # Step 2: Read ReportMetadata — prerequisite gate
        # No CertificationJob is created if this gate fails.
        # ------------------------------------------------------------------
        report_metadata = self.repository.get_report_metadata(
            client_id,
            audit_id,
            audit_execution_id,
            config_version,
            aggregation_version,
            intelligence_version,
            report_version,
        )

        if report_metadata is None or report_metadata.get("status") != "COMPLETE":
            gate_reason = (
                "ReportMetadata not found"
                if report_metadata is None
                else f"status={report_metadata.get('status')!r} != COMPLETE"
            )
            self.logger.log(
                evt.CERT_GATE_BLOCKED,
                event_type=evt.CERT_GATE_BLOCKED,
                log_category=LOG_CATEGORY_INTERNAL,
                level="WARNING",
                service="CertificationEngine",
                client_id=client_id,
                audit_id=audit_id,
                gate_reason=gate_reason,
            )
            raise CertificationGateError(
                f"Certification prerequisite not satisfied: {gate_reason}"
            )

        # ------------------------------------------------------------------
        # Step 3: Check CertificationMetadata for prior CERTIFIED record
        # ------------------------------------------------------------------
        existing_cert = self.repository.get_cert_metadata(
            client_id,
            audit_id,
            audit_execution_id,
            config_version,
            aggregation_version,
            intelligence_version,
            report_version,
            cert_version,
        )

        if existing_cert and existing_cert.get("terminal_state") == "CERTIFIED" and not force:
            self.logger.log(
                evt.CERT_ALREADY_CERTIFIED,
                event_type=evt.CERT_ALREADY_CERTIFIED,
                log_category=LOG_CATEGORY_INTERNAL,
                level="INFO",
                service="CertificationEngine",
                client_id=client_id,
                audit_id=audit_id,
                certificate_id=existing_cert.get("certificate_id"),
            )
            raise CertificationAlreadyCertifiedError(
                f"Audit already certified: certificate_id={existing_cert.get('certificate_id')!r}, "
                f"s3_certificate_ref={existing_cert.get('s3_certificate_ref')!r}. "
                "Use --force to re-certify."
            )

        # ------------------------------------------------------------------
        # Step 4: Generate certjob_id
        # ------------------------------------------------------------------
        certjob_id = generate_certjob_id()

        # ------------------------------------------------------------------
        # Step 5: Write CertificationJob PENDING
        # ------------------------------------------------------------------
        identity_tuple: dict[str, Any] = {
            "audit_execution_id": audit_execution_id,
            "config_version": config_version,
            "aggregation_version": aggregation_version,
            "intelligence_version": intelligence_version,
            "report_version": report_version,
            "cert_version": cert_version,
        }
        self.repository.write_certjob_pending(
            client_id, audit_id, certjob_id, identity_tuple
        )

        self.logger.log(
            evt.CERT_PENDING,
            event_type=evt.CERT_PENDING,
            log_category=LOG_CATEGORY_INTERNAL,
            level="INFO",
            service="CertificationEngine",
            client_id=client_id,
            audit_id=audit_id,
            certjob_id=certjob_id,
        )

        # ------------------------------------------------------------------
        # Steps 6-14: Pipeline execution (failure-safe after PENDING is written)
        # On any unrecoverable failure: update CertificationJob to FAILED and re-raise.
        # ------------------------------------------------------------------
        failure_stage: str = "unknown"
        artifact_exc: Exception | None = None
        try:
            # Step 6: Update CertificationJob to IN_PROGRESS
            failure_stage = "certjob_in_progress_update"
            self.repository.update_certjob_in_progress(client_id, audit_id, certjob_id)

            self.logger.log(
                evt.CERT_IN_PROGRESS,
                event_type=evt.CERT_IN_PROGRESS,
                log_category=LOG_CATEGORY_INTERNAL,
                level="INFO",
                service="CertificationEngine",
                client_id=client_id,
                audit_id=audit_id,
                certjob_id=certjob_id,
            )

            # Steps 7+8: Read Phase 6 S3 report artifact and execute domain checks.
            # TN-12: If the artifact read or parse fails, all 8 domains are set to
            # BLOCKED and the pipeline continues to produce a CERTIFICATION_BLOCKED
            # certificate. The CertificationJob transitions to FAILED at step 15.
            try:
                # Step 7: Read Phase 6 S3 report artifact; construct ReleaseConfidenceReport
                failure_stage = "reading_phase6_artifact"
                artifact_dict = self.repository.read_report_artifact(
                    report_metadata["s3_artifact_ref"]
                )
                report = ReleaseConfidenceReport.model_validate(artifact_dict)

                # Step 8: Execute all 8 domain checks
                failure_stage = "executing_domain_checks"
                domain_results = [
                    check_runner_health(report),
                    check_evidence_completeness(report),
                    check_evidence_integrity(report, report_metadata),
                    check_evidence_lineage(report, report_metadata),
                    check_observation_coverage(report, report_metadata),
                    check_scheduler_integrity(report),
                    check_methodology_compliance(report),
                    check_report_integrity(report),
                ]

                # Assert exactly 8 domain results with correct identifiers
                assert len(domain_results) == len(CERT_DOMAIN_IDENTIFIERS), (
                    f"Expected {len(CERT_DOMAIN_IDENTIFIERS)} domain results, "
                    f"got {len(domain_results)}"
                )

            except Exception as exc:
                # TN-12: S3 artifact read or Pydantic parse failure → all domains BLOCKED.
                # The pipeline continues and produces a CERTIFICATION_BLOCKED certificate.
                # CertificationJob transitions to FAILED at step 15 with failure context.
                artifact_exc = exc
                domain_results = [
                    CertificationDomainResult(
                        domain=d,
                        status="BLOCKED",
                        checks_performed=0,
                        checks_passed=0,
                        failure_details=[
                            f"Phase 6 S3 artifact read failure: "
                            f"{type(exc).__name__}: {exc}"
                        ],
                        evidence_refs=[],
                    )
                    for d in CERT_DOMAIN_IDENTIFIERS
                ]

            # Step 9: Determine terminal_state from domain results
            failure_stage = "determining_terminal_state"
            terminal_state = _determine_terminal_state(domain_results)

            # Step 10: Populate disclosed_failures
            failure_stage = "populating_disclosed_failures"
            disclosed_failures = [
                r.domain for r in domain_results
                if r.status in ("FAILED", "BLOCKED")
            ]

            # Step 11: Generate certificate_id; construct PlatformIntegrityCertificate
            failure_stage = "building_certificate"
            certificate_id = generate_certificate_id()
            generated_at = utc_now_iso()

            certificate = PlatformIntegrityCertificate(
                identity=CertificationIdentity(
                    certificate_id=certificate_id,
                    certificate_version=cert_version,
                    generated_at=generated_at,
                    generator_version=self.platform_version,
                ),
                result=CertificationResult(
                    terminal_state=terminal_state,
                    certification_summary=CERTIFICATION_SUMMARY_MAP[terminal_state],
                    disclosed_failures=disclosed_failures,
                ),
                report_reference=CertificationReportReference(
                    report_id=report_metadata.get("report_id", ""),
                    report_version=report_metadata.get("report_version", ""),
                    s3_report_artifact_ref=report_metadata["s3_artifact_ref"],
                    intelligence_version=report_metadata.get("intelligence_version", ""),
                    aggregate_set_hash=report_metadata.get("aggregate_set_hash", ""),
                ),
                audit_provenance=CertificationAuditProvenance(
                    client_id=client_id,
                    audit_id=audit_id,
                    audit_execution_id=audit_execution_id,
                    config_version=config_version,
                    aggregation_version=aggregation_version,
                    intelligence_version=intelligence_version,
                    report_version=report_version,
                ),
                domain_results=domain_results,
                certjob_id=certjob_id,
            )

            # Step 12: Build S3 key via build_cert_s3_key()
            failure_stage = "computing_s3_key"
            s3_key = build_cert_s3_key(
                client_id=client_id,
                audit_id=audit_id,
                audit_execution_id=audit_execution_id,
                config_version=config_version,
                aggregation_version=aggregation_version,
                intelligence_version=intelligence_version,
                report_version=report_version,
                cert_version=cert_version,
                certjob_id=certjob_id,
            )

            # Step 13: Write certificate artifact to S3
            failure_stage = "writing_s3_artifact"
            self.publisher.write_artifact(s3_key, certificate.to_dict())

            # Step 14: Write CertificationMetadata record
            failure_stage = "writing_cert_metadata"
            self.repository.write_cert_metadata_complete(
                client_id=client_id,
                audit_id=audit_id,
                audit_execution_id=audit_execution_id,
                config_version=config_version,
                aggregation_version=aggregation_version,
                intelligence_version=intelligence_version,
                report_version=report_version,
                cert_version=cert_version,
                terminal_state=terminal_state,
                certificate_id=certificate_id,
                certjob_id=certjob_id,
                s3_cert_ref=s3_key,
                s3_report_artifact_ref=report_metadata["s3_artifact_ref"],
                aggregate_set_hash=report_metadata.get("aggregate_set_hash", ""),
                report_id=report_metadata.get("report_id", ""),
                certification_summary=CERTIFICATION_SUMMARY_MAP[terminal_state],
                disclosed_failures=disclosed_failures,
            )

        except Exception as exc:
            # Failure path: update CertificationJob to FAILED before re-raising.
            failure_reason = getattr(exc, "error_type", type(exc).__name__)
            try:
                self.repository.update_certjob_failed(
                    client_id, audit_id, certjob_id,
                    f"stage={failure_stage}; reason={failure_reason}",
                )
            except Exception:
                pass  # Do not mask the original exception.

            self.logger.log(
                evt.CERT_FAILED,
                event_type=evt.CERT_FAILED,
                log_category=LOG_CATEGORY_INTERNAL,
                level="ERROR",
                service="CertificationEngine",
                client_id=client_id,
                audit_id=audit_id,
                certjob_id=certjob_id,
                failure_stage=failure_stage,
                failure_reason=failure_reason,
            )
            raise

        # ------------------------------------------------------------------
        # Step 15: Update CertificationJob final status; log terminal state.
        # TN-12: When the Phase 6 artifact read failed (artifact_exc is set), the
        # certificate and metadata have been written but CertificationJob transitions
        # to FAILED with failure context, per the TN-12 trust requirement.
        # For all other terminal states (CERTIFIED, CERTIFICATION_FAILED), the job
        # transitions to COMPLETE.
        # ------------------------------------------------------------------
        if artifact_exc is not None:
            failure_reason_tn12 = type(artifact_exc).__name__
            try:
                self.repository.update_certjob_failed(
                    client_id,
                    audit_id,
                    certjob_id,
                    f"stage=reading_phase6_artifact; reason={failure_reason_tn12}",
                )
            except Exception:
                pass  # Certificate and metadata already written; FAILED update is best-effort.
        else:
            try:
                self.repository.update_certjob_complete(
                    client_id, audit_id, certjob_id, terminal_state, s3_key
                )
            except Exception:
                pass  # Certificate and metadata already written; COMPLETE update is best-effort.

        log_event = (
            evt.CERT_COMPLETE
            if terminal_state == "CERTIFIED"
            else evt.CERT_FAILED
        )
        self.logger.log(
            log_event,
            event_type=log_event,
            log_category=LOG_CATEGORY_INTERNAL,
            level="INFO",
            service="CertificationEngine",
            client_id=client_id,
            audit_id=audit_id,
            certjob_id=certjob_id,
            certificate_id=certificate_id,
            terminal_state=terminal_state,
            certification_summary=CERTIFICATION_SUMMARY_MAP[terminal_state],
            s3_certificate_ref=s3_key,
            domain_statuses={r.domain: r.status for r in domain_results},
            disclosed_failures=disclosed_failures,
        )

        return certificate
