"""Lightweight S3 storage wrapper for config and raw evidence."""

from __future__ import annotations

import json
from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.core.constants.engine import RAW_RESULT_KEY_TEMPLATE
from release_confidence_platform.core.exceptions import (
    ConfigError,
    DuplicateRunIdError,
    StorageError,
)
from release_confidence_platform.sanitization.sanitizer import sanitize


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

    def read_text(self, key: str) -> str:
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            return response["Body"].read().decode("utf-8")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                raise StorageError("Config object not found", "CONFIG_ARTIFACT_NOT_FOUND") from exc
            raise StorageError("S3 config read failed", "STORAGE_ERROR") from exc
        except Exception as exc:
            raise StorageError("S3 config read failed", "STORAGE_ERROR") from exc

    def head_metadata(self, key: str) -> dict[str, Any] | None:
        try:
            response = self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise StorageError("S3 metadata lookup failed", "STORAGE_ERROR") from exc
        except FileNotFoundError:
            return None
        metadata = {
            "key": key,
            "last_modified": response.get("LastModified"),
            "version_id": response.get("VersionId"),
            "size_bytes": response.get("ContentLength"),
        }
        return {k: _metadata_value(v) for k, v in metadata.items() if v is not None}

    def list_keys(
        self, prefix: str, *, max_keys: int = 1000, continuation_token: str | None = None
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"Bucket": self.bucket_name, "Prefix": prefix, "MaxKeys": max_keys}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token
        try:
            response = self.s3_client.list_objects_v2(**kwargs)
        except Exception as exc:
            raise StorageError("S3 list failed", "STORAGE_ERROR") from exc
        return {
            "keys": [obj.get("Key") for obj in response.get("Contents", []) if obj.get("Key")],
            "next_token": response.get("NextContinuationToken"),
        }

    def object_exists(self, key: str) -> bool:
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise StorageError("S3 existence check failed", "STORAGE_ERROR") from exc
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
        except Exception as exc:
            raise StorageError("S3 config write failed", "STORAGE_ERROR") from exc

    def build_raw_result_key(self, client_id: str, audit_id: str, run_id: str) -> str:
        return RAW_RESULT_KEY_TEMPLATE.format(client_id=client_id, audit_id=audit_id, run_id=run_id)

    def write_raw_results_once(self, key: str, payload: dict[str, Any]) -> None:
        if self.object_exists(key):
            raise DuplicateRunIdError()
        sanitized = sanitize(payload)
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=json.dumps(sanitized, sort_keys=True).encode("utf-8"),
            ContentType="application/json",
        )


def _metadata_value(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value
