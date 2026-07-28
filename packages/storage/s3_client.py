"""Lightweight S3 storage wrapper for config and raw evidence."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlencode

from botocore.exceptions import ClientError

from packages.core.constants.engine import RAW_RESULT_KEY_TEMPLATE
from packages.core.exceptions import ConfigError, DuplicateRunIdError, StorageError
from packages.sanitization.sanitizer import sanitize
from release_confidence_platform.core.exceptions import (
    StorageError as _HoldCoordinationStorageError,
)
from release_confidence_platform.evidence_retention.constants import (
    EVIDENCE_CLASS_TAG_KEY,
    HOLD_STATUS_ACTIVE,
    LEGAL_HOLD_TAG_KEY,
    LEGAL_HOLD_TAG_VALUE_FALSE,
    LEGAL_HOLD_TAG_VALUE_TRUE,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository

# Evidence Governance Workstream A1.LH3 (Technical Design Section 19.5.4,
# 19.8) correction: the prior module-level `_RAW_EVIDENCE_TAGGING` constant
# was computed once at import time from a hardcoded rcp-legal-hold=false --
# it could never reflect any runtime hold state by construction, which is
# precisely the defect this subphase closes. Tagging is now computed fresh,
# per call, by `_raw_evidence_tagging(hold_state)` below, from a hold_state
# read immediately before each `put_object` -- see `write_raw_results_once`.
# rcp-evidence-class remains the only immutable, hardcoded-per-call-site
# component (every call through this method writes a raw_evidence-class
# object, confirmed by the Technical Design), so it is not reintroduced as a
# module-level constant either -- it is folded directly into
# `_raw_evidence_tagging`'s per-call computation for locality with the field
# it is always paired with on the wire.


def _raw_evidence_tagging(hold_state: dict[str, Any] | None) -> str:
    """Compute the rcp-legal-hold/rcp-evidence-class Tagging string for one
    raw-evidence PutObject call, from the hold_state read immediately before
    this specific call (Technical Design Section 19.5.4).

    rcp-legal-hold is `true` if and only if `hold_state` reflects a currently
    ACTIVE hold; `false` for both "no hold record exists" (hold_state is
    None) and "the audit was held but has since been RELEASED". This must
    never be computed from anything cached or fixed at import/construction
    time -- see the module-level comment above and
    tests/unit/test_raw_evidence_s3_tagging.py's
    `test_write_raw_results_once_does_not_reuse_stale_module_level_hold_state`
    for the direct regression test proving that.
    """
    is_actively_held = hold_state is not None and hold_state.get("status") == HOLD_STATUS_ACTIVE
    legal_hold_value = LEGAL_HOLD_TAG_VALUE_TRUE if is_actively_held else LEGAL_HOLD_TAG_VALUE_FALSE
    return urlencode(
        {
            LEGAL_HOLD_TAG_KEY: legal_hold_value,
            EVIDENCE_CLASS_TAG_KEY: "raw_evidence",
        }
    )


def _parse_raw_evidence_key_identity(key: str) -> tuple[str, str]:
    """Extract (client_id, audit_id) from a raw-evidence S3 key.

    Raw-evidence keys are always constructed via
    `S3StorageClient.build_raw_result_key` from
    `packages.core.constants.engine.RAW_RESULT_KEY_TEMPLATE`
    (`raw-results/{client_id}/{audit_id}/{run_id}/results.json`) --
    `write_raw_results_once` is "the sole PutObject call site for raw
    execution evidence" (confirmed by the Technical Design), so this parse
    is against a locked, single-producer key shape, not a heuristic over
    arbitrary caller input. Parsing from the key (rather than requiring an
    additional client_id/audit_id parameter on write_raw_results_once, or
    reading them out of the caller-supplied payload) keeps this write path's
    existing two-parameter signature unchanged, so its one production call
    site (apps/backend/orchestrator/service.py) requires no change.
    """
    parts = key.split("/")
    if len(parts) < 3 or parts[0] != "raw-results" or not parts[1] or not parts[2]:
        raise StorageError(
            "Raw evidence key does not match the expected "
            "raw-results/{client_id}/{audit_id}/{run_id}/... shape; cannot "
            "resolve audit identity for legal-hold state resolution "
            f"(key_prefix={_safe_key_prefix(key)}).",
            "STORAGE_ERROR",
        )
    return parts[1], parts[2]


class S3StorageClient:
    def __init__(
        self,
        bucket_name: str,
        s3_client: Any,
        hold_repository: HoldRepository | None = None,
    ):
        """
        Evidence Governance Workstream A1.LH3 (Technical Design Section
        19.5.4, 19.8): `hold_repository` is an additive, optional dependency.
        `read_json`/`object_exists`/`write_json`/`build_raw_result_key`/
        `list_raw_evidence_keys` never consult it and are unaffected either
        way. `write_raw_results_once` (the sole raw-evidence governed write)
        requires it -- Technical Design Section 19.14's uniform fail-closed
        rule -- and raises `StorageError` (`HOLD_COORDINATION_NOT_CONFIGURED`)
        if it is None rather than writing without ever having checked
        legal-hold state.
        """
        self.bucket_name = bucket_name
        self.s3_client = s3_client
        self._hold_repository = hold_repository

    def read_json(self, key: str) -> dict[str, Any]:
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            body = response["Body"].read().decode("utf-8")
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ConfigError("Config JSON is invalid", "CONFIG_LOAD_ERROR") from exc
        except Exception as exc:
            raise ConfigError("Config object could not be loaded", "CONFIG_LOAD_ERROR") from exc

    def object_exists(self, key: str) -> bool:
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _OBJECT_NOT_FOUND_CODES:
                return False
            raise _storage_error_from_s3_client_error(
                exc, key=key, operation="head_object"
            ) from exc
        except FileNotFoundError:
            return False

    def write_json(self, key: str, payload: dict[str, Any], *, overwrite: bool = False) -> None:
        if not overwrite and self.object_exists(key):
            raise StorageError("Config object exists", "CONFIG_OBJECT_EXISTS")
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json.dumps(sanitize(payload), sort_keys=True).encode("utf-8"),
                ContentType="application/json",
            )
        except ClientError as exc:
            raise _storage_error_from_s3_client_error(exc, key=key, operation="put_object") from exc
        except Exception as exc:
            raise StorageError("S3 config write failed", "STORAGE_ERROR") from exc

    def build_raw_result_key(self, client_id: str, audit_id: str, run_id: str) -> str:
        return RAW_RESULT_KEY_TEMPLATE.format(client_id=client_id, audit_id=audit_id, run_id=run_id)

    def list_raw_evidence_keys(self, client_id: str, audit_id: str) -> list[str]:
        """List all S3 object keys under raw-results/{client_id}/{audit_id}/.

        Follows ContinuationToken pagination to return the complete result set.
        """
        prefix = f"raw-results/{client_id}/{audit_id}/"
        keys: list[str] = []
        kwargs: dict[str, Any] = {"Bucket": self.bucket_name, "Prefix": prefix}
        while True:
            try:
                response = self.s3_client.list_objects_v2(**kwargs)
            except ClientError as exc:
                raise _storage_error_from_s3_client_error(
                    exc, key=prefix, operation="list_objects_v2"
                ) from exc
            for obj in response.get("Contents", []):
                keys.append(obj["Key"])
            if not response.get("IsTruncated"):
                break
            continuation = response.get("NextContinuationToken")
            if not continuation:
                break
            kwargs["ContinuationToken"] = continuation
        return keys

    def write_raw_results_once(self, key: str, payload: dict[str, Any]) -> None:
        # Existing object-key construction and duplicate-write behavior
        # unchanged (Technical Design Section 19.8): the pre-existing
        # check-then-write duplicate guard is untouched by this correction --
        # A1.LH2's canary-marker/reconciliation mechanism (out of this
        # subphase's scope) is what closes the PLACE/RELEASE race window for
        # this write, not a change here.
        if self.object_exists(key):
            raise DuplicateRunIdError()
        # Evidence Governance Workstream A1.LH3 (Technical Design Section
        # 19.5.4, 19.14): a Category 1 governed write must never proceed
        # without deterministically resolving current legal-hold state
        # first. An S3StorageClient constructed without a HoldRepository
        # cannot resolve that state at all, so this fails closed here rather
        # than falling back to the old hardcoded/module-level tagging.
        if self._hold_repository is None:
            raise StorageError(
                "Raw evidence write requires a configured legal-hold "
                "coordination dependency (HoldRepository via "
                "S3StorageClient's hold_repository constructor argument) to "
                "resolve current hold state before writing; none was "
                "supplied to this instance. Refusing to write unconditionally "
                "rather than silently skipping legal-hold verification.",
                "HOLD_COORDINATION_NOT_CONFIGURED",
            )
        client_id, audit_id = _parse_raw_evidence_key_identity(key)
        # Technical Design Section 19.5.4: the S3 write path has no
        # transactional backstop the way the DynamoDB leg does (Section
        # 19.4's TransactWriteItems re-verifies hold_version at commit time
        # regardless of read staleness) -- ConsistentRead=True is required
        # here specifically so this read cannot silently miss a very
        # recently committed hold placement/release.
        try:
            hold_state = self._hold_repository.get_legal_hold(
                client_id, audit_id, consistent_read=True
            )
        except _HoldCoordinationStorageError as exc:
            # HoldRepository lives in release_confidence_platform.
            # evidence_retention and raises release_confidence_platform.
            # core.exceptions.StorageError -- a different exception
            # hierarchy than this module's own packages.core.exceptions.
            # StorageError, which apps/backend/orchestrator/service.py's
            # `except EngineError` boundary actually catches. Re-raise as
            # the local StorageError, preserving error_type/message, so the
            # failure remains distinguishable rather than being silently
            # swallowed into a generic ORCHESTRATION_ERROR.
            raise StorageError(exc.message, exc.error_type) from exc
        except Exception as exc:
            # Any other unexpected failure resolving hold state (e.g. a
            # non-StorageError raised by a caller-supplied hold_repository
            # double) must still fail closed before put_object is ever
            # attempted (Technical Design Section 19.14) -- never proceed to
            # write with an unresolved hold state.
            raise StorageError(
                "Legal-hold state could not be resolved prior to raw "
                "evidence write; failing closed rather than writing without "
                "a verified hold state.",
                "HOLD_STATE_UNRESOLVABLE",
            ) from exc
        tagging = _raw_evidence_tagging(hold_state)
        sanitized = sanitize(payload)
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json.dumps(sanitized, sort_keys=True).encode("utf-8"),
                ContentType="application/json",
                Tagging=tagging,
            )
        except ClientError as exc:
            raise _storage_error_from_s3_client_error(exc, key=key, operation="put_object") from exc
        except Exception as exc:
            raise StorageError("S3 raw result write failed", "STORAGE_ERROR") from exc


_OBJECT_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}
_BUCKET_NOT_FOUND_CODES = {"NoSuchBucket"}
_PERMISSION_CODES = {"AccessDenied", "Forbidden"}
_REGION_CODES = {
    "PermanentRedirect",
    "AuthorizationHeaderMalformed",
    "IllegalLocationConstraintException",
}
_SAFE_ERROR_CODE_PATTERN = re.compile(r"[^A-Za-z0-9_.:-]")


def _storage_error_from_s3_client_error(
    exc: ClientError, *, key: str, operation: str
) -> StorageError:
    aws_code = _safe_aws_error_code(exc)
    key_prefix = _safe_key_prefix(key)
    required_permission = _required_permission(operation)
    context = (
        f"aws_error_code={aws_code}; operation={operation}; key_prefix={key_prefix}; "
        f"required_permission={required_permission}"
    )
    if aws_code in _BUCKET_NOT_FOUND_CODES:
        return StorageError(
            f"S3 runtime bucket not found or not configured ({context})",
            "STORAGE_CONFIG_ERROR",
        )
    if aws_code in _PERMISSION_CODES:
        return StorageError(
            f"S3 runtime bucket permission denied ({context})",
            "STORAGE_PERMISSION_ERROR",
        )
    if aws_code in _REGION_CODES:
        return StorageError(
            f"S3 runtime bucket region mismatch or redirect ({context})",
            "STORAGE_CONFIG_ERROR",
        )
    return StorageError(f"S3 runtime storage operation failed ({context})", "STORAGE_ERROR")


def _required_permission(operation: str) -> str:
    if operation == "head_object":
        return "s3:GetObject+s3:ListBucket"
    if operation == "put_object":
        return "s3:PutObject"
    if operation == "list_objects_v2":
        return "s3:ListBucket"
    return "s3:GetObject"


def _safe_aws_error_code(exc: ClientError) -> str:
    code = str(exc.response.get("Error", {}).get("Code") or "Unknown")
    sanitized = _SAFE_ERROR_CODE_PATTERN.sub("", code)
    return sanitized[:80] or "Unknown"


def _safe_key_prefix(key: str) -> str:
    prefix = key.split("/", 1)[0] if key else "<empty>"
    sanitized = _SAFE_ERROR_CODE_PATTERN.sub("", prefix)
    return sanitized[:80] or "<unknown>"
