"""DynamoDB-backed Phase 4 aggregation repository."""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.sanitization.sanitizer import sanitize
from release_confidence_platform.storage.dynamodb_codec import (
    decode_dynamodb_response,
    encode_dynamodb_call_kwargs,
    storage_error_from_dynamodb_client_error,
    storage_error_from_dynamodb_request_error,
)


class ConditionalWriteError(StorageError):
    def __init__(self, message: str = "Conditional write failed"):
        super().__init__(message, "CONDITIONAL_WRITE_FAILED")


class AggregationRepository:
    def __init__(self, table_name: str, dynamodb_client: Any):
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client

    def audit_keys(self, client_id: str, audit_id: str) -> dict[str, str]:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}"}

    def execution_identity_keys(self, client_id: str, audit_id: str) -> dict[str, str]:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#EXECUTION_ID"}

    def job_keys(self, client_id: str, audit_id: str, job_id: str) -> dict[str, str]:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#AGGJOB#{job_id}"}

    def aggregate_prefix(
        self, client_id: str, audit_id: str, exec_id: str, cfg: str, ver: str
    ) -> str:
        return f"AUDIT#{audit_id}#EXEC#{exec_id}#CFG#{cfg}#AGG#{ver}"

    def get_audit_metadata(self, client_id: str, audit_id: str) -> dict[str, Any]:
        response = self._call("get_item", Key=self.audit_keys(client_id, audit_id))
        if "Item" not in response:
            raise StorageError("Audit metadata not found", "AUDIT_NOT_FOUND")
        return response["Item"]

    def get_audit_execution_identity(self, client_id: str, audit_id: str) -> dict[str, Any] | None:
        return self._call("get_item", Key=self.execution_identity_keys(client_id, audit_id)).get(
            "Item"
        )

    def put_audit_execution_identity_once(self, item: dict[str, Any]) -> None:
        self._put_once(item)

    def put_job_once(self, item: dict[str, Any]) -> None:
        self._put_once(item)

    def update_job(self, key: dict[str, str], updates: dict[str, Any]) -> None:
        names = {f"#f{i}": key for i, key in enumerate(updates)}
        values = {f":v{i}": value for i, value in enumerate(sanitize(updates).values())}
        assignments = ", ".join(f"{name} = :v{i}" for i, name in enumerate(names))
        self._call(
            "update_item",
            Key=key,
            UpdateExpression="SET " + assignments,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(PK) AND attribute_exists(SK)",
        )

    def list_completed_runs(self, client_id: str, audit_id: str) -> list[dict[str, Any]]:
        response = self._call(
            "query",
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
            ExpressionAttributeValues={
                ":pk": f"CLIENT#{client_id}",
                ":sk_prefix": f"AUDIT#{audit_id}#RUN#",
            },
        )
        runs = []
        for item in response.get("Items", []):
            if (
                item.get("status") == "COMPLETED"
                and item.get("raw_result_version") == "v1"
                and item.get("raw_result_s3_key")
            ):
                runs.append(item)
        return sorted(runs, key=lambda item: item.get("SK", ""))

    def aggregate_set_exists(
        self, client_id: str, audit_id: str, exec_id: str, cfg: str, ver: str
    ) -> bool:
        key = {
            "PK": f"CLIENT#{client_id}",
            "SK": f"{self.aggregate_prefix(client_id, audit_id, exec_id, cfg, ver)}#AUDIT",
        }
        return "Item" in self._call("get_item", Key=key)

    def put_records_once(self, records: list[dict[str, Any]]) -> None:
        for item in records:
            self._put_once(item)

    def _put_once(self, item: dict[str, Any]) -> None:
        try:
            self._call(
                "put_item",
                preserve_client_error_codes={"ConditionalCheckFailedException"},
                Item=sanitize(item),
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConditionalWriteError() from exc
            raise

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
            if exc.response.get("Error", {}).get("Code") in (preserve_client_error_codes or set()):
                raise
            raise storage_error_from_dynamodb_client_error(exc, operation=method_name) from exc
        except Exception as exc:
            raise storage_error_from_dynamodb_request_error(exc, operation=method_name) from exc
