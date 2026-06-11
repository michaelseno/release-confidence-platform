"""Durable audit execution identity resolution."""

from __future__ import annotations

import uuid
from typing import Any

from release_confidence_platform.core.exceptions import ValidationError
from release_confidence_platform.core.time import utc_now_iso
from release_confidence_platform.core.validators import validate_identifier


def generate_audit_execution_id() -> str:
    return f"audexec_{uuid.uuid4().hex}"


class AuditExecutionIdentityResolver:
    def __init__(self, repository: Any):
        self.repository = repository

    def resolve_or_assign(self, client_id: str, audit_id: str, audit: dict[str, Any]) -> str:
        existing = audit.get("audit_execution_id")
        if existing:
            return validate_identifier("audit_execution_id", existing)
        child = self.repository.get_audit_execution_identity(client_id, audit_id)
        if child and child.get("audit_execution_id"):
            return validate_identifier("audit_execution_id", child["audit_execution_id"])
        audit_execution_id = generate_audit_execution_id()
        try:
            self.repository.put_audit_execution_identity_once(
                {
                    **self.repository.execution_identity_keys(client_id, audit_id),
                    "client_id": client_id,
                    "audit_id": audit_id,
                    "audit_execution_id": audit_execution_id,
                    "source": "phase4_identity_assignment",
                    "created_at": utc_now_iso(),
                }
            )
        except Exception as exc:
            child = self.repository.get_audit_execution_identity(client_id, audit_id)
            if child and child.get("audit_execution_id"):
                return validate_identifier("audit_execution_id", child["audit_execution_id"])
            raise ValidationError(
                "Missing audit_execution_id", "MISSING_AUDIT_EXECUTION_ID"
            ) from exc
        return audit_execution_id
