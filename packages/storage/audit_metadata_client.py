"""DynamoDB audit metadata repository for Phase 3 lifecycle/scheduling."""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from packages.audit_lifecycle.exceptions import LifecycleConflictError
from packages.core.exceptions import StorageError
from packages.core.time import utc_now_iso
from packages.sanitization.sanitizer import sanitize


class DuplicateOccurrenceClaimError(StorageError):
    def __init__(self, message: str = "Duplicate schedule occurrence"):
        super().__init__(message, "DUPLICATE_SCHEDULE_OCCURRENCE")


class AuditMetadataRepository:
    def __init__(self, table_name: str, dynamodb_client: Any):
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client

    def audit_keys(self, client_id: str, audit_id: str) -> dict[str, str]:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}"}

    def occurrence_keys(
        self, client_id: str, audit_id: str, schedule_occurrence_id: str
    ) -> dict[str, str]:
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": f"AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}",
        }

    def get_audit_metadata(self, client_id: str, audit_id: str) -> dict[str, Any]:
        response = self._call("get_item", Key=self.audit_keys(client_id, audit_id))
        if "Item" not in response:
            raise StorageError("Audit metadata not found", "AUDIT_NOT_FOUND")
        return response["Item"]

    def put_audit_metadata_once(self, item: dict[str, Any]) -> None:
        item = sanitize(item)
        self._put_conditional(item, error=StorageError("Audit metadata exists", "AUDIT_EXISTS"))

    def append_lifecycle_transition(
        self,
        *,
        client_id: str,
        audit_id: str,
        expected_current_state: str,
        next_state: str,
        history_entry: dict[str, Any],
    ) -> None:
        key = self.audit_keys(client_id, audit_id)
        try:
            self._call(
                "update_item",
                Key=key,
                UpdateExpression=(
                    "SET lifecycle_state = :next_state, updated_at = :updated_at, "
                    "lifecycle_history = list_append("
                    "if_not_exists(lifecycle_history, :empty), :entry)"
                ),
                ConditionExpression="lifecycle_state = :expected_state",
                ExpressionAttributeValues={
                    ":next_state": next_state,
                    ":updated_at": utc_now_iso(),
                    ":empty": [],
                    ":entry": [sanitize(history_entry)],
                    ":expected_state": expected_current_state,
                },
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise LifecycleConflictError() from exc
            raise StorageError("Lifecycle transition update failed", "STORAGE_ERROR") from exc

    def set_schedules(self, client_id: str, audit_id: str, schedules: list[dict[str, Any]]) -> None:
        self._set_fields(client_id, audit_id, {"schedules": sanitize(schedules)})

    def update_execution_counters(
        self, client_id: str, audit_id: str, updates: dict[str, Any]
    ) -> None:
        self._set_fields(client_id, audit_id, {"execution_counters": sanitize(updates)})

    def record_finalization(self, client_id: str, audit_id: str, metadata: dict[str, Any]) -> None:
        self._set_fields(client_id, audit_id, {"finalization": sanitize(metadata)})

    def record_cleanup_errors(
        self, client_id: str, audit_id: str, cleanup_errors: list[dict[str, Any]]
    ) -> None:
        self._set_fields(client_id, audit_id, {"cleanup_errors": sanitize(cleanup_errors)})

    def claim_occurrence(self, item: dict[str, Any]) -> None:
        self._put_conditional(item, error=DuplicateOccurrenceClaimError())

    def update_occurrence(self, key: dict[str, str], updates: dict[str, Any]) -> None:
        assignments = []
        values = {}
        names = {}
        for index, (field, value) in enumerate(sanitize(updates).items()):
            name = f"#f{index}"
            val = f":v{index}"
            names[name] = field
            values[val] = value
            assignments.append(f"{name} = {val}")
        self._call(
            "update_item",
            Key=key,
            UpdateExpression="SET " + ", ".join(assignments),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(PK) AND attribute_exists(SK)",
        )

    def _set_fields(self, client_id: str, audit_id: str, fields: dict[str, Any]) -> None:
        assignments = []
        values = {":updated_at": utc_now_iso()}
        names = {}
        for index, (field, value) in enumerate(fields.items()):
            name = f"#f{index}"
            val = f":v{index}"
            names[name] = field
            values[val] = value
            assignments.append(f"{name} = {val}")
        assignments.append("updated_at = :updated_at")
        self._call(
            "update_item",
            Key=self.audit_keys(client_id, audit_id),
            UpdateExpression="SET " + ", ".join(assignments),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(PK) AND attribute_exists(SK)",
        )

    def _put_conditional(self, item: dict[str, Any], *, error: Exception) -> None:
        try:
            self._call(
                "put_item",
                Item=sanitize(item),
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise error from exc
            raise StorageError("DynamoDB put failed", "STORAGE_ERROR") from exc

    def _call(self, method_name: str, **kwargs: Any) -> dict[str, Any]:
        method = getattr(self.dynamodb_client, method_name)
        try:
            return method(TableName=self.table_name, **kwargs)
        except TypeError:
            return method(**kwargs)
