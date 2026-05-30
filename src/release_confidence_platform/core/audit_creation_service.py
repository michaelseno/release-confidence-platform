"""Shared audit creation orchestration."""

from __future__ import annotations

import json
from typing import Any

from release_confidence_platform.audit_lifecycle.constants import (
    LIFECYCLE_STATE_DRAFT,
    LIFECYCLE_STATE_FAILED,
)
from release_confidence_platform.audit_scheduling.safeguards import effective_caps
from release_confidence_platform.config.audit_validation_service import AuditConfigValidationService
from release_confidence_platform.config.stage_config import StageConfig
from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.core.time import utc_now_iso
from release_confidence_platform.sanitization.sanitizer import sanitize


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
        except StorageError as exc:
            if exc.error_type != "AUDIT_NOT_FOUND":
                raise
        adopt_existing_artifacts = False
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
            existing_artifacts = {label: self.s3.object_exists(key) for label, key in keys.items()}
            if any(existing_artifacts.values()):
                if existing_metadata is None:
                    self._reconcile_existing_config_artifacts(validated, keys, existing_artifacts)
                    adopt_existing_artifacts = True
                else:
                    raise StorageError("Config object exists", "CONFIG_OBJECT_EXISTS")
            if existing_metadata is not None:
                raise StorageError("Audit metadata exists", "AUDIT_EXISTS")
        metadata = self._metadata(validated, keys, force=force)
        if not adopt_existing_artifacts:
            for label, payload in _config_payloads(validated):
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

    def _reconcile_existing_config_artifacts(
        self, validated: Any, keys: dict[str, str], existing_artifacts: dict[str, bool]
    ) -> None:
        diagnostics: list[dict[str, str]] = []
        all_match = True
        for label, payload in _config_payloads(validated):
            key = keys[label]
            if not existing_artifacts[label]:
                diagnostics.append({"artifact": label, "key": key, "state": "missing"})
                all_match = False
                continue
            existing_payload = self.s3.read_json(key)
            if _normalized_json(existing_payload) == _normalized_json(payload):
                diagnostics.append({"artifact": label, "key": key, "state": "match"})
            else:
                diagnostics.append({"artifact": label, "key": key, "state": "mismatch"})
                all_match = False
        if all_match:
            return
        raise StorageError(
            "Partial audit create state exists; "
            f"artifacts={_format_artifact_diagnostics(diagnostics)}; "
            "metadata_absent=true; recovery=retry with a new bundle/new IDs, or delete only "
            "the exact stale config objects when metadata is absent, or use --force only when "
            "metadata exists in DRAFT/FAILED and replacement is safe",
            "PARTIAL_AUDIT_CREATE_EXISTS",
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


def _config_payloads(validated: Any) -> tuple[tuple[str, dict[str, Any]], ...]:
    return (
        ("client_config", validated.client_config),
        ("audit_config", validated.audit_config),
        ("endpoints_config", validated.endpoints_config),
    )


def _normalized_json(payload: dict[str, Any]) -> str:
    return json.dumps(sanitize(payload), sort_keys=True, separators=(",", ":"))


def _format_artifact_diagnostics(diagnostics: list[dict[str, str]]) -> str:
    sanitized = sanitize(diagnostics)
    return ",".join(f"{item['artifact']}:{item['state']}:{item['key']}" for item in sanitized)
