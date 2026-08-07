"""DynamoDB and S3 repository for Phase 7 Audit Platform Integrity.

Two responsibilities:
  (a) Phase 6 consumer reads — read-only access to ReportMetadata (DynamoDB) and
      the Phase 6 S3 report artifact. Never writes to Phase 6 SK namespaces.
  (b) Phase 7 writes — targets exclusively Phase 7 SK namespaces (#CERTJOB# and #CERT#).

Sort key write prohibition: every write method calls _assert_phase7_sk() before
the DynamoDB call. This is a programming-error guard covering the same invariant
tested by test_engine_no_phase6_mutation.py.

SK write guard design note:
  The CertificationMetadata SK contains #AGG#, #INTEL#, and #RPT# as structural
  scope qualifiers (e.g., ...#AGG#{agg_v}#INTEL#{intel_v}#RPT#{rpt_v}#CERT#{cert_v}#META).
  These qualifiers cannot be included in the prohibited marker list without
  incorrectly rejecting valid Phase 7 CertificationMetadata writes. Only markers
  that are EXCLUSIVELY non-Phase-7 record types are prohibited:
    #RPTJOB# — exclusively Phase 6 ReportJob records
    #INTJOB# — exclusively Phase 5 IntelligenceJob records
  The primary protection is the requirement that every write SK must contain
  #CERTJOB# (CertificationJob) or #CERT# (CertificationMetadata).

Evidence Governance Workstream A1.3d.4 (Technical Design Section 20.8;
ADR Decision 11, Non-Negotiable Invariant 31): write_cert_metadata_complete
becomes a hold-coordinated TransactWriteItems call that preserves the
existing unconditional-replacement (Put with no ConditionExpression)
semantics -- structurally identical in shape to the already-merged Phase
5/6 governed writes (reliability_intelligence/repository.py,
deterministic_reporting/repository.py), but with no item-level condition
of its own, since forced recertification must always be able to replace an
existing CertificationMetadata record. CertificationJob remains Category 3
-- never receives custody fields, hold coordination, or evidence-class tags.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.core.time import utc_now_iso
from release_confidence_platform.evidence_retention.hold_coordination import (
    HoldCoordinatedTransactionRunner,
    build_hold_version_condition_check_item,
    compute_ttl_disposal_at,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from release_confidence_platform.storage.dynamodb_codec import (
    decode_dynamodb_response,
    encode_dynamodb_call_kwargs,
    encode_item,
    storage_error_from_dynamodb_client_error,
    storage_error_from_dynamodb_request_error,
)

# Phase 7-exclusive SK segment markers. Any write targeting these patterns is permitted.
_PHASE7_SK_MARKERS = ("#CERTJOB#", "#CERT#")

# Exclusively non-Phase-7 record type markers that must never appear in Phase 7 write paths.
# Note: #RPT#, #INTEL#, #AGG# are structural qualifiers shared with Phase 7 SKs and
# are NOT listed here. See module docstring for full rationale.
_PROHIBITED_SK_MARKERS = ("#RPTJOB#", "#INTJOB#")


def _assert_phase7_sk(sk: str) -> None:
    """Assert that an SK is in Phase 7 namespace before any write.

    Raises AssertionError if the SK does not contain a Phase 7 marker, or if it
    contains any exclusively non-Phase-7 record type marker. This is a
    programming-error guard, not a user-facing validation.
    """
    has_phase7_marker = any(marker in sk for marker in _PHASE7_SK_MARKERS)
    has_prohibited = any(marker in sk for marker in _PROHIBITED_SK_MARKERS)
    if not has_phase7_marker or has_prohibited:
        raise AssertionError(
            f"Phase 7 write attempted to prohibited SK namespace: {sk!r}. "
            "Phase 7 writes must target only #CERTJOB# or #CERT# SK patterns."
        )


class ConditionalWriteError(StorageError):
    def __init__(self, message: str = "Conditional write failed"):
        super().__init__(message, "CONDITIONAL_WRITE_FAILED")


def _cert_governance_fields(
    hold_state: dict[str, Any] | None, custody_period_days: int
) -> dict[str, int | str]:
    """Compute custody_expires_at/ttl_disposal_at/evidence_class for a Phase 7
    governed CertificationMetadata write (Technical Design Section 20.8.1).

    Mirrors reliability_intelligence/repository.py::_intelligence_governance_fields
    and deterministic_reporting/repository.py::_report_governance_fields exactly,
    with evidence_class fixed to "certificate". custody_expires_at is always
    freshly computed; ttl_disposal_at is omitted if and only if this attempt's
    own hold_state read observed an ACTIVE hold.
    """
    now_epoch_seconds = int(datetime.now(UTC).timestamp())
    custody_expires_at = now_epoch_seconds + custody_period_days * 86400
    fields: dict[str, int | str] = {
        "custody_expires_at": custody_expires_at,
        "evidence_class": "certificate",
    }
    ttl_disposal_at = compute_ttl_disposal_at(hold_state, custody_expires_at)
    if ttl_disposal_at is not None:
        fields["ttl_disposal_at"] = ttl_disposal_at
    return fields


class CertificationRepository:
    """Phase 6 consumer reads and Phase 7 certification writes for Audit Platform Integrity."""

    def __init__(
        self,
        table_name: str,
        dynamodb_client: Any,
        s3_client: Any,
        bucket_name: str,
        hold_repository: HoldRepository | None = None,
        *,
        custody_period_days: int | None = None,
    ) -> None:
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client
        self.s3_client = s3_client
        self.bucket_name = bucket_name
        self._hold_repository = hold_repository
        self._custody_period_days = custody_period_days

    def _governance_preflight(self) -> None:
        """Write-entry governance preflight (ADR Invariant 31; Technical
        Design Section 20.4). Mandatory first action of every governed
        write method, before any hold-state read, transaction-item
        construction, or AWS mutation. Order is load-bearing: hold
        coordination presence, then custody-duration presence, then
        custody-duration validity (Boolean rejected before the int check,
        since bool is an int subclass).
        """
        if self._hold_repository is None:
            raise StorageError(
                "Hold coordination is not configured", "HOLD_COORDINATION_NOT_CONFIGURED"
            )
        if self._custody_period_days is None:
            raise StorageError(
                "Custody period configuration was not provided to this repository instance",
                "CUSTODY_PERIOD_CONFIG_MISSING",
            )
        if (
            isinstance(self._custody_period_days, bool)
            or not isinstance(self._custody_period_days, int)
            or self._custody_period_days <= 0
        ):
            raise StorageError(
                "Custody period configuration is invalid", "CUSTODY_PERIOD_CONFIG_MISSING"
            )

    # ------------------------------------------------------------------
    # Phase 6 read-only gate (never writes to Phase 6 records)
    # ------------------------------------------------------------------

    def get_report_metadata(
        self,
        client_id: str,
        audit_id: str,
        audit_execution_id: str,
        config_version: str,
        aggregation_version: str,
        intelligence_version: str,
        report_version: str,
    ) -> dict[str, Any] | None:
        """Read the Phase 6 ReportMetadata record for the prerequisite gate.

        Returns the record dict if found, or None if absent.
        Phase 7 reads this record but never writes to it.
        """
        key = {
            "PK": f"CLIENT#{client_id}",
            "SK": (
                f"AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}"
                f"#AGG#{aggregation_version}#INTEL#{intelligence_version}"
                f"#RPT#{report_version}#META"
            ),
        }
        return self._get_item(key)

    def read_report_artifact(self, s3_artifact_ref: str) -> dict[str, Any]:
        """Read and deserialize the Phase 6 S3 report artifact.

        Args:
            s3_artifact_ref: S3 object key from ReportMetadata.s3_artifact_ref.
                Phase 7 must use this key directly and never construct it independently.

        Returns:
            Parsed artifact dict.

        Raises:
            StorageError: On any S3 GetObject failure or JSON parse failure.
        """
        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket_name, Key=s3_artifact_ref
            )
            return json.loads(response["Body"].read().decode("utf-8"))
        except Exception as exc:
            raise StorageError(
                f"Failed to read Phase 6 report S3 artifact: {exc}",
                "S3_REPORT_ARTIFACT_READ_FAILURE",
            ) from exc

    # ------------------------------------------------------------------
    # Phase 7 idempotency read — CertificationMetadata
    # ------------------------------------------------------------------

    def get_cert_metadata(
        self,
        client_id: str,
        audit_id: str,
        audit_execution_id: str,
        config_version: str,
        aggregation_version: str,
        intelligence_version: str,
        report_version: str,
        cert_version: str,
    ) -> dict[str, Any] | None:
        """Read the Phase 7 CertificationMetadata record for the idempotency gate.

        Returns the record dict if found, or None if this is a first-time certification.
        """
        key = {
            "PK": f"CLIENT#{client_id}",
            "SK": (
                f"AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}"
                f"#AGG#{aggregation_version}#INTEL#{intelligence_version}"
                f"#RPT#{report_version}#CERT#{cert_version}#META"
            ),
        }
        return self._get_item(key)

    # ------------------------------------------------------------------
    # Phase 7 writes — CertificationJob lifecycle
    # ------------------------------------------------------------------

    def write_certjob_pending(
        self,
        client_id: str,
        audit_id: str,
        certjob_id: str,
        identity_tuple: dict[str, Any],
    ) -> None:
        """Write a new CertificationJob record in PENDING status.

        Uses conditional write to prevent duplicate job records.

        Args:
            client_id: Scoped client identifier.
            audit_id: Scoped audit identifier.
            certjob_id: Unique job identifier.
            identity_tuple: Dict with audit_execution_id, config_version,
                aggregation_version, intelligence_version, report_version, cert_version.

        Raises:
            AssertionError: If computed SK is not a Phase 7 SK.
            ConditionalWriteError: If the record already exists.
            StorageError: On DynamoDB failure.
        """
        sk = f"AUDIT#{audit_id}#CERTJOB#{certjob_id}"
        _assert_phase7_sk(sk)
        now = utc_now_iso()
        item = {
            "PK": f"CLIENT#{client_id}",
            "SK": sk,
            "certjob_id": certjob_id,
            "client_id": client_id,
            "audit_id": audit_id,
            "audit_execution_id": identity_tuple["audit_execution_id"],
            "config_version": identity_tuple["config_version"],
            "aggregation_version": identity_tuple["aggregation_version"],
            "intelligence_version": identity_tuple["intelligence_version"],
            "report_version": identity_tuple["report_version"],
            "cert_version": identity_tuple["cert_version"],
            "status": "PENDING",
            "failure_stage": None,
            "failure_reason": None,
            "certificate_id": None,
            "s3_certificate_ref": None,
            "created_at": now,
            "completed_at": None,
        }
        self._put_once(item)

    def update_certjob_in_progress(
        self,
        client_id: str,
        audit_id: str,
        certjob_id: str,
    ) -> None:
        """Update a CertificationJob to IN_PROGRESS status.

        Raises:
            AssertionError: If SK is not a Phase 7 SK.
            StorageError: On DynamoDB failure.
        """
        sk = f"AUDIT#{audit_id}#CERTJOB#{certjob_id}"
        _assert_phase7_sk(sk)
        key = {"PK": f"CLIENT#{client_id}", "SK": sk}
        self._update_item(key, {"status": "IN_PROGRESS", "updated_at": utc_now_iso()})

    def update_certjob_complete(
        self,
        client_id: str,
        audit_id: str,
        certjob_id: str,
        terminal_state: str,
        s3_ref: str,
    ) -> None:
        """Update a CertificationJob to COMPLETE status with terminal state and S3 reference.

        Raises:
            AssertionError: If SK is not a Phase 7 SK.
            StorageError: On DynamoDB failure.
        """
        sk = f"AUDIT#{audit_id}#CERTJOB#{certjob_id}"
        _assert_phase7_sk(sk)
        key = {"PK": f"CLIENT#{client_id}", "SK": sk}
        now = utc_now_iso()
        self._update_item(key, {
            "status": "COMPLETE",
            "terminal_state": terminal_state,
            "s3_certificate_ref": s3_ref,
            "completed_at": now,
            "updated_at": now,
        })

    def update_certjob_failed(
        self,
        client_id: str,
        audit_id: str,
        certjob_id: str,
        error: str,
    ) -> None:
        """Update a CertificationJob to FAILED status with an error description.

        Raises:
            AssertionError: If SK is not a Phase 7 SK.
            StorageError: On DynamoDB failure.
        """
        sk = f"AUDIT#{audit_id}#CERTJOB#{certjob_id}"
        _assert_phase7_sk(sk)
        key = {"PK": f"CLIENT#{client_id}", "SK": sk}
        now = utc_now_iso()
        self._update_item(key, {
            "status": "FAILED",
            "failure_reason": error,
            "completed_at": now,
            "updated_at": now,
        })

    # ------------------------------------------------------------------
    # Phase 7 writes — CertificationMetadata
    # ------------------------------------------------------------------

    def write_cert_metadata_complete(
        self,
        client_id: str,
        audit_id: str,
        audit_execution_id: str,
        config_version: str,
        aggregation_version: str,
        intelligence_version: str,
        report_version: str,
        cert_version: str,
        terminal_state: str,
        certificate_id: str,
        certjob_id: str,
        s3_cert_ref: str,
        s3_report_artifact_ref: str,
        aggregate_set_hash: str,
        report_id: str,
        certification_summary: str,
        disclosed_failures: list[str],
    ) -> None:
        """Write or update the authoritative CertificationMetadata record, as
        a hold-coordinated TransactWriteItems call (Technical Design Section
        20.8): the existing unconditional Put (no ConditionExpression of any
        kind -- forced recertification must always be able to replace an
        existing record) plus the appended LegalHold.hold_version
        ConditionCheck.

        PutItem overwrites any existing record for the same identity tuple.
        Force re-runs update terminal_state, certificate_id, certjob_id, and
        completed_at. created_at is always set to the current write timestamp
        in this implementation (MVP scope: see assumption in implementation plan).

        Every attempt (including a hold-version retry) computes fresh
        custody_expires_at/ttl_disposal_at/evidence_class from the injected
        duration, that attempt's own clock, and that attempt's own
        hold-state read -- on every call, first-certification, forced
        recertification, and the TN-12 BLOCKED path alike; this write
        contract does not distinguish between them.

        Raises:
            AssertionError: If computed SK is not a Phase 7 SK.
            StorageError: ``HOLD_COORDINATION_NOT_CONFIGURED`` if this
                instance has no HoldRepository; ``CUSTODY_PERIOD_CONFIG_MISSING``
                if no valid custody-period duration was injected -- both fail
                closed before any hold-state read, transact-item
                construction, or AWS request; ``HOLD_STATE_CONCURRENCY_EXCEEDED``
                on bounded hold-version retry exhaustion.
        """
        self._governance_preflight()
        sk = (
            f"AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}"
            f"#AGG#{aggregation_version}#INTEL#{intelligence_version}"
            f"#RPT#{report_version}#CERT#{cert_version}#META"
        )
        _assert_phase7_sk(sk)
        now = utc_now_iso()
        # Literal construction -- NEVER sanitize() a persistence-bound item.
        base_item: dict[str, Any] = {
            "PK": f"CLIENT#{client_id}",
            "SK": sk,
            "certificate_version": cert_version,
            "certificate_id": certificate_id,
            "certjob_id": certjob_id,
            "client_id": client_id,
            "audit_id": audit_id,
            "audit_execution_id": audit_execution_id,
            "config_version": config_version,
            "aggregation_version": aggregation_version,
            "intelligence_version": intelligence_version,
            "report_version": report_version,
            "cert_version": cert_version,
            "terminal_state": terminal_state,
            "certification_summary": certification_summary,
            "disclosed_failures": disclosed_failures,
            "report_id": report_id,
            "s3_certificate_ref": s3_cert_ref,
            "s3_report_artifact_ref": s3_report_artifact_ref,
            "aggregate_set_hash": aggregate_set_hash,
            "created_at": now,
            "completed_at": now,
        }
        hold_key = self._hold_repository.legal_hold_key(client_id, audit_id)

        def build_transact_items(
            hold_state: dict[str, Any] | None,
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            item_with_governance = {
                **base_item,
                **_cert_governance_fields(hold_state, self._custody_period_days),
            }
            # No ConditionExpression -- the unconditional-replacement contract
            # (Technical Design Section 20.8) is preserved exactly; forced
            # recertification must always be able to replace an existing record.
            put_transact_item = {
                "Put": {
                    "TableName": self.table_name,
                    "Item": encode_item(item_with_governance),
                }
            }
            hold_condition_item = build_hold_version_condition_check_item(
                self.table_name, hold_key, hold_state
            )
            return [put_transact_item], hold_condition_item

        runner = HoldCoordinatedTransactionRunner(self.dynamodb_client, self._hold_repository)
        runner.run(client_id, audit_id, build_transact_items)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_item(self, key: dict[str, str]) -> dict[str, Any] | None:
        response = self._call("get_item", Key=key)
        return response.get("Item")

    def _put_once(self, item: dict[str, Any]) -> None:
        try:
            self._call(
                "put_item",
                preserve_client_error_codes={"ConditionalCheckFailedException"},
                Item=item,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConditionalWriteError() from exc
            raise

    def _update_item(self, key: dict[str, str], updates: dict[str, Any]) -> None:
        names = {f"#f{i}": field_name for i, field_name in enumerate(updates)}
        values = {f":v{i}": value for i, value in enumerate(updates.values())}
        assignments = ", ".join(f"{name} = :v{i}" for i, name in enumerate(names))
        self._call(
            "update_item",
            Key=key,
            UpdateExpression="SET " + assignments,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def _call(
        self,
        method_name: str,
        *,
        preserve_client_error_codes: set[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        method = getattr(self.dynamodb_client, method_name)
        try:
            return decode_dynamodb_response(
                method(TableName=self.table_name, **encode_dynamodb_call_kwargs(kwargs))
            )
        except TypeError:
            return decode_dynamodb_response(method(**kwargs))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in (
                preserve_client_error_codes or set()
            ):
                raise
            raise storage_error_from_dynamodb_client_error(
                exc, operation=method_name
            ) from exc
        except Exception as exc:
            raise storage_error_from_dynamodb_request_error(
                exc, operation=method_name
            ) from exc
