"""DynamoDB-backed Phase 4 aggregation repository."""

from __future__ import annotations

import json
from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.aggregation.constants import MAX_AGGREGATE_TRANSACTION_BYTES
from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.sanitization.sanitizer import sanitize
from release_confidence_platform.storage.dynamodb_codec import (
    decode_dynamodb_response,
    encode_dynamodb_call_kwargs,
    encode_item,
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

    def put_lineage_page_once(self, item: dict[str, Any]) -> None:
        self._put_once(item)

    def get_lineage_page(self, key: dict[str, str]) -> dict[str, Any] | None:
        return self._call("get_item", Key=key).get("Item")

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

    def get_job(self, key: dict[str, str]) -> dict[str, Any] | None:
        return self._call("get_item", Key=key).get("Item")

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
        pk = f"CLIENT#{client_id}"
        prefix = self.aggregate_prefix(client_id, audit_id, exec_id, cfg, ver)
        marker = self._call("get_item", Key={"PK": pk, "SK": f"{prefix}#SET"}).get("Item")
        if not marker or marker.get("completion_status") != "COMPLETE":
            return False
        required_sort_keys = [
            f"{prefix}#LINEAGE#audit",
            f"{prefix}#AUDIT",
            f"{prefix}#FAILURE_CLASSIFICATION",
        ]
        endpoint_count = marker.get("endpoint_aggregate_count")
        aggregate_count = marker.get("aggregate_record_count")
        if not isinstance(endpoint_count, int) or not isinstance(aggregate_count, int):
            return False
        found_aggregates = 0
        for sk in required_sort_keys:
            if "Item" not in self._call("get_item", Key={"PK": pk, "SK": sk}):
                return False
            found_aggregates += 1 if not sk.endswith("LINEAGE#audit") else 0
        response = self._call(
            "query",
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
            ExpressionAttributeValues={":pk": pk, ":sk_prefix": f"{prefix}#ENDPOINT#"},
        )
        endpoint_records = [
            item for item in response.get("Items", []) if item.get("record_kind") == "aggregate"
        ]
        endpoint_aggregates = [
            item
            for item in endpoint_records
            if item.get("aggregate_type") == "endpoint"
        ]
        if len(endpoint_aggregates) != endpoint_count:
            return False
        found_aggregates += len(endpoint_records)
        return found_aggregates == aggregate_count

    def put_records_once(self, records: list[dict[str, Any]]) -> None:
        sanitized_records = [sanitize(item) for item in records]
        total_bytes = sum(
            len(json.dumps(item, sort_keys=True, default=str).encode("utf-8"))
            for item in sanitized_records
        )
        if total_bytes > MAX_AGGREGATE_TRANSACTION_BYTES:
            raise StorageError("Aggregate transaction too large", "AGGREGATE_SET_TOO_LARGE")
        transact_items = [
            {
                "Put": {
                    "TableName": self.table_name,
                    "Item": encode_item(item),
                    "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
                }
            }
            for item in sanitized_records
        ]
        try:
            self.dynamodb_client.transact_write_items(TransactItems=transact_items)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {
                "ConditionalCheckFailedException",
                "TransactionCanceledException",
            }:
                raise ConditionalWriteError() from exc
            raise storage_error_from_dynamodb_client_error(
                exc, operation="transact_write_items"
            ) from exc
        except Exception as exc:
            raise storage_error_from_dynamodb_request_error(
                exc, operation="transact_write_items"
            ) from exc

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
