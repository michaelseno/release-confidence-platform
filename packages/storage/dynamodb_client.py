"""Lightweight DynamoDB run metadata wrapper."""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from packages.core.constants.engine import RUN_STATUSES
from packages.core.exceptions import DuplicateRunIdError, StorageError
from packages.sanitization.sanitizer import sanitize


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
        try:
            self._call(
                "put_item",
                Item=sanitize(item),
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise DuplicateRunIdError() from exc
            raise StorageError("DynamoDB put failed", "STORAGE_ERROR") from exc

    def update_terminal(self, key: dict[str, str], updates: dict[str, Any]) -> None:
        if updates.get("status") not in RUN_STATUSES:
            raise StorageError("Invalid run status", "STORAGE_ERROR")
        expression_names = {f"#k{i}": k for i, k in enumerate(updates)}
        expression_values = {f":v{i}": v for i, v in enumerate(sanitize(updates).values())}
        assignments = ", ".join(f"{name} = :v{i}" for i, name in enumerate(expression_names))
        self._call(
            "update_item",
            Key=key,
            UpdateExpression=f"SET {assignments}",
            ExpressionAttributeNames=expression_names,
            ExpressionAttributeValues=expression_values,
            ConditionExpression="attribute_exists(PK) AND attribute_exists(SK)",
        )

    def _call(self, method_name: str, **kwargs: Any) -> dict[str, Any]:
        method = getattr(self.dynamodb_client, method_name)
        try:
            return method(TableName=self.table_name, **kwargs)
        except TypeError:
            return method(**kwargs)
