"""Scenario taxonomy helpers."""

from __future__ import annotations

from packages.audit_scheduling.constants import (
    RELIABILITY_CATEGORY_BY_SCENARIO,
    SCENARIO_TYPES,
)
from packages.core.exceptions import ValidationError


def validate_scenario_type(value: str) -> str:
    if value not in SCENARIO_TYPES:
        raise ValidationError("Unknown scenario type", "INVALID_SCENARIO_TYPE")
    if value not in RELIABILITY_CATEGORY_BY_SCENARIO:
        raise ValidationError("Missing reliability category mapping", "INVALID_SCENARIO_CATEGORY")
    return value


def reliability_category_for(value: str) -> str:
    validate_scenario_type(value)
    return RELIABILITY_CATEGORY_BY_SCENARIO[value]
