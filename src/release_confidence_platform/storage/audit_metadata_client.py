"""DynamoDB audit metadata repository for Phase 3 lifecycle/scheduling."""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.audit_lifecycle.exceptions import LifecycleConflictError
from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.core.time import utc_now_iso
from release_confidence_platform.sanitization.sanitizer import sanitize


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

    def list_audits_for_client(
        self, client_id: str, *, limit: int, exclusive_start_key: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """List audit metadata records for a client using a bounded DynamoDB query."""

        kwargs: dict[str, Any] = {
            "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
            "ExpressionAttributeValues": {
                ":pk": f"CLIENT#{client_id}",
                ":sk_prefix": "AUDIT#",
            },
            "Limit": limit,
        }
        if exclusive_start_key:
            kwargs["ExclusiveStartKey"] = exclusive_start_key
        try:
            response = self._call("query", **kwargs)
        except Exception as exc:
            raise StorageError("DynamoDB audit query failed", "STORAGE_ERROR") from exc
        return {
            "items": response.get("Items", []),
            "last_evaluated_key": response.get("LastEvaluatedKey"),
        }

    def list_clients_from_registry(
        self, *, limit: int, exclusive_start_key: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Return registry-backed clients if a registry/index exists.

        No registry or client index exists in the current repository schema, so callers should use
        the documented temporary bounded scan fallback.
        """

        return None

    def scan_clients_bounded(
        self,
        *,
        limit: int,
        exclusive_start_key: dict[str, Any] | None = None,
        max_items: int = 1000,
    ) -> dict[str, Any]:
        """Temporary bounded scan fallback for client discovery.

        This intentionally reads only safe metadata fields and stops once enough unique clients are
        collected or the hard read guard is reached. Replace with a client registry/index when one
        is available.
        """

        clients: dict[str, dict[str, Any]] = {}
        read_count = 0
        last_key = exclusive_start_key
        while len(clients) < limit and read_count < max_items:
            page_limit = min(limit - len(clients), max_items - read_count)
            if page_limit <= 0:
                break
            kwargs: dict[str, Any] = {
                "Limit": page_limit,
                "ProjectionExpression": (
                    "PK, SK, client_id, client_name, created_at, updated_at, lifecycle_state"
                ),
            }
            if last_key:
                kwargs["ExclusiveStartKey"] = last_key
            try:
                response = self._call("scan", **kwargs)
            except Exception as exc:
                raise StorageError("DynamoDB client scan failed", "STORAGE_ERROR") from exc
            items = response.get("Items", [])
            read_count += len(items)
            for item in items:
                client_id = _client_id_from_item(item)
                if not client_id:
                    continue
                current = clients.setdefault(
                    client_id,
                    {"client_id": client_id, "active_audit_count": 0},
                )
                current["active_audit_count"] = current.get("active_audit_count", 0) + 1
                for field in ("client_name", "created_at", "updated_at"):
                    value = item.get(field)
                    if value is not None and current.get(field) is None:
                        current[field] = value
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
        return {"items": list(clients.values())[:limit], "last_evaluated_key": last_key}

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


def _client_id_from_item(item: dict[str, Any]) -> str | None:
    value = _ddb_scalar(item.get("client_id"))
    if isinstance(value, str) and value:
        return value
    pk = _ddb_scalar(item.get("PK"))
    if isinstance(pk, str) and pk.startswith("CLIENT#"):
        return pk.removeprefix("CLIENT#")
    return None


def _ddb_scalar(value: Any) -> Any:
    if isinstance(value, dict) and set(value) & {"S", "N", "BOOL"}:
        return value.get("S") or value.get("N") or value.get("BOOL")
    return value
