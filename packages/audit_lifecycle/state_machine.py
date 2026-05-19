"""Deterministic lifecycle state machine."""

from __future__ import annotations

from packages.audit_lifecycle.constants import LIFECYCLE_STATES, TRANSITIONS
from packages.audit_lifecycle.exceptions import InvalidTransitionError


class LifecycleStateMachine:
    @staticmethod
    def validate_state(state: str) -> str:
        if state not in LIFECYCLE_STATES:
            raise InvalidTransitionError("Unknown lifecycle state")
        return state

    @classmethod
    def validate_transition(cls, current_state: str, next_state: str) -> None:
        cls.validate_state(current_state)
        cls.validate_state(next_state)
        if next_state not in TRANSITIONS[current_state]:
            raise InvalidTransitionError("Invalid lifecycle transition")

    @classmethod
    def allowed_next_states(cls, current_state: str) -> tuple[str, ...]:
        cls.validate_state(current_state)
        return TRANSITIONS[current_state]
