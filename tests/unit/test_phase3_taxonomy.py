import pytest

from packages.audit_scheduling.constants import SCENARIO_TYPES
from packages.audit_scheduling.taxonomy import reliability_category_for, validate_scenario_type
from packages.core.exceptions import ValidationError


def test_taxonomy_and_reliability_mapping():
    assert set(SCENARIO_TYPES) == {
        "baseline_health",
        "repeated_stability",
        "burst_stability",
        "invalid_payload_handling",
        "missing_fields_validation",
        "auth_failure_handling",
        "timeout_sensitivity",
        "response_consistency",
    }
    assert reliability_category_for("timeout_sensitivity") == "Resilience"
    assert reliability_category_for("missing_fields_validation") == "Validation Robustness"


def test_unknown_scenario_rejected():
    with pytest.raises(ValidationError):
        validate_scenario_type("generic_api_test")
