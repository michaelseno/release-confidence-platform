"""Lightweight S3 storage wrapper for config and raw evidence."""

from __future__ import annotations

import json
import re
from typing import Any

from botocore.exceptions import ClientError

from packages.core.constants.engine import RAW_RESULT_KEY_TEMPLATE
from packages.core.exceptions import ConfigError, DuplicateRunIdError, StorageError
from packages.sanitization.sanitizer import sanitize


class S3StorageClient:
    def __init__(self, bucket_name: str, s3_client: Any):
        self.bucket_name = bucket_name
        self.s3_client = s3_client

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
        if self.object_exists(key):
            raise DuplicateRunIdError()
        sanitized = sanitize(payload)
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json.dumps(sanitized, sort_keys=True).encode("utf-8"),
                ContentType="application/json",
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
