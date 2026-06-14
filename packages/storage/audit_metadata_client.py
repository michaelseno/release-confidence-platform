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

    def aggregation_job_keys(self, client_id: str, audit_id: str, job_id: str) -> dict[str, str]:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#AGGJOB#{job_id}"}

    def put_aggregation_job_intent_once(self, item: dict[str, Any]) -> None:
        self._put_conditional(
            item,
            error=StorageError("Aggregation job intent exists", "AGGREGATION_JOB_INTENT_EXISTS"),
        )

    def update_aggregation_job_intent(self, key: dict[str, str], updates: dict[str, Any]) -> None:
        self.update_occurrence(key, updates)

    def get_audit_metadata(self, client_id: str, audit_id: str) -> dict[str, Any]:
        response = self._call("get_item", Key=self.audit_keys(client_id, audit_id))
        if "Item" not in response:
            raise StorageError("Audit metadata not found", "AUDIT_NOT_FOUND")
        return response["Item"]

    def list_run_records(self, client_id: str, audit_id: str) -> list[dict[str, Any]]:
        """Query all RUN child records for the audit.

        Uses a KeyConditionExpression with begins_with on the SK so that only
        AUDIT#{audit_id}#RUN#* items are returned.  Follows LastEvaluatedKey
        pagination to return the complete result set.
        """
        pk_value = f"CLIENT#{client_id}"
        sk_prefix = f"AUDIT#{audit_id}#RUN#"
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
            "ExpressionAttributeValues": {":pk": pk_value, ":sk_prefix": sk_prefix},
        }
        while True:
            response = self._call("query", **kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return items

    def put_audit_metadata_once(self, item: dict[str, Any]) -> None:
        item = sanitize(item)
        self._put_conditional(item, error=StorageError("Audit metadata exists", "AUDIT_EXISTS"))

    def update_for_force_recreate(self, item: dict[str, Any]) -> None:
        item = sanitize(item)
        key = self.audit_keys(item["client_id"], item["audit_id"])
        history_entry = item.pop("force_history_entry")
        values = {
            ":draft": "DRAFT",
            ":failed": "FAILED",
            ":next_state": item["lifecycle_state"],
            ":updated_at": item["updated_at"],
            ":empty": [],
            ":entry": [sanitize(history_entry)],
        }
        names: dict[str, str] = {}
        assignments = ["lifecycle_state = :next_state", "updated_at = :updated_at"]
        for index, field in enumerate(
            (
                "config_hash",
                "config_version",
                "config_s3_keys",
                "audit_window",
                "execution_environment",
                "operational_caps",
            )
        ):
            if field in item:
                name = f"#force{index}"
                val = f":force{index}"
                names[name] = field
                values[val] = item[field]
                assignments.append(f"{name} = {val}")
        assignments.append(
            "lifecycle_history = list_append(if_not_exists(lifecycle_history, :empty), :entry)"
        )
        kwargs = {
            "Key": key,
            "UpdateExpression": "SET " + ", ".join(assignments),
            "ExpressionAttributeValues": values,
            "ConditionExpression": "lifecycle_state IN (:draft, :failed)",
        }
        if names:
            kwargs["ExpressionAttributeNames"] = names
        try:
            self._call("update_item", **kwargs)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise StorageError(
                    "Audit lifecycle is not eligible for force recreate", "FORCE_RECREATE_BLOCKED"
                ) from exc
            raise StorageError("Force recreate metadata update failed", "STORAGE_ERROR") from exc

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
