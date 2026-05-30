"""Mockable EventBridge Scheduler wrapper boundary."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError, ParamValidationError

from packages.core.exceptions import StorageError
from packages.sanitization.sanitizer import sanitize

_SENSITIVE_PROVIDER_DETAIL_PATTERN = re.compile(
    r"\b(authorization|auth|cookie|api[_-]?key|apikey|password|passwd|secret|token)\b"
    r"\s*[:=]\s*([^\s;,]+)",
    re.IGNORECASE,
)
_PROVIDER_BEARER_PATTERN = re.compile(r"\bBearer\s+[^\s;,]+", re.IGNORECASE)


class EventBridgeSchedulerClient:
    def __init__(
        self,
        scheduler_client: Any,
        *,
        target_arn: str | None = None,
        target_arns: Mapping[str, str] | None = None,
        role_arn: str | None = None,
        group_name: str | None = None,
    ):
        self.scheduler_client = scheduler_client
        self.target_arn = target_arn
        self.target_arns = dict(target_arns or {})
        self.role_arn = role_arn
        self.group_name = group_name

    def create_schedule(self, definition: Any) -> dict[str, Any]:
        payload = {
            "Name": definition.name,
            "ScheduleExpression": definition.expression,
            "FlexibleTimeWindow": {"Mode": "OFF"},
        }
        if self.group_name:
            payload["GroupName"] = self.group_name
        schedule_expression_timezone = _schedule_expression_timezone(definition)
        if schedule_expression_timezone:
            payload["ScheduleExpressionTimezone"] = schedule_expression_timezone
        target_arn = self._target_arn_for(definition)
        if target_arn and self.role_arn:
            payload["Target"] = {
                "Arn": target_arn,
                "RoleArn": self.role_arn,
                "Input": json.dumps(sanitize(definition.target_payload), sort_keys=True),
            }
        request_shape = _create_schedule_request_shape(payload)
        try:
            self._call("create_schedule", **payload)
            return sanitize(
                {**definition.metadata, "schedule_group": self.group_name, "status": "created"}
            )
        except (ParamValidationError, BotoCoreError, ClientError) as exc:
            _raise_scheduler_error(
                "create_schedule", exc, "Schedule creation failed", request_shape=request_shape
            )

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
        except (ParamValidationError, BotoCoreError, ClientError) as exc:
            _raise_scheduler_error("get_schedule", exc, "Schedule lookup failed")

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
        except (ParamValidationError, BotoCoreError, ClientError) as exc:
            _raise_scheduler_error(method_name, exc, "Schedule cleanup failed")

    def _call(self, method_name: str, **kwargs: Any) -> dict[str, Any]:
        method = getattr(self.scheduler_client, method_name)
        return method(**kwargs)

    def _target_arn_for(self, definition: Any) -> str | None:
        schedule_type = getattr(definition, "schedule_type", None)
        if schedule_type and schedule_type in self.target_arns:
            return self.target_arns[schedule_type]
        return self.target_arn


def _schedule_expression_timezone(definition: Any) -> str | None:
    value = getattr(definition, "schedule_expression_timezone", None)
    if value:
        return str(value)
    metadata = getattr(definition, "metadata", None)
    if isinstance(metadata, Mapping) and metadata.get("schedule_expression_timezone"):
        return str(metadata["schedule_expression_timezone"])
    return None


def _raise_scheduler_error(
    operation: str,
    exc: Exception,
    default_message: str,
    *,
    request_shape: Mapping[str, Any] | None = None,
) -> None:
    """Map Scheduler AWS boundary errors to sanitized project errors."""

    if isinstance(exc, ParamValidationError):
        raise StorageError(
            f"EventBridge Scheduler request validation failed (operation={operation})",
            "SCHEDULE_REQUEST_VALIDATION_ERROR",
        ) from exc
    if isinstance(exc, ClientError):
        aws_code = str(exc.response.get("Error", {}).get("Code") or "Unknown")
        if aws_code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}:
            raise StorageError(
                "EventBridge Scheduler permission denied "
                f"(operation={operation}, aws_error_code={aws_code})",
                "SCHEDULE_PERMISSION_ERROR",
            ) from exc
        if aws_code in {"ResourceNotFoundException", "ResourceNotFound", "NotFoundException"}:
            detail = _scheduler_config_error_detail(exc, request_shape)
            raise StorageError(
                "EventBridge Scheduler resource not found; verify scheduler group, target ARNs, "
                f"and role ARN (operation={operation}, aws_error_code={aws_code}{detail})",
                "SCHEDULE_CONFIG_ERROR",
            ) from exc
        if aws_code in {"ValidationException", "InvalidParameterValue", "ConflictException"}:
            detail = _scheduler_config_error_detail(exc, request_shape)
            raise StorageError(
                "EventBridge Scheduler rejected the request; verify scheduler stage configuration "
                f"(operation={operation}, aws_error_code={aws_code}{detail})",
                "SCHEDULE_CONFIG_ERROR",
            ) from exc
        raise StorageError(
            f"{default_message} (operation={operation}, aws_error_code={aws_code})",
            "SCHEDULE_CREATE_FAILED"
            if operation == "create_schedule"
            else "SCHEDULE_PROVIDER_ERROR",
        ) from exc
    raise StorageError(
        f"EventBridge Scheduler provider failure (operation={operation})",
        "SCHEDULE_PROVIDER_ERROR",
    ) from exc


def _scheduler_config_error_detail(
    exc: ClientError, request_shape: Mapping[str, Any] | None
) -> str:
    parts: list[str] = []
    provider_message = _sanitized_provider_message(exc)
    if provider_message:
        parts.append(f"provider_message={provider_message}")
    if request_shape is not None:
        parts.append(f"request_shape={_request_shape_json(request_shape)}")
    return ", " + ", ".join(parts) if parts else ""


def _sanitized_provider_message(exc: ClientError) -> str | None:
    raw_message = exc.response.get("Error", {}).get("Message")
    if not raw_message:
        return None
    sanitized = str(sanitize(str(raw_message)))
    sanitized = _PROVIDER_BEARER_PATTERN.sub("[REDACTED]", sanitized)
    return _SENSITIVE_PROVIDER_DETAIL_PATTERN.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", sanitized
    )


def _request_shape_json(request_shape: Mapping[str, Any]) -> str:
    return json.dumps(sanitize(dict(request_shape)), sort_keys=True, default=str)


def _create_schedule_request_shape(payload: Mapping[str, Any]) -> dict[str, Any]:
    target = payload.get("Target") if isinstance(payload.get("Target"), Mapping) else {}
    return {
        "operation": "create_schedule",
        "schedule_name": payload.get("Name"),
        "group_name": payload.get("GroupName"),
        "schedule_expression": payload.get("ScheduleExpression"),
        "schedule_expression_timezone": payload.get("ScheduleExpressionTimezone"),
        "start_date": payload.get("StartDate"),
        "end_date": payload.get("EndDate"),
        "target_arn": target.get("Arn"),
        "role_arn": target.get("RoleArn"),
        "input_keys": _target_input_keys(target.get("Input")),
    }


def _target_input_keys(target_input: Any) -> list[str]:
    if not isinstance(target_input, str):
        return []
    try:
        parsed = json.loads(target_input)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, Mapping):
        return []
    return sorted(str(key) for key in parsed.keys())
