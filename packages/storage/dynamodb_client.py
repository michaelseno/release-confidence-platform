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
                preserve_client_error_codes={"ConditionalCheckFailedException"},
                Item=sanitize(item),
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise DuplicateRunIdError() from exc
            raise _storage_error_from_dynamodb_client_error(exc, operation="put_item") from exc

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
