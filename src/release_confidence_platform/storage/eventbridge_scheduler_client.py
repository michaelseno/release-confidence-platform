"""Mockable EventBridge Scheduler wrapper boundary."""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.sanitization.sanitizer import sanitize


class EventBridgeSchedulerClient:
    def __init__(
        self,
        scheduler_client: Any,
        *,
        target_arn: str | None = None,
        role_arn: str | None = None,
        group_name: str | None = None,
    ):
        self.scheduler_client = scheduler_client
        self.target_arn = target_arn
        self.role_arn = role_arn
        self.group_name = group_name

    def create_schedule(self, definition: Any) -> dict[str, Any]:
        try:
            payload = {
                "Name": definition.name,
                "ScheduleExpression": definition.expression,
                "FlexibleTimeWindow": {"Mode": "OFF"},
            }
            if self.group_name:
                payload["GroupName"] = self.group_name
            if self.target_arn and self.role_arn:
                payload["Target"] = {
                    "Arn": self.target_arn,
                    "RoleArn": self.role_arn,
                    "Input": sanitize(definition.target_payload),
                }
            self._call("create_schedule", **payload)
            return sanitize(
                {**definition.metadata, "schedule_group": self.group_name, "status": "created"}
            )
        except ClientError as exc:
            raise StorageError("Schedule creation failed", "SCHEDULE_CREATE_FAILED") from exc

    def delete_schedule(self, schedule_name: str, group_name: str | None = None) -> dict[str, Any]:
        return self._cleanup("delete_schedule", schedule_name, group_name, "deleted")

    def disable_schedule(self, schedule_name: str, group_name: str | None = None) -> dict[str, Any]:
        return self._cleanup(
            "update_schedule", schedule_name, group_name, "disabled", State="DISABLED"
        )

    def get_schedule(self, schedule_name: str, group_name: str | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"Name": schedule_name}
        if group_name:
            kwargs["GroupName"] = group_name
        try:
            return sanitize(self._call("get_schedule", **kwargs))
        except ClientError as exc:
            raise StorageError("Schedule lookup failed", "SCHEDULE_LOOKUP_FAILED") from exc

    def _cleanup(
        self,
        method_name: str,
        schedule_name: str,
        group_name: str | None,
        status: str,
        **extra: Any,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"Name": schedule_name, **extra}
        if group_name:
            kwargs["GroupName"] = group_name
        try:
            self._call(method_name, **kwargs)
            return {"schedule_name": schedule_name, "status": status}
        except ClientError as exc:
            raise StorageError("Schedule cleanup failed", "SCHEDULE_CLEANUP_FAILED") from exc

    def _call(self, method_name: str, **kwargs: Any) -> dict[str, Any]:
        method = getattr(self.scheduler_client, method_name)
        return method(**kwargs)
