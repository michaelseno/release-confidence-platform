"""Secrets Manager-only secret resolver."""

from __future__ import annotations

from typing import Any

from packages.core.exceptions import SecretError


class SecretsManagerClient:
    def __init__(self, secrets_client: Any):
        self.secrets_client = secrets_client

    def resolve(self, secret_reference: dict[str, str]) -> str:
        if not isinstance(secret_reference, dict) or not secret_reference.get("secret_ref"):
            raise SecretError("Invalid secret reference", "SECRET_ERROR")
        try:
            response = self.secrets_client.get_secret_value(SecretId=secret_reference["secret_ref"])
            if "SecretString" in response:
                return response["SecretString"]
        except Exception as exc:
            raise SecretError("Secret resolution failed", "SECRET_ERROR") from exc
        raise SecretError("Secret value is unsupported", "SECRET_ERROR")
