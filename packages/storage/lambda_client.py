"""Mockable Lambda invocation wrapper."""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from botocore.exceptions import ClientError

from packages.core.exceptions import StorageError
from packages.sanitization.sanitizer import sanitize


class LambdaInvocationClient:
    def __init__(self, lambda_client: Any):
        self.lambda_client = lambda_client

    def invoke(
        self, *, function_name: str, payload: dict[str, Any], invocation_type: str = "Event"
    ) -> dict[str, Any]:
        try:
            response = self.lambda_client.invoke(
                FunctionName=function_name,
                InvocationType=invocation_type,
                Payload=json.dumps(sanitize(payload)).encode("utf-8"),
            )
        except ClientError as exc:
            raise _storage_error_from_lambda_client_error(
                exc, function_name=function_name, invocation_type=invocation_type
            ) from exc
        except Exception as exc:
            raise StorageError("Lambda invocation failed", "LAMBDA_INVOCATION_FAILED") from exc
        diagnostic_error = _storage_error_from_lambda_invoke_response(
            response, function_name=function_name, invocation_type=invocation_type
        )
        if diagnostic_error is not None:
            raise diagnostic_error
        result = {
            "status_code": response.get("StatusCode"),
            "function_name": function_name,
            "invocation_type": invocation_type,
            "accepted_async_invocation": invocation_type == "Event"
            and response.get("StatusCode") == 202,
            "note": "Async Lambda invocation acceptance does not guarantee handler success"
            if invocation_type == "Event"
            else None,
        }
        if invocation_type == "RequestResponse":
            handler_payload = _safe_lambda_handler_payload(response.get("Payload"))
            handler_status = (
                handler_payload.get("status") if isinstance(handler_payload, dict) else None
            )
            result.update(
                {
                    "accepted_async_invocation": False,
                    "handler_response": handler_payload,
                    "handler_status": handler_status,
                    "handler_succeeded": isinstance(handler_status, str)
                    and handler_status.upper() == "COMPLETED",
                    "note": "Synchronous Lambda invocation includes sanitized handler response",
                }
            )
        return sanitize(result)


_FUNCTION_NOT_FOUND_CODES = {"ResourceNotFoundException"}
_PERMISSION_CODES = {"AccessDeniedException", "AccessDenied", "Forbidden"}
_SAFE_ERROR_CODE_PATTERN = re.compile(r"[^A-Za-z0-9_.:-]")
_SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"\b(token|secret|password|passwd|api[_-]?key|credential)=([^\s,;\}\]]+)",
    re.IGNORECASE,
)
_IMPORT_FAILURE_MARKERS = ("Runtime.ImportModuleError", "No module named")


def _storage_error_from_lambda_client_error(
    exc: ClientError, *, function_name: str, invocation_type: str
) -> StorageError:
    aws_code = _safe_aws_error_code(exc)
    safe_function_name = _safe_function_name(function_name)
    safe_invocation_type = _safe_context_value(invocation_type)
    context = (
        f"aws_error_code={aws_code}; operation=invoke; "
        f"function_name={safe_function_name}; invocation_type={safe_invocation_type}"
    )
    if aws_code in _FUNCTION_NOT_FOUND_CODES:
        return StorageError(
            f"Lambda orchestrator function not found for stage ({context})",
            "LAMBDA_CONFIG_ERROR",
        )
    if aws_code in _PERMISSION_CODES:
        return StorageError(
            "Lambda orchestrator invoke permission denied "
            f"({context}; required_permission=lambda:InvokeFunction)",
            "LAMBDA_PERMISSION_ERROR",
        )
    safe_message = _safe_aws_error_message(exc)
    message_context = f"{context}; aws_error_message={safe_message}" if safe_message else context
    return StorageError(
        f"Lambda invocation failed ({message_context})",
        "LAMBDA_INVOCATION_FAILED",
    )


def _storage_error_from_lambda_invoke_response(
    response: dict[str, Any], *, function_name: str, invocation_type: str
) -> StorageError | None:
    function_error = response.get("FunctionError")
    if not function_error:
        return None

    safe_function_name = _safe_function_name(function_name)
    safe_invocation_type = _safe_context_value(invocation_type)
    safe_function_error = _safe_context_value(str(function_error))
    details = _safe_lambda_runtime_details(response)
    context = (
        f"operation=invoke; function_name={safe_function_name}; "
        f"invocation_type={safe_invocation_type}; function_error={safe_function_error}"
    )
    if details:
        context = f"{context}; runtime_error={details}"

    if any(marker in details for marker in _IMPORT_FAILURE_MARKERS):
        return StorageError(
            "Lambda runtime dependency/import failure detected "
            f"({context}; redeploy_with_packaged_backend_dependencies=true)",
            "LAMBDA_DEPENDENCY_IMPORT_ERROR",
        )

    return StorageError(
        f"Lambda runtime execution failed ({context})",
        "LAMBDA_RUNTIME_ERROR",
    )


def _safe_lambda_runtime_details(response: dict[str, Any]) -> str:
    detail_parts: list[str] = []
    payload_text = _read_lambda_payload_text(response.get("Payload"))
    if payload_text:
        detail_parts.append(payload_text)

    log_result = response.get("LogResult")
    if log_result:
        try:
            decoded_log = base64.b64decode(str(log_result)).decode("utf-8", errors="replace")
        except Exception:
            decoded_log = ""
        if decoded_log:
            detail_parts.append(decoded_log)

    if not detail_parts:
        return ""
    sanitized = str(sanitize(" | ".join(detail_parts))).replace("\n", " ").replace("\r", " ")
    sanitized = _SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\1=[REDACTED]", sanitized)
    return sanitized[:360]


def _read_lambda_payload_text(payload: Any) -> str:
    if payload is None:
        return ""
    try:
        raw_payload = payload.read() if hasattr(payload, "read") else payload
    except Exception:
        return ""
    if isinstance(raw_payload, bytes):
        return raw_payload.decode("utf-8", errors="replace")
    return str(raw_payload)


def _safe_lambda_handler_payload(payload: Any) -> dict[str, Any] | str | None:
    payload_text = _read_lambda_payload_text(payload)
    if not payload_text:
        return None
    try:
        decoded = json.loads(payload_text)
    except json.JSONDecodeError:
        decoded = payload_text
    safe_payload = sanitize(decoded)
    if isinstance(safe_payload, str):
        safe_payload = safe_payload.replace("\n", " ").replace("\r", " ")[:720]
    return safe_payload


def _safe_aws_error_code(exc: ClientError) -> str:
    code = str(exc.response.get("Error", {}).get("Code") or "Unknown")
    sanitized = _SAFE_ERROR_CODE_PATTERN.sub("", code)
    return sanitized[:80] or "Unknown"


def _safe_aws_error_message(exc: ClientError) -> str:
    message = str(exc.response.get("Error", {}).get("Message") or "")
    if not message:
        return ""
    sanitized = str(sanitize(message)).replace("\n", " ").replace("\r", " ")
    return sanitized[:180]


def _safe_function_name(function_name: str) -> str:
    return _safe_context_value(function_name, limit=180)


def _safe_context_value(value: str, *, limit: int = 80) -> str:
    sanitized = str(sanitize(value)).replace("\n", " ").replace("\r", " ").strip()
    return sanitized[:limit] or "<empty>"
