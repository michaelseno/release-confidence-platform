"""Defaults profile resolution, loading, and validation for config init."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from release_confidence_platform.core.exceptions import ConfigError, ValidationError

SUPPORTED_NAMED_PROFILES = {"dev", "staging", "prod"}
SUPPORTED_TARGET_ENVIRONMENTS = {"dev", "staging", "prod", "production"}
SAFE_FALLBACK_OUTPUT_DIR = ".local-configs"
SAFE_FALLBACK_TIMEZONE = "UTC"
SAFE_FALLBACK_OUTPUT = "text"
SECRET_KEY_FRAGMENTS = (
    "password",
    "token",
    "secret",
    "api_key",
    "authorization",
    "cookie",
    "private_key",
)


@dataclass(frozen=True)
class DefaultProfile:
    name: str
    source_path: Path
    data: dict[str, Any]


def load_default_profile(defaults: str | None = None) -> DefaultProfile:
    source_path = resolve_default_profile_path(defaults)
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError("defaults profile JSON is invalid", "CONFIG_LOAD_ERROR") from exc
    except OSError as exc:
        raise ConfigError("defaults profile could not be loaded", "CONFIG_LOAD_ERROR") from exc
    validate_default_profile(raw)
    return DefaultProfile(name=raw["profile_name"], source_path=source_path, data=raw)


def resolve_default_profile_path(defaults: str | None = None) -> Path:
    value = (defaults or "dev").strip()
    if not value:
        raise ValidationError("defaults profile must not be empty", "INVALID_ARGUMENT")
    if _is_path_like(value):
        return Path(value)
    if value not in SUPPORTED_NAMED_PROFILES:
        raise ValidationError("unsupported defaults profile", "INVALID_ARGUMENT")
    cwd_path = Path.cwd() / "config" / "defaults" / f"{value}.json"
    if cwd_path.exists():
        return cwd_path
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config" / "defaults" / f"{value}.json"
        if candidate.exists():
            return candidate
    raise ConfigError("defaults profile could not be loaded", "CONFIG_LOAD_ERROR")


def validate_default_profile(profile: Any) -> None:
    if not isinstance(profile, dict):
        raise ValidationError("defaults profile must be a JSON object", "CONFIG_VALIDATION_ERROR")
    _reject_secret_bearing_fields(profile)
    required = {
        "profile_name",
        "target_environment",
        "operator_defaults",
        "request_defaults",
        "rate_limits",
        "payload_safety",
        "production_safeguards",
        "schedule_defaults",
        "retention_defaults",
    }
    missing = sorted(required - set(profile))
    if missing:
        raise ValidationError("defaults profile missing required fields", "CONFIG_VALIDATION_ERROR")
    if not isinstance(profile["profile_name"], str) or not profile["profile_name"].strip():
        raise ValidationError("defaults profile profile_name is invalid", "CONFIG_VALIDATION_ERROR")
    target_environment = profile["target_environment"]
    if target_environment not in SUPPORTED_TARGET_ENVIRONMENTS:
        raise ValidationError(
            "defaults profile target_environment is invalid", "CONFIG_VALIDATION_ERROR"
        )
    _validate_operator_defaults(profile["operator_defaults"])
    _validate_request_defaults(profile["request_defaults"])
    _validate_rate_limits(profile["rate_limits"])
    _validate_payload_safety(profile["payload_safety"])
    _validate_production_safeguards(profile["production_safeguards"], target_environment)
    _validate_schedule_defaults(profile["schedule_defaults"])
    _validate_retention_defaults(profile["retention_defaults"])
    sample_endpoints = profile.get("sample_endpoints", [])
    if not isinstance(sample_endpoints, list):
        raise ValidationError(
            "defaults profile sample_endpoints must be a list", "CONFIG_VALIDATION_ERROR"
        )


def _is_path_like(value: str) -> bool:
    return "/" in value or "\\" in value or value.endswith(".json")


def _validate_operator_defaults(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValidationError("operator_defaults must be an object", "CONFIG_VALIDATION_ERROR")
    allowed = {"output_dir", "timezone", "output"}
    if set(value) - allowed:
        raise ValidationError(
            "operator_defaults contains unsupported fields", "CONFIG_VALIDATION_ERROR"
        )
    if "output_dir" in value and not isinstance(value["output_dir"], str):
        raise ValidationError(
            "operator_defaults.output_dir must be a string", "CONFIG_VALIDATION_ERROR"
        )
    if "timezone" in value:
        _validate_timezone(value["timezone"], error_type="CONFIG_VALIDATION_ERROR")
    if value.get("output") not in (None, "text", "json"):
        raise ValidationError(
            "operator_defaults.output must be text or json", "CONFIG_VALIDATION_ERROR"
        )


def _validate_request_defaults(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValidationError("request_defaults must be an object", "CONFIG_VALIDATION_ERROR")
    if not isinstance(value.get("timeout_seconds"), (int, float)) or value["timeout_seconds"] <= 0:
        raise ValidationError(
            "request_defaults.timeout_seconds is invalid", "CONFIG_VALIDATION_ERROR"
        )
    if not isinstance(value.get("retries"), int) or value["retries"] < 0:
        raise ValidationError("request_defaults.retries is invalid", "CONFIG_VALIDATION_ERROR")


def _validate_rate_limits(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValidationError("rate_limits must be an object", "CONFIG_VALIDATION_ERROR")
    for key in ("max_concurrency", "max_requests_per_run"):
        if not isinstance(value.get(key), int) or value[key] <= 0:
            raise ValidationError(f"rate_limits.{key} is invalid", "CONFIG_VALIDATION_ERROR")


def _validate_payload_safety(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValidationError("payload_safety must be an object", "CONFIG_VALIDATION_ERROR")
    for key in (
        "allow_generated_payloads",
        "allow_data_pool_reuse",
        "destructive_operation",
        "allow_destructive_operation",
    ):
        if value.get(key) is not False:
            raise ValidationError(
                "payload_safety must be non-destructive", "CONFIG_VALIDATION_ERROR"
            )


def _validate_production_safeguards(value: Any, target_environment: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError("production_safeguards must be an object", "CONFIG_VALIDATION_ERROR")
    if value.get("allow_production_execution") is not False:
        raise ValidationError("production execution must be disabled", "CONFIG_VALIDATION_ERROR")
    if value.get("allow_destructive_operation") is not False:
        raise ValidationError("destructive operations must be disabled", "CONFIG_VALIDATION_ERROR")
    if (
        target_environment in {"prod", "production"}
        and value.get("allow_production_execution") is not False
    ):
        raise ValidationError("production profile is unsafe", "CONFIG_VALIDATION_ERROR")


def _validate_schedule_defaults(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValidationError("schedule_defaults must be an object", "CONFIG_VALIDATION_ERROR")
    for key in (
        "audit_window",
        "baseline_schedule",
        "burst_schedule",
        "repeated_schedule",
        "finalization_schedule",
    ):
        if key not in value or not isinstance(value[key], dict):
            raise ValidationError(
                "schedule_defaults missing required schedules", "CONFIG_VALIDATION_ERROR"
            )
    duration = value["audit_window"].get("duration_hours")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise ValidationError(
            "schedule_defaults.audit_window.duration_hours is invalid",
            "CONFIG_VALIDATION_ERROR",
        )
    _validate_manual_burst_defaults(value["burst_schedule"].get("manual_burst_defaults"))


def _validate_manual_burst_defaults(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValidationError(
            "schedule_defaults.burst_schedule.manual_burst_defaults must be an object",
            "CONFIG_VALIDATION_ERROR",
        )
    if value.get("enabled") is not True:
        raise ValidationError(
            "schedule_defaults.burst_schedule.manual_burst_defaults.enabled must be true",
            "CONFIG_VALIDATION_ERROR",
        )
    for key in ("request_count", "concurrency"):
        if (
            not isinstance(value.get(key), int)
            or isinstance(value.get(key), bool)
            or value[key] <= 0
        ):
            raise ValidationError(
                f"schedule_defaults.burst_schedule.manual_burst_defaults.{key} is invalid",
                "CONFIG_VALIDATION_ERROR",
            )


def _validate_retention_defaults(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValidationError("retention_defaults must be an object", "CONFIG_VALIDATION_ERROR")
    for key in ("evidence_retention_days", "config_retention_days"):
        if not isinstance(value.get(key), int) or value[key] <= 0:
            raise ValidationError(f"retention_defaults.{key} is invalid", "CONFIG_VALIDATION_ERROR")


def _reject_secret_bearing_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_lower = str(key).lower()
            if any(fragment in key_lower for fragment in SECRET_KEY_FRAGMENTS):
                raise ValidationError(
                    "defaults profile contains unsupported secret-bearing fields",
                    "CONFIG_VALIDATION_ERROR",
                )
            _reject_secret_bearing_fields(child)
    elif isinstance(value, list):
        for child in value:
            _reject_secret_bearing_fields(child)


def _validate_timezone(value: Any, *, error_type: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("timezone must not be empty", error_type)
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError("invalid timezone", error_type) from exc
