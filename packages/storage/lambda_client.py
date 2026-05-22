"""Mockable Lambda invocation wrapper."""

from __future__ import annotations

import json
from typing import Any

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
        except Exception as exc:
            raise StorageError("Lambda invocation failed", "LAMBDA_INVOCATION_FAILED") from exc
        return sanitize({"status_code": response.get("StatusCode"), "function_name": function_name})
