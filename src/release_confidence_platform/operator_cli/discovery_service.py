"""Read-only discovery services for internal operator CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from release_confidence_platform.core.constants.engine import (
    AUDIT_CONFIG_KEY_TEMPLATE,
    CLIENT_CONFIG_KEY_TEMPLATE,
    ENDPOINTS_CONFIG_KEY_TEMPLATE,
)
from release_confidence_platform.core.exceptions import StorageError, ValidationError
from release_confidence_platform.core.validators import validate_identifier

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
CONFIG_ARTIFACTS = (
    ("client", "client_config.json", CLIENT_CONFIG_KEY_TEMPLATE),
    ("audit", "audit_config.json", AUDIT_CONFIG_KEY_TEMPLATE),
    ("endpoints", "endpoints.json", ENDPOINTS_CONFIG_KEY_TEMPLATE),
)


class DiscoveryListService:
    def __init__(self, repository: Any):
        self.repository = repository

    def list_clients(self, *, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
        effective_limit = _validate_limit(limit)
        registry_page = self.repository.list_clients_from_registry(limit=effective_limit)
        page = registry_page or self.repository.scan_clients_bounded(
            limit=effective_limit, max_items=MAX_LIMIT
        )
        items = [_safe_client(item) for item in page.get("items", [])]
        return {
            "items": items,
            "limit": effective_limit,
            "count": len(items),
            "truncated": bool(page.get("last_evaluated_key")),
            "fallback": (
                "bounded_audit_metadata_scan" if registry_page is None else "client_registry"
            ),
        }

    def list_audits(self, *, client_id: str, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
        client_id = validate_identifier("client_id", client_id)
        effective_limit = _validate_limit(limit)
        page = self.repository.list_audits_for_client(client_id, limit=effective_limit)
        items = []
        for item in page.get("items", []):
            if not _is_canonical_audit_item(item, client_id):
                continue
            items.append(_safe_audit(item))
            if len(items) >= effective_limit:
                break
        return {
            "client_id": client_id,
            "items": items,
            "limit": effective_limit,
            "count": len(items),
            "truncated": bool(page.get("last_evaluated_key")),
        }


class ConfigDiscoveryService:
    def __init__(self, s3_storage: Any, *, stage: str):
        self.s3_storage = s3_storage
        self.stage = stage

    def list_config_keys(self, *, client_id: str, audit_id: str) -> dict[str, Any]:
        client_id, audit_id = _validate_ids(client_id, audit_id)
        config_keys = []
        for artifact_type, file_name, template in CONFIG_ARTIFACTS:
            key = _config_key(template, client_id, audit_id)
            metadata = self.s3_storage.head_metadata(key)
            entry = {
                "type": artifact_type,
                "file_name": file_name,
                "key": key,
                "exists": metadata is not None,
            }
            if metadata:
                entry.update(metadata)
            config_keys.append(entry)
        return {
            "client_id": client_id,
            "audit_id": audit_id,
            "config_keys": config_keys,
            "count": len([item for item in config_keys if item["exists"]]),
        }

    def download_audit_config_set(
        self,
        *,
        client_id: str,
        audit_id: str,
        output_dir: str | Path,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        client_id, audit_id = _validate_ids(client_id, audit_id)
        destination = Path(output_dir)
        if destination.exists() and not destination.is_dir():
            raise StorageError("Output directory path is an existing file", "INVALID_OUTPUT_DIR")
        targets = _targets(client_id, audit_id, destination)
        conflicts = [target.name for _, _, target in targets if target.exists()]
        if conflicts and not overwrite:
            raise StorageError(
                "one or more destination files already exist; no files were replaced: "
                + ", ".join(conflicts),
                "LOCAL_FILE_EXISTS",
            )
        missing = []
        for artifact_type, key, _target in targets:
            if self.s3_storage.head_metadata(key) is None:
                missing.append(f"{artifact_type}:{key}")
        if missing:
            raise StorageError(
                "missing required config artifacts: " + ", ".join(missing),
                "CONFIG_ARTIFACT_NOT_FOUND",
            )
        contents: list[tuple[str, str, Path, str]] = []
        for artifact_type, key, target in targets:
            contents.append((artifact_type, key, target, self.s3_storage.read_text(key)))
        destination.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        try:
            for _artifact_type, _key, target, content in contents:
                target.write_text(content, encoding="utf-8")
                written.append(target)
        except Exception as exc:
            for target in written:
                try:
                    target.unlink()
                except OSError:
                    pass
            raise StorageError("Local config write failed", "LOCAL_WRITE_FAILED") from exc
        downloaded_files = [
            {"type": artifact_type, "path": str(target), "file_name": target.name}
            for artifact_type, _key, target, _content in contents
        ]
        return {
            "client_id": client_id,
            "audit_id": audit_id,
            "output_dir": str(destination),
            "downloaded_files": downloaded_files,
            "count": len(downloaded_files),
            "overwritten": overwrite,
            "warning": (
                "downloaded configs may contain sensitive operational details; keep files under "
                ".local-configs/ and do not commit them"
            ),
        }


def _validate_limit(value: int) -> int:
    if not isinstance(value, int) or value < 1 or value > MAX_LIMIT:
        raise ValidationError("--limit must be an integer between 1 and 1000", "INVALID_ARGUMENT")
    return value


def _validate_ids(client_id: str, audit_id: str) -> tuple[str, str]:
    return validate_identifier("client_id", client_id), validate_identifier("audit_id", audit_id)


def _config_key(template: str, client_id: str, audit_id: str) -> str:
    return template.format(client_id=client_id, audit_id=audit_id)


def _targets(client_id: str, audit_id: str, destination: Path):
    return [
        (artifact_type, _config_key(template, client_id, audit_id), destination / file_name)
        for artifact_type, file_name, template in CONFIG_ARTIFACTS
    ]


def _safe_client(item: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        item, ("client_id", "client_name", "created_at", "updated_at", "active_audit_count")
    )


def _safe_audit(item: dict[str, Any]) -> dict[str, Any]:
    audit_id = item.get("audit_id")
    sk = item.get("SK")
    if not audit_id and isinstance(sk, str) and sk.startswith("AUDIT#"):
        audit_id = sk.removeprefix("AUDIT#").split("#", 1)[0]
    data = _pick(
        item,
        (
            "lifecycle_state",
            "created_at",
            "updated_at",
            "audit_window",
            "target_environment",
            "execution_environment",
            "config_version",
            "config_hash",
            "schedule_status",
        ),
    )
    data["audit_id"] = audit_id
    if "target_environment" not in data and isinstance(data.get("execution_environment"), dict):
        data["target_environment"] = data["execution_environment"].get("target_environment")
    data.pop("execution_environment", None)
    return {k: v for k, v in data.items() if v is not None}


def _is_canonical_audit_item(item: dict[str, Any], client_id: str) -> bool:
    pk = item.get("PK")
    sk = item.get("SK")
    if pk is not None and pk != f"CLIENT#{client_id}":
        return False
    if not isinstance(sk, str) or not sk.startswith("AUDIT#"):
        return False
    audit_id = sk.removeprefix("AUDIT#")
    return bool(audit_id) and "#" not in audit_id


def _pick(item: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: item[field] for field in fields if item.get(field) is not None}
