"""Audit lifecycle transition service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from packages.audit_lifecycle.state_machine import LifecycleStateMachine
from packages.core.constants.engine import LOG_CATEGORY_INTERNAL
from packages.core.logging import StructuredLogger
from packages.core.time import utc_now_iso
from packages.core.validators import validate_identifier
from packages.sanitization.sanitizer import sanitize


@dataclass(frozen=True)
class LifecycleTransition:
    client_id: str
    audit_id: str
    expected_current_state: str
    next_state: str
    reason: str
    actor: str
    metadata: dict[str, Any] = field(default_factory=dict)


class AuditLifecycleService:
    def __init__(self, repository: Any, logger: StructuredLogger | None = None):
        self.repository = repository
        self.state_machine = LifecycleStateMachine()
        self.logger = logger or StructuredLogger()

    def transition(self, transition: LifecycleTransition) -> dict[str, Any]:
        client_id = validate_identifier("client_id", transition.client_id)
        audit_id = validate_identifier("audit_id", transition.audit_id)
        self.state_machine.validate_transition(
            transition.expected_current_state, transition.next_state
        )
        entry = sanitize(
            {
                "client_id": client_id,
                "audit_id": audit_id,
                "from_state": transition.expected_current_state,
                "to_state": transition.next_state,
                "timestamp": utc_now_iso(),
                "reason": transition.reason,
                "actor": transition.actor,
                "metadata": transition.metadata or {},
            }
        )
        self.repository.append_lifecycle_transition(
            client_id=client_id,
            audit_id=audit_id,
            expected_current_state=transition.expected_current_state,
            next_state=transition.next_state,
            history_entry=entry,
        )
        self.logger.log(
            "lifecycle_transition",
            event_type="lifecycle_transition",
            log_category=LOG_CATEGORY_INTERNAL,
            level="INFO",
            service="AuditLifecycleService",
            stage="lifecycle",
            client_id=client_id,
            audit_id=audit_id,
            from_state=transition.expected_current_state,
            to_state=transition.next_state,
            actor=transition.actor,
            reason=transition.reason,
        )
        return entry
