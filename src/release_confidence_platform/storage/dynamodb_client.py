"""Lightweight DynamoDB run metadata wrapper."""

from __future__ import annotations

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError, ParamValidationError

from release_confidence_platform.core.constants.engine import RUN_STATUSES
from release_confidence_platform.core.exceptions import DuplicateRunIdError, StorageError
from release_confidence_platform.storage.dynamodb_codec import (
    decode_dynamodb_response,
    encode_dynamodb_call_kwargs,
    storage_error_from_dynamodb_client_error,
    storage_error_from_dynamodb_request_error,
)


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
                Item=item,
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
        encoded_kwargs = encode_dynamodb_call_kwargs(kwargs)
        try:
            return decode_dynamodb_response(method(TableName=self.table_name, **encoded_kwargs))
        except TypeError:
            return decode_dynamodb_response(method(**kwargs))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in (preserve_client_error_codes or set()):
                raise
            raise storage_error_from_dynamodb_client_error(exc, operation=method_name) from exc
        except (ParamValidationError, BotoCoreError) as exc:
            raise storage_error_from_dynamodb_request_error(exc, operation=method_name) from exc
