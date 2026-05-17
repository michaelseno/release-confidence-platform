"""Lightweight S3 storage wrapper for config and raw evidence."""

from __future__ import annotations

import json
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
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise StorageError("S3 existence check failed", "STORAGE_ERROR") from exc
        except FileNotFoundError:
            return False

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
