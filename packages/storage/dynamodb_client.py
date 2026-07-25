"""Lightweight DynamoDB run metadata wrapper."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from packages.core.constants.engine import RUN_STATUSES
from packages.core.exceptions import DuplicateRunIdError, StorageError
from release_confidence_platform.evidence_retention.constants import (
    CUSTODY_EXPIRES_AT_ATTRIBUTE,
    EVIDENCE_CLASSES,
    TTL_DISPOSAL_AT_ATTRIBUTE,
)

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


def _run_metadata_custody_fields() -> dict[str, int | str]:
    """Compute custody_expires_at/ttl_disposal_at/evidence_class for a
    RunMetadata CREATE.

    Ordinary CREATE only: no hold can exist yet for a record that does not
    exist yet, so ttl_disposal_at is unconditionally set equal to
    custody_expires_at here -- the hold-conditional branch only applies on
    regeneration (Technical Design Section 18.4), and RunMetadata has no
    regeneration path (Section 18.1 classifies it CREATE + FINALIZATION
    only).

    evidence_class is a fixed constant (_RUN_METADATA_EVIDENCE_CLASS), not
    computed from anything -- included here so put_started_once's single
    merge (`{**item, **_run_metadata_custody_fields()}`) both establishes
    all three governed fields atomically and guarantees the fixed value
    always wins over any same-named key the caller's `item` might already
    contain (Technical Design Section 18.1 Category 2 table).
    """
    custody_period_days = _resolve_custody_period_days_env(
        CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR
    )
    now_epoch_seconds = int(datetime.now(UTC).timestamp())
    custody_expires_at = now_epoch_seconds + custody_period_days * _SECONDS_PER_DAY
    return {
        CUSTODY_EXPIRES_AT_ATTRIBUTE: custody_expires_at,
        TTL_DISPOSAL_AT_ATTRIBUTE: custody_expires_at,
        "evidence_class": _RUN_METADATA_EVIDENCE_CLASS,
    }


class DynamoDBMetadataClient:
    def __init__(self, table_name: str, dynamodb_client: Any):
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client

    def keys(self, client_id: str, audit_id: str, run_id: str) -> dict[str, str]:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#RUN#{run_id}"}

    def metadata_exists(self, client_id: str, audit_id: str, run_id: str) -> bool:
        response = self._call("get_item", Key=self.keys(client_id, audit_id, run_id))
        return "Item" in response

    def put_started_once(self, item: dict[str, Any]) -> None:
        if item.get("status") not in RUN_STATUSES:
            raise StorageError("Invalid run status", "STORAGE_ERROR")
        # Evidence Governance Workstream A1.3b/A1.3b.1: custody fields
        # (custody_expires_at/ttl_disposal_at) and evidence_class are
        # computed here, at write time, and merged into a copy of the
        # caller-supplied item -- the caller's own dict is never mutated
        # (apps/backend/orchestrator/service.py retains its own reference to
        # started_item for failure-path bookkeeping and must not observe
        # this write's internal fields). The custody-fields dict is merged
        # second (`{**item, **_run_metadata_custody_fields()}`), so its
        # fixed evidence_class value always overrides any same-named key the
        # caller's item might already contain -- evidence_class is never
        # caller-controlled for this write path.
        item_with_custody = {**item, **_run_metadata_custody_fields()}
        try:
            self._call(
                "put_item",
                preserve_client_error_codes={"ConditionalCheckFailedException"},
                Item=item_with_custody,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise DuplicateRunIdError() from exc
            raise _storage_error_from_dynamodb_client_error(exc, operation="put_item") from exc

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
