"""Helpers for low-level DynamoDB client request/response shapes."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import BotoCoreError, ClientError, ParamValidationError

from packages.core.exceptions import StorageError
from packages.sanitization.sanitizer import sanitize

_SERIALIZER = TypeSerializer()
_DESERIALIZER = TypeDeserializer()
_ATTRIBUTE_VALUE_KEYS = {"S", "N", "B", "SS", "NS", "BS", "M", "L", "NULL", "BOOL"}
_SAFE_ERROR_CODE_PATTERN = re.compile(r"[^A-Za-z0-9_.:-]")
_MISSING_TABLE_CODES = {"ResourceNotFoundException"}
_PERMISSION_CODES = {
    "AccessDenied",
    "AccessDeniedException",
    "UnauthorizedOperation",
    "UnrecognizedClientException",
}


def encode_dynamodb_call_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Encode plain-Python data fields required by low-level DynamoDB clients."""

    encoded = dict(kwargs)
    if "Key" in encoded:
        encoded["Key"] = encode_item(encoded["Key"])
    if "Item" in encoded:
        encoded["Item"] = encode_item(encoded["Item"])
    if "ExpressionAttributeValues" in encoded:
        expression_values = encoded["ExpressionAttributeValues"]
        encoded["ExpressionAttributeValues"] = {
            name: encode_value(value) for name, value in expression_values.items()
        }
    if "ExclusiveStartKey" in encoded:
        encoded["ExclusiveStartKey"] = encode_item(encoded["ExclusiveStartKey"])
    return encoded


def decode_dynamodb_response(response: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(response)
    if "Item" in decoded:
        decoded["Item"] = decode_item(decoded["Item"])
    if "Items" in decoded:
        decoded["Items"] = [decode_item(item) for item in decoded["Items"]]
    return decoded


def encode_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: encode_value(value) for key, value in item.items()}


def encode_value(value: Any) -> dict[str, Any]:
    if _is_attribute_value(value):
        return value
    return _SERIALIZER.serialize(_coerce_for_dynamodb(value))


def decode_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: decode_value(value) for key, value in item.items()}


def decode_value(value: Any) -> Any:
    if not _is_attribute_value(value):
        return value
    decoded = _DESERIALIZER.deserialize(value)
    return _decimal_to_json_compatible(decoded)


def storage_error_from_dynamodb_client_error(exc: ClientError, *, operation: str) -> StorageError:
    aws_code = safe_aws_error_code(exc)
    context = f"aws_error_code={aws_code}; operation={operation}"
    if aws_code in _MISSING_TABLE_CODES:
        return StorageError(
            "DynamoDB audit metadata table not found "
            f"({context}; check config/stages/<stage>.json audit_metadata_table or "
            "export RCP_AUDIT_METADATA_TABLE=<real-metadata-table>)",
            "STORAGE_CONFIG_ERROR",
        )
    if aws_code in _PERMISSION_CODES:
        return StorageError(
            "DynamoDB audit metadata permission denied "
            f"({context}; required_permissions=dynamodb:GetItem,dynamodb:PutItem,"
            "dynamodb:UpdateItem,dynamodb:Query,dynamodb:Scan)",
            "STORAGE_PERMISSION_ERROR",
        )
    safe_message = safe_aws_error_message(exc)
    message_context = f"{context}; aws_error_message={safe_message}" if safe_message else context
    return StorageError(f"DynamoDB metadata operation failed ({message_context})", "STORAGE_ERROR")


def storage_error_from_dynamodb_request_error(exc: Exception, *, operation: str) -> StorageError:
    if isinstance(exc, ParamValidationError):
        return StorageError(
            "DynamoDB request shape validation failed "
            f"(operation={operation}; check metadata serialization and table configuration)",
            "STORAGE_CONFIG_ERROR",
        )
    if isinstance(exc, BotoCoreError):
        return StorageError(
            f"DynamoDB client request failed (operation={operation})", "STORAGE_ERROR"
        )
    return StorageError(
        f"DynamoDB metadata operation failed (operation={operation})", "STORAGE_ERROR"
    )


def safe_aws_error_code(exc: ClientError) -> str:
    code = str(exc.response.get("Error", {}).get("Code") or "Unknown")
    sanitized = _SAFE_ERROR_CODE_PATTERN.sub("", code)
    return sanitized[:80] or "Unknown"


def safe_aws_error_message(exc: ClientError) -> str:
    message = str(exc.response.get("Error", {}).get("Message") or "")
    if not message:
        return ""
    sanitized = str(sanitize(message)).replace("\n", " ").replace("\r", " ")
    return sanitized[:180]


def _is_attribute_value(value: Any) -> bool:
    return (
        isinstance(value, dict) and len(value) == 1 and next(iter(value)) in _ATTRIBUTE_VALUE_KEYS
    )


def _coerce_for_dynamodb(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _coerce_for_dynamodb(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_coerce_for_dynamodb(item) for item in value]
    return value


def _decimal_to_json_compatible(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: _decimal_to_json_compatible(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decimal_to_json_compatible(item) for item in value]
    if isinstance(value, set):
        return [_decimal_to_json_compatible(item) for item in value]
    return value
