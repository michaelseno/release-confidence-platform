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
"""

from __future__ import annotations

import json
from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.core.time import utc_now_iso
from release_confidence_platform.storage.dynamodb_codec import (
    decode_dynamodb_response,
    encode_dynamodb_call_kwargs,
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


class CertificationRepository:
    """Phase 6 consumer reads and Phase 7 certification writes for Audit Platform Integrity."""

    def __init__(
        self,
        table_name: str,
        dynamodb_client: Any,
        s3_client: Any,
        bucket_name: str,
    ) -> None:
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client
        self.s3_client = s3_client
        self.bucket_name = bucket_name

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
    ) -> None:
        """Write or update the authoritative CertificationMetadata record.

        PutItem overwrites any existing record for the same identity tuple.
        Force re-runs update terminal_state, certificate_id, certjob_id, and
        completed_at. created_at is always set to the current write timestamp
        in this implementation (MVP scope: see assumption in implementation plan).

        Raises:
            AssertionError: If computed SK is not a Phase 7 SK.
            StorageError: On DynamoDB failure.
        """
        sk = (
            f"AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}"
            f"#AGG#{aggregation_version}#INTEL#{intelligence_version}"
            f"#RPT#{report_version}#CERT#{cert_version}#META"
        )
        _assert_phase7_sk(sk)
        now = utc_now_iso()
        item = {
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
            "report_id": report_id,
            "s3_certificate_ref": s3_cert_ref,
            "s3_report_artifact_ref": s3_report_artifact_ref,
            "aggregate_set_hash": aggregate_set_hash,
            "created_at": now,
            "completed_at": now,
        }
        self._put_item(item)

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

    def _put_item(self, item: dict[str, Any]) -> None:
        self._call("put_item", Item=item)

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
