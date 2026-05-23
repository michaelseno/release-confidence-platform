"""Shared audit creation orchestration."""

from __future__ import annotations

from typing import Any

from packages.audit_lifecycle.constants import LIFECYCLE_STATE_DRAFT, LIFECYCLE_STATE_FAILED
from packages.audit_scheduling.safeguards import effective_caps
from packages.config.audit_validation_service import AuditConfigValidationService
from packages.config.stage_config import StageConfig
from packages.core.exceptions import StorageError
from packages.core.time import utc_now_iso
from packages.sanitization.sanitizer import sanitize


def config_keys(client_id: str, audit_id: str) -> dict[str, str]:
    return {
        "client_config": f"configs/{client_id}/client_config.json",
        "audit_config": f"configs/{client_id}/audits/{audit_id}/audit_config.json",
        "endpoints_config": f"configs/{client_id}/audits/{audit_id}/endpoints.json",
    }


class AuditCreationService:
    def __init__(
        self,
        *,
        stage_config: StageConfig,
        s3_storage: Any,
        repository: Any,
        validation_service: AuditConfigValidationService | None = None,
    ):
        self.stage_config = stage_config
        self.s3 = s3_storage
        self.repository = repository
        self.validation = validation_service or AuditConfigValidationService()

    def create_from_files(
        self,
        *,
        client_config_path: str,
        audit_config_path: str,
        endpoints_config_path: str,
        dry_run: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        validated = self.validation.validate_files(
            client_config_path=client_config_path,
            audit_config_path=audit_config_path,
            endpoints_config_path=endpoints_config_path,
            stage=self.stage_config.stage,
        )
        keys = config_keys(validated.client_id, validated.audit_id)
        if dry_run:
            return sanitize(
                {
                    "status": "dry_run",
                    "client_id": validated.client_id,
                    "audit_id": validated.audit_id,
                    "planned_actions": [
                        *(f"upload {key}" for key in keys.values()),
                        "write DRAFT audit metadata",
                    ],
                    "force": force,
                }
            )
        existing_metadata = None
        try:
            existing_metadata = self.repository.get_audit_metadata(
                validated.client_id, validated.audit_id
            )
        except Exception:
            existing_metadata = None
        if force:
            if existing_metadata is None:
                raise StorageError(
                    "Force recreate requires existing audit metadata", "FORCE_RECREATE_BLOCKED"
                )
            state = existing_metadata.get("lifecycle_state")
            if state not in {LIFECYCLE_STATE_DRAFT, LIFECYCLE_STATE_FAILED}:
                raise StorageError(
                    "Audit lifecycle is not eligible for force recreate", "FORCE_RECREATE_BLOCKED"
                )
        else:
            existing_keys = [key for key in keys.values() if self.s3.object_exists(key)]
            if existing_keys:
                raise StorageError("Config object exists", "CONFIG_OBJECT_EXISTS")
            if existing_metadata is not None:
                raise StorageError("Audit metadata exists", "AUDIT_EXISTS")
        metadata = self._metadata(validated, keys, force=force)
        for label, payload in (
            ("client_config", validated.client_config),
            ("audit_config", validated.audit_config),
            ("endpoints_config", validated.endpoints_config),
        ):
            self.s3.write_json(keys[label], payload, overwrite=force)
        if force:
            self.repository.update_for_force_recreate(metadata)
        else:
            self.repository.put_audit_metadata_once(metadata)
        return sanitize(
            {
                "status": "success",
                "client_id": validated.client_id,
                "audit_id": validated.audit_id,
                "lifecycle_state": LIFECYCLE_STATE_DRAFT,
                "config_s3_keys": keys,
                "force": force,
            }
        )

    def _metadata(self, validated: Any, keys: dict[str, str], *, force: bool) -> dict[str, Any]:
        now = utc_now_iso()
        item = {
            **self.repository.audit_keys(validated.client_id, validated.audit_id),
            "client_id": validated.client_id,
            "audit_id": validated.audit_id,
            "lifecycle_state": LIFECYCLE_STATE_DRAFT,
            "lifecycle_history": [],
            "config_hash": validated.config_hash,
            "config_version": validated.config_version,
            "config_s3_keys": keys,
            "audit_window": validated.normalized_audit_config["audit_window"],
            "execution_environment": validated.normalized_audit_config.get("execution_environment"),
            "operational_caps": effective_caps(
                validated.normalized_audit_config.get("execution_environment")
            ),
            "schedules": [],
            "cleanup_errors": [],
            "created_at": now,
            "updated_at": now,
        }
        if force:
            item["force_history_entry"] = {
                "from_state": "DRAFT_OR_FAILED",
                "to_state": LIFECYCLE_STATE_DRAFT,
                "timestamp": now,
                "reason": "force_recreate",
                "actor": "operator_cli",
            }
        return sanitize(item)
