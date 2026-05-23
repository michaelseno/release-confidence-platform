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

SUPPORTED_TARGET_ENVIRONMENTS = {"dev", "staging", "prod", "production"}
GIT_SAFETY_WARNING = (
    "local generated configs may contain operational details; keep files under .local-configs/ "
    "and add .local-configs/ to .gitignore"
)


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
        target_environment: str,
        output_dir: str | Path,
        timezone: str = "UTC",
        include_sample_endpoints: bool = False,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        _validate_target_environment(target_environment)
        _validate_timezone(timezone)
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
            client_id=client_id, client_name=client_name, target_environment=target_environment
        )
        audit_config = generate_audit_config(
            client_id=client_id,
            audit_id=audit_id,
            target_environment=target_environment,
            timezone=timezone,
        )
        endpoints_config = generate_endpoints_config(
            client_id=client_id,
            audit_id=audit_id,
            target_environment=target_environment,
            include_sample=include_sample_endpoints,
        )
        self.validation_service.validate_configs(
            client_config=client_config,
            audit_config=audit_config,
            endpoints_config=endpoints_config,
            stage="dev",
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

        return {
            "client_id": client_id,
            "audit_id": audit_id,
            "output_dir": str(root),
            "generated_files": [
                {"type": kind, "path": str(path), "file_name": path.name} for kind, path, _ in files
            ],
            "overwritten": bool(overwrite and existed_before),
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
