"""Local-only config init service for operator starter templates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from release_confidence_platform.config.audit_validation_service import AuditConfigValidationService
from release_confidence_platform.config.generators import (
    generate_audit_config,
    generate_client_config,
    generate_endpoints_config,
)
from release_confidence_platform.core.exceptions import StorageError, ValidationError
from release_confidence_platform.core.id_generation import generate_audit_id, generate_client_id
from release_confidence_platform.core.slug_utils import slugify_client_name
from release_confidence_platform.operator_cli.default_profiles import (
    SAFE_FALLBACK_OUTPUT,
    SAFE_FALLBACK_OUTPUT_DIR,
    SAFE_FALLBACK_TIMEZONE,
    load_default_profile,
)

SUPPORTED_TARGET_ENVIRONMENTS = {"dev", "staging", "prod", "production"}
GIT_SAFETY_WARNING = (
    "local generated configs may contain operational details; keep files under .local-configs/ "
    "and add .local-configs/ to .gitignore"
)
RESOLUTION_ORDER = [
    "explicit_cli_argument",
    "profile_operator_defaults",
    "safe_fallback",
]
NEXT_STEPS = [
    "Review generated JSON files.",
    "Add real endpoints only after review; do not store secrets in generated config files.",
    "Run rcp audit validate after endpoints.json contains at least one real endpoint.",
    "Use rcp audit create --dry-run for local create planning without AWS mutation.",
    (
        "Run non-dry-run rcp audit create or rcp audit run only after endpoints are edited, "
        "local validation passes, deployed stage resources exist, and config/stages/<stage>.json "
        "aws_profile or RCP_AWS_PROFILE points to loadable AWS credentials."
    ),
]


@dataclass(frozen=True)
class ConfigInitService:
    validation_service: AuditConfigValidationService = AuditConfigValidationService()
    client_shortid: str | None = None
    audit_shortid: str | None = None
    today: date | None = None

    def init(
        self,
        *,
        client_name: str,
        defaults: str | None = None,
        target_environment: str | None = None,
        output_dir: str | Path | None = None,
        timezone: str | None = None,
        output: str | None = None,
        include_sample_endpoints: bool = False,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        profile = load_default_profile(defaults)
        profile_data = profile.data
        operator_defaults = profile_data.get("operator_defaults") or {}
        target_environment = target_environment or profile_data.get("target_environment") or "dev"
        timezone = timezone or operator_defaults.get("timezone") or SAFE_FALLBACK_TIMEZONE
        output_format = output or operator_defaults.get("output") or SAFE_FALLBACK_OUTPUT
        output_dir = output_dir or operator_defaults.get("output_dir") or SAFE_FALLBACK_OUTPUT_DIR
        _validate_target_environment(target_environment)
        _validate_timezone(timezone)
        _validate_output(output_format)
        parent = Path(output_dir)
        if parent.exists() and not parent.is_dir():
            raise ValidationError("output_dir must be a directory path", "INVALID_ARGUMENT")

        # Validate slug before ID generation so unsafe names fail before path calculations/writes.
        slugify_client_name(client_name)
        client_id = generate_client_id(client_name, shortid=self.client_shortid)
        audit_id = generate_audit_id(today=self.today, shortid=self.audit_shortid)
        root = parent / client_id
        audit_dir = root / "audits" / audit_id
        client_path = root / "client_config.json"
        audit_path = audit_dir / "audit_config.json"
        endpoints_path = audit_dir / "endpoints.json"

        client_config = generate_client_config(
            client_id=client_id,
            client_name=client_name,
            target_environment=target_environment,
            request_defaults=profile_data.get("request_defaults"),
            rate_limits=profile_data.get("rate_limits"),
            retention_defaults=profile_data.get("retention_defaults"),
        )
        audit_config = generate_audit_config(
            client_id=client_id,
            audit_id=audit_id,
            target_environment=target_environment,
            timezone=timezone,
            schedule_defaults=profile_data.get("schedule_defaults"),
            rate_limits=profile_data.get("rate_limits"),
        )
        endpoints_config = generate_endpoints_config(
            client_id=client_id,
            audit_id=audit_id,
            target_environment=target_environment,
            include_sample=include_sample_endpoints,
            request_defaults=profile_data.get("request_defaults"),
        )
        self.validation_service.validate_configs(
            client_config=client_config,
            audit_config=audit_config,
            endpoints_config=endpoints_config,
            stage=_validation_stage(target_environment),
            template_mode=True,
        )

        existed_before = root.exists()
        if existed_before and not overwrite:
            raise StorageError(f"generated client root already exists: {root}", "LOCAL_FILE_EXISTS")

        files = [
            ("client", client_path, client_config),
            ("audit", audit_path, audit_config),
            ("endpoints", endpoints_path, endpoints_config),
        ]
        written: list[Path] = []
        try:
            audit_dir.mkdir(parents=True, exist_ok=True)
            for _, path, payload in files:
                path.write_text(
                    json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
                )
                written.append(path)
        except OSError as exc:
            for path in written:
                try:
                    path.unlink()
                except OSError:
                    pass
            raise StorageError(
                "failed to write generated config files", "LOCAL_WRITE_FAILED"
            ) from exc

        profile_source = "path" if _is_path_like_default(defaults) else "named"
        generated_files = [
            {"type": kind, "path": str(path), "file_name": path.name} for kind, path, _ in files
        ]
        is_production_target = profile.name == "prod" or target_environment in {
            "prod",
            "production",
        }
        warnings: list[dict[str, str]] = []
        if is_production_target:
            warnings.append(
                {
                    "code": "PRODUCTION_TARGET_SAFE_LOCAL_ONLY",
                    "message": (
                        "Production target defaults selected; generated configs remain local "
                        "and non-executable by default."
                    ),
                }
            )
        if overwrite and existed_before:
            warnings.append(
                {
                    "code": "OUTPUT_WORKSPACE_OVERWRITTEN",
                    "message": "Existing workspace was overwritten.",
                    "path": str(root),
                }
            )

        return {
            "client_id": client_id,
            "audit_id": audit_id,
            "defaults_profile": profile.name,
            "defaults_source": str(profile.source_path),
            "target_environment": target_environment,
            "output_format": output_format,
            "output_dir": str(root),
            "generated_files": generated_files,
            "profile": {
                "source": profile_source,
                "name": profile.name,
                "path": str(profile.source_path),
                "target_environment": target_environment,
            },
            "effective_settings": {
                "workspace_root": str(root),
                "timezone": timezone,
                "include_sample_endpoints": include_sample_endpoints,
                "sample_endpoint_safety": (
                    "mock_only" if include_sample_endpoints else "empty_endpoints_array"
                ),
                "overwrite": overwrite,
                "output_format": output_format,
            },
            "resolution_order": RESOLUTION_ORDER,
            "safety": {
                "local_only": True,
                "aws_calls_made": False,
                "configs_uploaded": False,
                "schedules_created": False,
                "allow_production_execution": False,
                "allow_destructive_operation": False,
            },
            "warnings": warnings,
            "next_steps": NEXT_STEPS,
            "overwritten": bool(overwrite and existed_before),
            "local_only": True,
            "aws_interaction": False,
            "warning": GIT_SAFETY_WARNING,
        }


def _validate_target_environment(value: str) -> None:
    if value not in SUPPORTED_TARGET_ENVIRONMENTS:
        raise ValidationError("unsupported target environment", "INVALID_ARGUMENT")


def _validate_timezone(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("timezone must not be empty", "INVALID_ARGUMENT")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValidationError("invalid timezone", "INVALID_ARGUMENT") from exc
    except ValueError as exc:
        raise ValidationError("invalid timezone", "INVALID_ARGUMENT") from exc


def _validate_output(value: str) -> None:
    if value not in {"text", "json"}:
        raise ValidationError("unsupported output format", "INVALID_ARGUMENT")


def _validation_stage(target_environment: str) -> str:
    return "prod" if target_environment in {"prod", "production"} else target_environment


def _is_path_like_default(value: str | None) -> bool:
    if not value:
        return False
    return "/" in value or "\\" in value or value.endswith(".json")
