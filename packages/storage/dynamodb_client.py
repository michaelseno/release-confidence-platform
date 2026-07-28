"""Lightweight DynamoDB run metadata wrapper."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from packages.core.constants.engine import RUN_STATUSES
from packages.core.exceptions import DuplicateRunIdError, StorageError
from release_confidence_platform.core.exceptions import (
    StorageError as _HoldCoordinationStorageError,
)
from release_confidence_platform.evidence_retention.constants import (
    CUSTODY_EXPIRES_AT_ATTRIBUTE,
    EVIDENCE_CLASSES,
    TTL_DISPOSAL_AT_ATTRIBUTE,
)
from release_confidence_platform.evidence_retention.hold_coordination import (
    HoldCoordinatedTransactionRunner,
    build_hold_version_condition_check_item,
    compute_ttl_disposal_at,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from release_confidence_platform.storage.dynamodb_codec import encode_item

# Evidence Governance Workstream A1.3b (Technical Design Section 18.1,
# Category 2 -- evidence-derived artifact; ADR Decision 5 / Non-Negotiable
# Invariant 3).
#
# RunMetadata's custody_expires_at/ttl_disposal_at are computed independently
# at this write's own time from custody_period_days.raw_evidence.${stage} --
# never copied from the sibling raw-evidence S3 write, never hardcoded (see
# _resolve_custody_period_days_env below).
#
# This env var name is a forward-declared consumption point only. No change
# in this subphase wires it into infra/serverless.yml's provider.environment
# block (that is an infra change, out of A1.3b's authorized scope) or into
# any Lambda handler's client construction. Until a follow-up, separately
# authorized change does so, this variable is unset in every deployed stage
# (dev/staging/prod), and put_started_once fails closed on every invocation
# rather than silently writing RunMetadata without the custody fields -- see
# the implementation report for this subphase for the full flagged gap.
CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR = "CUSTODY_PERIOD_DAYS_RAW_EVIDENCE"

_SECONDS_PER_DAY = 86400

# Evidence Governance Workstream A1.3b.1 (Technical Design Section 18.1,
# Category 2 table -- corrects a gap disclosed in the TD's own text:
# "Known gap in already-merged A1.3b ... does not persist evidence_class").
# RunMetadata always points at raw execution evidence (raw-results/), so
# this value is a fixed, hardcoded constant -- never a parameter to
# _run_metadata_custody_fields(), never derived from the caller-supplied
# item, and never overridable by any caller. It matches, by value only (the
# two are computed independently per Section 18.1's Category 2 rule), the
# same fixed value already hardcoded on the sibling S3 write path's tagging
# (packages/storage/s3_client.py::_RAW_EVIDENCE_TAGGING,
# EVIDENCE_CLASS_TAG_KEY: "raw_evidence") and DisposalRecord.evidence_class's
# field naming convention (evidence_retention/models.py).
_RUN_METADATA_EVIDENCE_CLASS = "raw_evidence"
assert _RUN_METADATA_EVIDENCE_CLASS in EVIDENCE_CLASSES, (
    f"{_RUN_METADATA_EVIDENCE_CLASS!r} must be a member of the bounded "
    "EVIDENCE_CLASSES set (evidence_retention/constants.py)"
)


def _resolve_custody_period_days_env(env_var: str) -> int:
    """Read a positive-integer custody-period-days value from the environment.

    Never assumes or hardcodes a duration value (ADR Non-Negotiable Invariant
    3): the value is read fresh from the environment on every call, so a
    later-populated environment variable takes effect without a code change.

    Raises:
        StorageError: ``CUSTODY_PERIOD_CONFIG_MISSING`` if the variable is
            unset, empty, non-numeric, or not a positive integer -- the
            caller must fail closed rather than write the record without
            custody_expires_at/ttl_disposal_at.
    """
    raw_value = os.environ.get(env_var)
    if raw_value is not None:
        try:
            parsed = int(raw_value)
        except ValueError:
            parsed = None
        if parsed is not None and parsed > 0:
            return parsed
    raise StorageError(
        f"Custody-period configuration is unresolvable at runtime (environment "
        f"variable {env_var} is unset, empty, or not a positive integer); refusing "
        "to write a governed record without custody_expires_at/ttl_disposal_at "
        "rather than silently omitting them or assuming a duration.",
        "CUSTODY_PERIOD_CONFIG_MISSING",
    )


def _run_metadata_custody_fields(hold_state: dict[str, Any] | None) -> dict[str, int | str]:
    """Compute custody_expires_at/ttl_disposal_at/evidence_class for a
    RunMetadata CREATE.

    Evidence Governance Workstream A1.LH3 (Technical Design Section 19.8)
    correction: the prior docstring here reasoned "no hold can exist yet for
    a record that does not exist yet" and therefore set ttl_disposal_at
    unconditionally. That reasoning answered the wrong question -- the
    *record* cannot be held before it exists, but the *audit* it belongs to
    can already be under an active legal hold from an earlier point in the
    same EventBridge-scheduled execution window (Technical Design Section
    19, amendment preamble). `hold_state` is the LegalHold record read by
    the caller's HoldCoordinatedTransactionRunner for the attempt currently
    being built (Section 19.4 step 1/2) -- ttl_disposal_at is omitted
    (`compute_ttl_disposal_at` returns None) if and only if that read
    observed an ACTIVE hold; otherwise it equals custody_expires_at, exactly
    as before. custody_expires_at itself remains independently computed,
    never derived from hold state.

    evidence_class is a fixed constant (_RUN_METADATA_EVIDENCE_CLASS), not
    computed from anything -- included here so the caller's single merge
    (`{**item, **_run_metadata_custody_fields(hold_state)}`) both
    establishes the governed fields atomically and guarantees the fixed
    value always wins over any same-named key the caller's `item` might
    already contain (Technical Design Section 18.1 Category 2 table).
    """
    custody_period_days = _resolve_custody_period_days_env(
        CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR
    )
    now_epoch_seconds = int(datetime.now(UTC).timestamp())
    custody_expires_at = now_epoch_seconds + custody_period_days * _SECONDS_PER_DAY
    fields: dict[str, int | str] = {
        CUSTODY_EXPIRES_AT_ATTRIBUTE: custody_expires_at,
        "evidence_class": _RUN_METADATA_EVIDENCE_CLASS,
    }
    ttl_disposal_at = compute_ttl_disposal_at(hold_state, custody_expires_at)
    if ttl_disposal_at is not None:
        fields[TTL_DISPOSAL_AT_ATTRIBUTE] = ttl_disposal_at
    return fields


class DynamoDBMetadataClient:
    def __init__(
        self,
        table_name: str,
        dynamodb_client: Any,
        hold_repository: HoldRepository | None = None,
        transact_dynamodb_client: Any | None = None,
    ):
        """
        Evidence Governance Workstream A1.LH3 (Technical Design Section 19.8,
        19.10 item (c+d)): `hold_repository` and `transact_dynamodb_client`
        are additive, optional dependencies -- `dynamodb_client` keeps its
        existing role backing `keys`/`metadata_exists`/`update_terminal`
        (a `boto3.resource("dynamodb").Table` in production, per
        `apps/backend/handlers/orchestrator_handler.py`) unchanged.

        `transact_dynamodb_client` must be a low-level `boto3.client("dynamodb")`
        (or equivalent) -- `TransactWriteItems` and the wire-format item
        encoding it requires (`dynamodb_codec.encode_item`) are not available
        on a `Table` resource. When omitted, it defaults to `dynamodb_client`
        itself (only correct if that object already supports
        `transact_write_items`); production wiring always supplies
        `table.meta.client` explicitly (see orchestrator_handler.py /
        scheduled_execution_handler.py).

        `hold_repository` is required for `put_started_once` specifically
        (Technical Design Section 19.14's uniform fail-closed rule) -- when
        omitted, `put_started_once` raises `StorageError`
        (`HOLD_COORDINATION_NOT_CONFIGURED`) rather than writing RunMetadata
        without ever having checked legal-hold state. `keys`/`metadata_exists`/
        `update_terminal` are unaffected either way (Technical Design Section
        19.7 row 2: `update_terminal` never touches custody fields).
        """
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client
        self._hold_repository = hold_repository
        transact_client = (
            transact_dynamodb_client if transact_dynamodb_client is not None else dynamodb_client
        )
        self._hold_coordination_runner = (
            HoldCoordinatedTransactionRunner(transact_client, hold_repository)
            if hold_repository is not None
            else None
        )

    def keys(self, client_id: str, audit_id: str, run_id: str) -> dict[str, str]:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#RUN#{run_id}"}

    def metadata_exists(self, client_id: str, audit_id: str, run_id: str) -> bool:
        response = self._call("get_item", Key=self.keys(client_id, audit_id, run_id))
        return "Item" in response

    def put_started_once(self, item: dict[str, Any]) -> None:
        if item.get("status") not in RUN_STATUSES:
            raise StorageError("Invalid run status", "STORAGE_ERROR")
        # Evidence Governance Workstream A1.LH3 (Technical Design Section
        # 19.4, 19.14): RunMetadata CREATE is a Category 1/2 governed write --
        # it may never proceed to completion without deterministically
        # resolving the audit identity's current legal-hold state first. A
        # DynamoDBMetadataClient constructed without a HoldRepository cannot
        # resolve that state at all, so it fails closed here rather than
        # falling back to the old unconditioned put_item.
        if self._hold_coordination_runner is None or self._hold_repository is None:
            raise StorageError(
                "RunMetadata CREATE requires a configured legal-hold "
                "coordination dependency (HoldRepository via "
                "DynamoDBMetadataClient's hold_repository constructor "
                "argument) to resolve current hold state before writing; "
                "none was supplied to this instance. Refusing to write "
                "unconditionally rather than silently skipping legal-hold "
                "verification.",
                "HOLD_COORDINATION_NOT_CONFIGURED",
            )
        client_id = item["client_id"]
        audit_id = item["audit_id"]
        # Shallow-copied once, outside the retry closure below -- the
        # caller's own dict is never mutated (apps/backend/orchestrator/
        # service.py retains its own reference to started_item for
        # failure-path bookkeeping and must not observe this write's
        # internal fields), unchanged from the pre-A1.LH3 contract.
        item_copy = dict(item)
        hold_key = self._hold_repository.legal_hold_key(client_id, audit_id)

        def build_transact_items(
            hold_state: dict[str, Any] | None,
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            # Custody fields (custody_expires_at/ttl_disposal_at) and
            # evidence_class are computed fresh against this attempt's own
            # hold_state read (Technical Design Section 19.4 step 2) and
            # merged second, so the fixed evidence_class value always
            # overrides any same-named key the caller's item might already
            # contain -- evidence_class remains never caller-controlled.
            item_with_custody = {**item_copy, **_run_metadata_custody_fields(hold_state)}
            put_transact_item = {
                "Put": {
                    "TableName": self.table_name,
                    "Item": encode_item(item_with_custody),
                    "ConditionExpression": (
                        "attribute_not_exists(PK) AND attribute_not_exists(SK)"
                    ),
                }
            }
            hold_condition_item = build_hold_version_condition_check_item(
                self.table_name, hold_key, hold_state
            )
            return [put_transact_item], hold_condition_item

        def _raise_duplicate_run_id(reasons: list[dict[str, Any]]) -> None:
            # Technical Design Section 19.4 step 4's explicit precedence: the
            # governed record's own condition failure (a genuine duplicate
            # run_id) always wins over -- and is never masked behind -- a
            # concurrent hold-version race, even if both failed in the same
            # attempt.
            del reasons
            raise DuplicateRunIdError()

        try:
            self._hold_coordination_runner.run(
                client_id,
                audit_id,
                build_transact_items,
                on_governed_condition_failed=_raise_duplicate_run_id,
            )
        except DuplicateRunIdError:
            raise
        except _HoldCoordinationStorageError as exc:
            # HoldCoordinatedTransactionRunner/HoldRepository live in
            # release_confidence_platform.evidence_retention and raise
            # release_confidence_platform.core.exceptions.StorageError
            # subclasses (e.g. HoldStateConcurrencyExceededError,
            # HOLD_STATE_CONCURRENCY_EXCEEDED) -- a *different* exception
            # hierarchy than this module's own packages.core.exceptions.
            # StorageError, which apps/backend/orchestrator/service.py's
            # `except EngineError` boundary actually catches. Re-raise as the
            # local StorageError, preserving the original error_type/message
            # verbatim, so Technical Design Section 19.15's distinguishable
            # error codes survive the orchestrator's error-handling boundary
            # instead of being silently swallowed into a generic
            # ORCHESTRATION_ERROR.
            raise StorageError(exc.message, exc.error_type) from exc

    def update_terminal(self, key: dict[str, str], updates: dict[str, Any]) -> None:
        # Evidence Governance Workstream A1.3b/A1.3b.1 (Technical Design
        # Section 11 row 1 / Section 18.1, Category 2): this is a
        # terminal-status transition on an already-existing RunMetadata
        # record, not a regeneration (RunMetadata has no regeneration path
        # at all -- see _run_metadata_custody_fields above). This method
        # must NEVER recompute, set, or otherwise reference
        # custody_expires_at, ttl_disposal_at, or evidence_class -- only the
        # fields the caller explicitly supplies in `updates`
        # (status/completed_at/raw_result_s3_key/failure_summary today) are
        # ever written. Do not add any of these three fields to this method
        # under any circumstance without a corresponding Technical Design
        # change.
        if updates.get("status") not in RUN_STATUSES:
            raise StorageError("Invalid run status", "STORAGE_ERROR")
        expression_names = {f"#k{i}": k for i, k in enumerate(updates)}
        expression_values = {f":v{i}": v for i, v in enumerate(updates.values())}
        assignments = ", ".join(f"{name} = :v{i}" for i, name in enumerate(expression_names))
        self._call(
            "update_item",
            Key=key,
            UpdateExpression=f"SET {assignments}",
            ExpressionAttributeNames=expression_names,
            ExpressionAttributeValues=expression_values,
            ConditionExpression="attribute_exists(PK) AND attribute_exists(SK)",
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
            return method(TableName=self.table_name, **kwargs)
        except TypeError:
            return method(**kwargs)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in (preserve_client_error_codes or set()):
                raise
            raise _storage_error_from_dynamodb_client_error(exc, operation=method_name) from exc


_MISSING_TABLE_CODES = {"ResourceNotFoundException"}
_PERMISSION_CODES = {
    "AccessDenied",
    "AccessDeniedException",
    "UnauthorizedOperation",
    "UnrecognizedClientException",
}


def _storage_error_from_dynamodb_client_error(exc: ClientError, *, operation: str) -> StorageError:
    aws_code = _safe_aws_error_code(exc)
    context = (
        f"aws_error_code={aws_code}; operation={operation}; "
        "required_permissions=dynamodb:GetItem,dynamodb:PutItem,dynamodb:UpdateItem"
    )
    if aws_code in _MISSING_TABLE_CODES:
        return StorageError(
            f"DynamoDB run metadata table not found ({context})", "STORAGE_CONFIG_ERROR"
        )
    if aws_code in _PERMISSION_CODES:
        return StorageError(
            f"DynamoDB run metadata permission denied ({context})", "STORAGE_PERMISSION_ERROR"
        )
    return StorageError(f"DynamoDB run metadata operation failed ({context})", "STORAGE_ERROR")


def _safe_aws_error_code(exc: ClientError) -> str:
    code = str(exc.response.get("Error", {}).get("Code") or "Unknown")
    sanitized = "".join(ch for ch in code if ch.isalnum() or ch in "_.:-")
    return sanitized[:80] or "Unknown"
