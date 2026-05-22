"""Shared audit configuration validation for operator/API entry points."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packages.audit_scheduling.safeguards import effective_caps, validate_audit_window
from packages.config.validators import validate_audit_config, validate_endpoint_config
from packages.core.exceptions import ConfigError, ValidationError
from packages.core.validators import validate_identifier

DESTRUCTIVE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class ValidatedAuditConfig:
    client_config: dict[str, Any]
    audit_config: dict[str, Any]
    endpoints_config: dict[str, Any]
    normalized_audit_config: dict[str, Any]
    endpoints: list[dict[str, Any]]
    client_id: str
    audit_id: str
    config_hash: dict[str, str]
    config_version: str | None


def _load_json_file(path: str | Path, label: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{label} JSON is invalid", "CONFIG_LOAD_ERROR") from exc
    except OSError as exc:
        raise ConfigError(f"{label} could not be loaded", "CONFIG_LOAD_ERROR") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _is_production(audit_config: dict[str, Any]) -> bool:
    env = audit_config.get("execution_environment") or {}
    return (
        env.get("target_environment") == "production"
        or audit_config.get("target_environment") == "production"
    )


def _allowed_methods(client_config: dict[str, Any]) -> set[str] | None:
    safety = client_config.get("safety") or client_config.get("safety_config") or {}
    methods = safety.get("allowed_methods") or safety.get("allowed_endpoint_methods")
    if methods is None:
        return None
    if not isinstance(methods, list) or not all(isinstance(method, str) for method in methods):
        raise ConfigError("allowed_methods must be a list of strings", "CONFIG_VALIDATION_ERROR")
    return {method.upper() for method in methods}


def _normalize_audit_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config)
    window = normalized.get("audit_window") or {}
    if "start_at" in window or "end_at" in window:
        normalized["audit_window"] = {
            **window,
            "start_time": window.get("start_time") or window.get("start_at"),
            "end_time": window.get("end_time") or window.get("end_at"),
            "timezone": window.get("timezone") or normalized.get("timezone"),
        }
    if "baseline_schedule" in normalized and "baseline" not in normalized:
        normalized["baseline"] = normalized["baseline_schedule"]
    if "repeated_schedule" in normalized and "repeated" not in normalized:
        repeated = normalized["repeated_schedule"]
        normalized["repeated"] = repeated if isinstance(repeated, list) else [repeated]
    return normalized


class AuditConfigValidationService:
    def validate_files(
        self,
        *,
        client_config_path: str | Path,
        audit_config_path: str | Path,
        endpoints_config_path: str | Path,
        stage: str,
    ) -> ValidatedAuditConfig:
        return self.validate_configs(
            client_config=_load_json_file(client_config_path, "client_config"),
            audit_config=_load_json_file(audit_config_path, "audit_config"),
            endpoints_config=_load_json_file(endpoints_config_path, "endpoints_config"),
            stage=stage,
        )

    def validate_configs(
        self,
        *,
        client_config: dict[str, Any],
        audit_config: dict[str, Any],
        endpoints_config: dict[str, Any],
        stage: str,
    ) -> ValidatedAuditConfig:
        if not isinstance(client_config, dict) or not isinstance(audit_config, dict):
            raise ConfigError("Client and audit configs must be objects", "CONFIG_VALIDATION_ERROR")
        client_id = validate_identifier("client_id", client_config.get("client_id"))
        audit_id = validate_identifier("audit_id", audit_config.get("audit_id"))
        if audit_config.get("client_id") not in (None, client_id):
            raise ConfigError("Audit config client_id mismatch", "CONFIG_VALIDATION_ERROR")
        if isinstance(endpoints_config, dict):
            if endpoints_config.get("client_id") not in (None, client_id):
                raise ConfigError("Endpoint config client_id mismatch", "CONFIG_VALIDATION_ERROR")
            if endpoints_config.get("audit_id") not in (None, audit_id):
                raise ConfigError("Endpoint config audit_id mismatch", "CONFIG_VALIDATION_ERROR")
        validate_audit_config(audit_config, audit_id)
        normalized = _normalize_audit_config(audit_config)
        normalized["client_id"] = client_id
        normalized["audit_id"] = audit_id
        audit_window = validate_audit_window(normalized.get("audit_window"))
        normalized["audit_window"] = audit_window
        endpoints = validate_endpoint_config(endpoints_config)
        allowed_methods = _allowed_methods(client_config)
        execution_env = normalized.get("execution_environment") or {}
        is_prod = stage == "prod" or _is_production(normalized)
        if is_prod and execution_env.get("allow_production_execution") is not True:
            raise ValidationError(
                "Production execution requires explicit allow", "PRODUCTION_BLOCKED"
            )
        effective_caps(execution_env)
        for endpoint in endpoints:
            method = endpoint["method"]
            if allowed_methods is not None and method not in allowed_methods:
                raise ValidationError("Endpoint method is not allowed", "METHOD_NOT_ALLOWED")
            if (
                method in DESTRUCTIVE_METHODS
                and execution_env.get("allow_destructive_operation") is not True
            ):
                raise ValidationError(
                    "Destructive operation requires explicit allow", "DESTRUCTIVE_OPERATION_BLOCKED"
                )
            payload_safety = endpoint.get("payload_safety")
            if not isinstance(payload_safety, dict):
                raise ValidationError("Invalid payload safety", "INVALID_PAYLOAD_SAFETY")
            if (
                payload_safety.get("destructive_operation") is True
                and payload_safety.get("allow_destructive_operation") is not True
            ):
                raise ValidationError(
                    "Destructive operation requires explicit allow", "DESTRUCTIVE_OPERATION_BLOCKED"
                )
            if endpoint.get("auth_required") is True and not endpoint.get("auth_ref"):
                raise ValidationError("auth_ref is required", "AUTH_REF_REQUIRED")
        return ValidatedAuditConfig(
            client_config=client_config,
            audit_config=audit_config,
            endpoints_config=endpoints_config,
            normalized_audit_config=normalized,
            endpoints=endpoints,
            client_id=client_id,
            audit_id=audit_id,
            config_hash={
                "client_config": _hash(client_config),
                "audit_config": _hash(audit_config),
                "endpoints_config": _hash(endpoints_config),
            },
            config_version=audit_config.get("config_version")
            or client_config.get("config_version"),
        )
