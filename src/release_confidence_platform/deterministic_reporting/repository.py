"""DynamoDB repository for Phase 6 Deterministic Reporting.

Two responsibilities:
  (a) Phase 5 consumer read — read-only gate check on IntelligenceMetadata.
      Never writes to Phase 5 SK namespaces.
  (b) Phase 6 writes — targets exclusively Phase 6 SK namespaces (#RPTJOB# and #RPT#).

Sort key write prohibition: every write method calls _assert_phase6_sk() before
the DynamoDB call. This is a programming-error guard covering the same invariant
tested by test_engine_no_phase5_mutation.py.
"""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.storage.dynamodb_codec import (
    decode_dynamodb_response,
    encode_dynamodb_call_kwargs,
    storage_error_from_dynamodb_client_error,
    storage_error_from_dynamodb_request_error,
)

# Phase 6-exclusive SK segment markers. Any write targeting these patterns is permitted.
_PHASE6_SK_MARKERS = ("#RPTJOB#", "#RPT#")

# Phase 5-exclusive SK segments that must never appear in Phase 6 write paths.
_PHASE5_PROHIBITED_SK_MARKERS = ("#INTJOB#", "#LINEAGE#")


def _assert_phase6_sk(sk: str) -> None:
    """Assert that an SK is in Phase 6 namespace before any write.

    Raises AssertionError if the SK does not contain a Phase 6 marker, or if it
    contains any Phase 5 prohibited marker. This is a programming-error guard,
    not a user-facing validation.
    """
    has_phase6_marker = any(marker in sk for marker in _PHASE6_SK_MARKERS)
    has_prohibited = any(marker in sk for marker in _PHASE5_PROHIBITED_SK_MARKERS)
    if not has_phase6_marker or has_prohibited:
        raise AssertionError(
            f"Phase 6 write attempted to prohibited SK namespace: {sk!r}. "
            "Phase 6 writes must target only #RPTJOB# or #RPT# SK patterns."
        )


class ConditionalWriteError(StorageError):
    def __init__(self, message: str = "Conditional write failed"):
        super().__init__(message, "CONDITIONAL_WRITE_FAILED")


class ReportRepository:
    """Phase 5 consumer reads and Phase 6 report writes for Deterministic Reporting."""

    def __init__(self, table_name: str, dynamodb_client: Any) -> None:
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client

    # ------------------------------------------------------------------
    # Key construction helpers
    # ------------------------------------------------------------------

    def report_job_keys(
        self,
        client_id: str,
        audit_id: str,
        report_job_id: str,
    ) -> dict[str, str]:
        """Build the PK/SK key dict for a ReportJob record."""
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": f"AUDIT#{audit_id}#RPTJOB#{report_job_id}",
        }

    def report_metadata_keys(
        self,
        client_id: str,
        audit_id: str,
        audit_execution_id: str,
        config_version: str,
        aggregation_version: str,
        intelligence_version: str,
        report_version: str,
    ) -> dict[str, str]:
        """Build the PK/SK key dict for a ReportMetadata record."""
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": (
                f"AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}"
                f"#AGG#{aggregation_version}#INTEL#{intelligence_version}"
                f"#RPT#{report_version}#META"
            ),
        }

    # ------------------------------------------------------------------
    # Phase 5 read-only gate (never writes to Phase 5 records)
    # ------------------------------------------------------------------

    def get_intelligence_metadata(
        self,
        client_id: str,
        audit_id: str,
        audit_execution_id: str,
        config_version: str,
        aggregation_version: str,
        intelligence_version: str,
    ) -> dict[str, Any] | None:
        """Read the Phase 5 IntelligenceMetadata record for the prerequisite gate.

        Returns the record dict if found, or None if absent.
        Phase 6 reads this record but never writes to it.

        Args:
            client_id: Validated client identifier.
            audit_id: Validated audit identifier.
            audit_execution_id: Durable execution identity.
            config_version: Configuration version.
            aggregation_version: Aggregation version.
            intelligence_version: Intelligence version.

        Returns:
            IntelligenceMetadata dict, or None if not found.
        """
        key = {
            "PK": f"CLIENT#{client_id}",
            "SK": (
                f"AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}"
                f"#AGG#{aggregation_version}#INTEL#{intelligence_version}#META"
            ),
        }
        return self._get_item(key)

    # ------------------------------------------------------------------
    # Phase 6 idempotency read
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
        """Read the Phase 6 ReportMetadata record for idempotency check.

        Returns the record dict if found, or None if this is a first-time generation.

        Args:
            client_id: Validated client identifier.
            audit_id: Validated audit identifier.
            audit_execution_id: Durable execution identity.
            config_version: Configuration version.
            aggregation_version: Aggregation version.
            intelligence_version: Intelligence version.
            report_version: Report version.

        Returns:
            ReportMetadata dict, or None if not found.
        """
        key = self.report_metadata_keys(
            client_id,
            audit_id,
            audit_execution_id,
            config_version,
            aggregation_version,
            intelligence_version,
            report_version,
        )
        return self._get_item(key)

    # ------------------------------------------------------------------
    # Phase 6 writes — ReportJob
    # ------------------------------------------------------------------

    def put_report_job_once(self, item: dict[str, Any]) -> None:
        """Write a new ReportJob record (conditional, first-write-wins).

        Raises:
            AssertionError: If item SK is not a Phase 6 SK.
            ConditionalWriteError: If the record already exists.
            StorageError: On DynamoDB client or request failure.
        """
        _assert_phase6_sk(item.get("SK", ""))
        self._put_once(item)

    def update_report_job(
        self, key: dict[str, str], updates: dict[str, Any]
    ) -> None:
        """Apply field updates to an existing ReportJob record.

        Args:
            key: PK/SK dict from report_job_keys().
            updates: Dict of field name to new value to set.

        Raises:
            AssertionError: If key SK is not a Phase 6 SK.
            StorageError: On DynamoDB failure.
        """
        _assert_phase6_sk(key.get("SK", ""))
        self._update_item(key, updates)

    # ------------------------------------------------------------------
    # Phase 6 writes — ReportMetadata
    # ------------------------------------------------------------------

    def put_report_metadata_once(self, item: dict[str, Any]) -> None:
        """Write a new ReportMetadata record (conditional, first-write-wins).

        Raises:
            AssertionError: If item SK is not a Phase 6 SK.
            ConditionalWriteError: If the record already exists.
            StorageError: On DynamoDB client or request failure.
        """
        _assert_phase6_sk(item.get("SK", ""))
        self._put_once(item)

    def update_report_metadata_fields(
        self, key: dict[str, str], updates: dict[str, Any]
    ) -> None:
        """Apply field updates to an existing ReportMetadata record.

        Args:
            key: PK/SK dict from report_metadata_keys().
            updates: Dict of field name to new value to set.

        Raises:
            AssertionError: If key SK is not a Phase 6 SK.
            StorageError: On DynamoDB failure.
        """
        _assert_phase6_sk(key.get("SK", ""))
        self._update_item(key, updates)

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
