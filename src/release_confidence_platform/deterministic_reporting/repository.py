"""DynamoDB repository for Phase 6 Deterministic Reporting.

Two responsibilities:
  (a) Phase 5 consumer read — read-only gate check on IntelligenceMetadata.
      Never writes to Phase 5 SK namespaces.
  (b) Phase 6 writes — targets exclusively Phase 6 SK namespaces (#RPTJOB# and #RPT#).

Sort key write prohibition: every write method calls _assert_phase6_sk() before
the DynamoDB call. This is a programming-error guard covering the same invariant
tested by test_engine_no_phase5_mutation.py.

Evidence Governance Workstream A1.3d.3 (Technical Design Section 20.7.1-20.7.3;
ADR Decision 11, Non-Negotiable Invariant 31): ReportMetadata CREATE
(put_report_metadata_once) and regeneration (regenerate_report_metadata) are
hold-coordinated TransactWriteItems calls, structurally identical to the
already-merged Phase 5 IntelligenceMetadata contract
(reliability_intelligence/repository.py). ReportJob remains Category 3 --
never receives custody fields, hold coordination, or evidence-class tags.
update_report_metadata_fields remains a plain, unconditioned SET update for
ordinary status/field transitions and rejects any caller-supplied governance
field as a programming-error guard.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.core.exceptions import StorageError
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
    encode_value,
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


def _parse_phase6_metadata_identity(item: dict[str, Any]) -> tuple[str, str]:
    """Parse (client_id, audit_id) from a trusted, internally-constructed
    ReportMetadata item's PK/SK (Technical Design Section 20.7.1 item 4).

    This is not caller-input validation -- the item has already passed
    _assert_phase6_sk() by the time this is called. It exists solely to
    resolve the audit identity HoldCoordinatedTransactionRunner and
    HoldRepository.legal_hold_key() require. Mirrors
    reliability_intelligence/repository.py::_parse_phase5_metadata_identity
    exactly -- ReportMetadata's SK shares the identical
    AUDIT#{audit_id}#... prefix Phase 5's parser already handles.
    """
    pk, sk = item.get("PK", ""), item.get("SK", "")
    if not pk.startswith("CLIENT#") or not sk.startswith("AUDIT#"):
        raise StorageError(
            "ReportMetadata item PK/SK does not match the expected "
            "CLIENT#{client_id}/AUDIT#{audit_id}#... shape; cannot resolve "
            "audit identity for legal-hold state resolution.",
            "STORAGE_ERROR",
        )
    client_id = pk[len("CLIENT#") :]
    audit_id = sk[len("AUDIT#") :].split("#", 1)[0]
    if not client_id or not audit_id:
        raise StorageError(
            "ReportMetadata item PK/SK does not match the expected "
            "CLIENT#{client_id}/AUDIT#{audit_id}#... shape; cannot resolve "
            "audit identity for legal-hold state resolution.",
            "STORAGE_ERROR",
        )
    return client_id, audit_id


def _report_governance_fields(
    hold_state: dict[str, Any] | None, custody_period_days: int
) -> dict[str, int | str]:
    """Compute custody_expires_at/ttl_disposal_at/evidence_class for a Phase 6
    governed ReportMetadata write (Technical Design Section 20.7.1 item 6 /
    20.7.2).

    Mirrors reliability_intelligence/repository.py::_intelligence_governance_fields
    exactly, with evidence_class fixed to "report". custody_expires_at is
    always freshly computed; ttl_disposal_at is omitted if and only if this
    attempt's own hold_state read observed an ACTIVE hold.
    """
    now_epoch_seconds = int(datetime.now(UTC).timestamp())
    custody_expires_at = now_epoch_seconds + custody_period_days * 86400
    fields: dict[str, int | str] = {
        "custody_expires_at": custody_expires_at,
        "evidence_class": "report",
    }
    ttl_disposal_at = compute_ttl_disposal_at(hold_state, custody_expires_at)
    if ttl_disposal_at is not None:
        fields["ttl_disposal_at"] = ttl_disposal_at
    return fields


# Evidence Governance Workstream A1.3d.3 (Technical Design Section 20.7.2).
# custody_expires_at/ttl_disposal_at/evidence_class are repository-owned
# governance fields on regenerate_report_metadata -- a caller may never set
# them, mirroring AggregationRepository.update_job's
# _RETENTION_GOVERNED_FIELD_NAMES guard (aggregation/repository.py).
_REPORT_REGENERATION_GOVERNED_FIELD_NAMES = frozenset(
    {"custody_expires_at", "ttl_disposal_at", "evidence_class"}
)

# Evidence Governance Workstream A1.3d.3 (Technical Design Section 20.7.3).
# update_report_metadata_fields must reject any caller-supplied attempt to
# set these three repository-owned governance fields -- this is
# repository-ownership enforcement, not legal-hold coordination.
_FORBIDDEN_REPORT_METADATA_UPDATE_FIELDS = frozenset(
    {"custody_expires_at", "ttl_disposal_at", "evidence_class"}
)


class ReportRepository:
    """Phase 5 consumer reads and Phase 6 report writes for Deterministic Reporting."""

    def __init__(
        self,
        table_name: str,
        dynamodb_client: Any,
        hold_repository: HoldRepository | None = None,
        *,
        custody_period_days: int | None = None,
    ) -> None:
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client
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
        """Write a new ReportMetadata record as a hold-coordinated
        TransactWriteItems call (first generation) -- the existing
        conditional Put (attribute_not_exists(PK) AND attribute_not_exists(SK))
        plus the appended LegalHold.hold_version ConditionCheck (Technical
        Design Section 20.7.1).

        Used only when no existing ReportMetadata exists for the combination.
        A ConditionalWriteError indicates a concurrent generation attempt or race
        between a check and a put; the engine handles this by reading the existing record.

        Raises:
            StorageError: ``HOLD_COORDINATION_NOT_CONFIGURED`` if this
                instance has no HoldRepository; ``CUSTODY_PERIOD_CONFIG_MISSING``
                if no valid custody-period duration was injected -- both fail
                closed before any hold-state read, transact-item
                construction, or AWS request; ``HOLD_STATE_CONCURRENCY_EXCEEDED``
                on bounded hold-version retry exhaustion.
            ConditionalWriteError: If the record's own condition failed (an
                existing item at this key) -- never masked behind a
                hold-version retry.
        """
        self._governance_preflight()
        _assert_phase6_sk(item.get("SK", ""))
        client_id, audit_id = _parse_phase6_metadata_identity(item)
        base_item = dict(item)  # shallow copy -- NEVER sanitize() a persistence-bound item
        hold_key = self._hold_repository.legal_hold_key(client_id, audit_id)

        def build_transact_items(
            hold_state: dict[str, Any] | None,
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            item_with_governance = {
                **base_item,
                **_report_governance_fields(hold_state, self._custody_period_days),
            }
            put_transact_item = {
                "Put": {
                    "TableName": self.table_name,
                    "Item": encode_item(item_with_governance),
                    "ConditionExpression": (
                        "attribute_not_exists(PK) AND attribute_not_exists(SK)"
                    ),
                }
            }
            hold_condition_item = build_hold_version_condition_check_item(
                self.table_name, hold_key, hold_state
            )
            return [put_transact_item], hold_condition_item

        def _raise_conditional_write_error(reasons: list[dict[str, Any]]) -> None:
            del reasons
            raise ConditionalWriteError()

        runner = HoldCoordinatedTransactionRunner(self.dynamodb_client, self._hold_repository)
        runner.run(
            client_id,
            audit_id,
            build_transact_items,
            on_governed_condition_failed=_raise_conditional_write_error,
        )

    def regenerate_report_metadata(
        self,
        key: dict[str, str],
        updates: dict[str, Any],
        *,
        client_id: str,
        audit_id: str,
    ) -> None:
        """Dedicated, explicitly-typed regeneration operation for ReportMetadata
        (Technical Design Section 20.7.2) -- used only at the regen-detection
        branch point (engine.py's existing-record branch), distinct from
        update_report_metadata_fields, which remains used for ordinary status
        transitions.

        custody_expires_at, ttl_disposal_at, and evidence_class are
        repository-owned governance fields on this operation and are
        rejected -- never silently overridden -- if present in the
        caller-supplied updates dict. This check is the method's first
        action, before the governance preflight, before any hold-state
        read, and before any AWS request.

        The hold-coordinated TransactWriteItems Update SETs a freshly
        computed custody_expires_at and a fixed evidence_class="report"
        always; SETs ttl_disposal_at when the fresh hold-state read
        observes no active hold; explicitly REMOVEs ttl_disposal_at (not
        mere omission) when it observes an active hold, so a stale value
        from a prior generation is never silently preserved. Every other
        caller-supplied updates field is applied as an ordinary SET clause,
        unaffected by this contract.

        Args:
            key: PK/SK dict from report_metadata_keys().
            updates: Dict of non-governance field name to new value to set
                (e.g. report_job_id, status, generation_count, updated_at).
            client_id: Validated client identifier (structurally derived by
                the caller, not re-parsed from key here).
            audit_id: Validated audit identifier.

        Raises:
            AssertionError: If updates contains any forbidden governance
                field name.
            StorageError: ``HOLD_COORDINATION_NOT_CONFIGURED`` if this
                instance has no HoldRepository; ``CUSTODY_PERIOD_CONFIG_MISSING``
                if no valid custody-period duration was injected -- both fail
                closed before any hold-state read, transact-item
                construction, or AWS request; ``HOLD_STATE_CONCURRENCY_EXCEEDED``
                on bounded hold-version retry exhaustion.
        """
        forbidden = _REPORT_REGENERATION_GOVERNED_FIELD_NAMES & updates.keys()
        if forbidden:
            raise AssertionError(
                f"regenerate_report_metadata must never accept caller-supplied "
                f"governance fields {sorted(forbidden)!r}; custody_expires_at, "
                f"ttl_disposal_at, and evidence_class are computed internally, "
                f"never caller-controlled."
            )
        self._governance_preflight()
        _assert_phase6_sk(key.get("SK", ""))
        base_updates = dict(updates)  # shallow copy -- caller's dict is never mutated
        hold_key = self._hold_repository.legal_hold_key(client_id, audit_id)

        def build_transact_items(
            hold_state: dict[str, Any] | None,
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            governance_fields = _report_governance_fields(
                hold_state, self._custody_period_days
            )
            custody_expires_at = governance_fields["custody_expires_at"]
            evidence_class = governance_fields["evidence_class"]
            ttl_disposal_at = governance_fields.get("ttl_disposal_at")

            all_updates = {
                **base_updates,
                "custody_expires_at": custody_expires_at,
                "evidence_class": evidence_class,
            }
            names = {f"#f{i}": field_name for i, field_name in enumerate(all_updates)}
            values = {f":v{i}": value for i, value in enumerate(all_updates.values())}
            set_assignments = ", ".join(f"{name} = :v{i}" for i, name in enumerate(names))

            update_expression = f"SET {set_assignments}"
            if ttl_disposal_at is not None:
                extra_name = f"#f{len(names)}"
                extra_value = f":v{len(values)}"
                names[extra_name] = "ttl_disposal_at"
                values[extra_value] = ttl_disposal_at
                update_expression += f", {extra_name} = {extra_value}"
            else:
                # Active hold: explicit REMOVE, never mere omission -- omission
                # alone would silently preserve a stale prior-generation value
                # (Technical Design Section 20.7.2).
                update_expression += " REMOVE ttl_disposal_at"

            update_transact_item = {
                "Update": {
                    "TableName": self.table_name,
                    "Key": encode_item(key),
                    "UpdateExpression": update_expression,
                    "ExpressionAttributeNames": names,
                    "ExpressionAttributeValues": {
                        placeholder: encode_value(value)
                        for placeholder, value in values.items()
                    },
                }
            }
            hold_condition_item = build_hold_version_condition_check_item(
                self.table_name, hold_key, hold_state
            )
            return [update_transact_item], hold_condition_item

        runner = HoldCoordinatedTransactionRunner(self.dynamodb_client, self._hold_repository)
        runner.run(client_id, audit_id, build_transact_items)

    def update_report_metadata_fields(
        self, key: dict[str, str], updates: dict[str, Any]
    ) -> None:
        """Apply field updates to an existing ReportMetadata record.

        Remains a plain, unconditioned SET update for ordinary status/field
        transitions (PENDING->IN_PROGRESS, ->FAILED, ->COMPLETE) -- never
        touches custody_expires_at/ttl_disposal_at/evidence_class, and never
        performs hold coordination (Technical Design Section 20.7.3).

        Args:
            key: PK/SK dict from report_metadata_keys().
            updates: Dict of field name to new value to set.

        Raises:
            AssertionError: If key SK is not a Phase 6 SK, or if updates
                contains any repository-owned governance field name.
            StorageError: On DynamoDB failure.
        """
        forbidden = _FORBIDDEN_REPORT_METADATA_UPDATE_FIELDS.intersection(updates)
        if forbidden:
            raise AssertionError("ReportMetadata governance fields are repository-owned")
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
