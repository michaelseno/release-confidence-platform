import copy

import pytest

from packages.audit_lifecycle.constants import LIFECYCLE_STATES
from packages.audit_lifecycle.exceptions import InvalidTransitionError
from packages.audit_lifecycle.service import AuditLifecycleService, LifecycleTransition
from packages.audit_lifecycle.state_machine import LifecycleStateMachine


class Repo:
    def __init__(self):
        self.item = {"lifecycle_state": "DRAFT", "lifecycle_history": [{"existing": True}]}

    def append_lifecycle_transition(self, **kwargs):
        assert kwargs["expected_current_state"] == self.item["lifecycle_state"]
        self.item["lifecycle_state"] = kwargs["next_state"]
        self.item["lifecycle_history"].append(kwargs["history_entry"])


def test_lifecycle_states_and_transitions():
    assert LIFECYCLE_STATES == (
        "DRAFT",
        "SCHEDULED",
        "RUNNING",
        "FINALIZING",
        "ANALYZING",
        "REPORTING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    )
    LifecycleStateMachine.validate_transition("DRAFT", "SCHEDULED")
    LifecycleStateMachine.validate_transition("FINALIZING", "ANALYZING")
    LifecycleStateMachine.validate_transition("ANALYZING", "REPORTING")
    LifecycleStateMachine.validate_transition("REPORTING", "COMPLETED")


def test_invalid_transition_and_scheduled_with_errors_rejected():
    with pytest.raises(InvalidTransitionError):
        LifecycleStateMachine.validate_state("SCHEDULED_WITH_ERRORS")
    with pytest.raises(InvalidTransitionError):
        LifecycleStateMachine.validate_transition("COMPLETED", "RUNNING")


def test_lifecycle_history_append_only():
    repo = Repo()
    original = copy.deepcopy(repo.item["lifecycle_history"])
    AuditLifecycleService(repo).transition(
        LifecycleTransition(
            client_id="client123",
            audit_id="audit456",
            expected_current_state="DRAFT",
            next_state="SCHEDULED",
            reason="schedules_created",
            actor="scheduler",
            metadata={"raw_token": "must redact"},
        )
    )
    assert repo.item["lifecycle_state"] == "SCHEDULED"
    assert repo.item["lifecycle_history"][:1] == original
    assert len(repo.item["lifecycle_history"]) == 2
    assert repo.item["lifecycle_history"][1]["metadata"]["raw_token"] == "[REDACTED]"
