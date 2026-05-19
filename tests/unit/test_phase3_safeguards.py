import pytest

from packages.audit_scheduling.safeguards import (
    effective_caps,
    ensure_execution_allowed,
    validate_audit_window,
)
from packages.audit_scheduling.validators import validate_schedule_config
from packages.core.exceptions import ValidationError


def test_audit_window_default_and_cap():
    window = validate_audit_window({"start_time": "2026-05-19T00:00:00Z"})
    assert window["end_time"] == "2026-05-21T00:00:00Z"
    with pytest.raises(ValidationError):
        validate_audit_window({"start_time": "2026-05-19T00:00:00Z", "duration_hours": 49})


def test_caps_and_production_block():
    assert effective_caps({"target_environment": "staging"})["max_concurrency"] == 5
    with pytest.raises(ValidationError):
        effective_caps({"target_environment": "production", "allow_production_execution": False})
    assert (
        effective_caps({"target_environment": "production", "allow_production_execution": True})[
            "max_concurrency"
        ]
        == 2
    )


def test_schedule_config_rejects_caps_and_repeated_estimate():
    window = {"start_time": "2026-05-19T00:00:00Z", "end_time": "2026-05-19T01:00:00Z"}
    with pytest.raises(ValidationError):
        validate_schedule_config(
            {
                "client_id": "client123",
                "audit_id": "audit456",
                "burst_schedule": {"windows": [{"request_count": 501, "concurrency": 1}]},
            },
            window,
        )
    with pytest.raises(ValidationError):
        validate_schedule_config(
            {
                "client_id": "client123",
                "audit_id": "audit456",
                "repeated": [{"iteration_count": 101}],
            },
            window,
        )


def test_schedule_config_enforces_burst_request_count_per_run_caps():
    window = {"start_time": "2026-05-19T00:00:00Z", "end_time": "2026-05-19T01:00:00Z"}
    base_config = {
        "client_id": "client123",
        "audit_id": "audit456",
    }

    with pytest.raises(ValidationError):
        validate_schedule_config(
            {
                **base_config,
                "execution_environment": {"target_environment": "staging"},
                "burst_schedule": {"windows": [{"request_count": 101, "concurrency": 1}]},
            },
            window,
        )

    accepted = validate_schedule_config(
        {
            **base_config,
            "execution_environment": {"target_environment": "staging"},
            "burst_schedule": {"windows": [{"request_count": 100, "concurrency": 1}]},
        },
        window,
    )
    assert accepted["burst_schedule"]["windows"][0]["request_count"] == 100

    with pytest.raises(ValidationError):
        validate_schedule_config(
            {
                **base_config,
                "execution_environment": {
                    "target_environment": "production",
                    "allow_production_execution": True,
                },
                "burst_schedule": {"windows": [{"request_count": 26, "concurrency": 1}]},
            },
            window,
        )

    accepted_prod = validate_schedule_config(
        {
            **base_config,
            "execution_environment": {
                "target_environment": "production",
                "allow_production_execution": True,
            },
            "burst_schedule": {"windows": [{"request_count": 25, "concurrency": 1}]},
        },
        window,
    )
    assert accepted_prod["burst_schedule"]["windows"][0]["request_count"] == 25


def test_execution_guard_enforces_burst_request_count_per_run_caps():
    audit = {
        "lifecycle_state": "RUNNING",
        "audit_window": {"start_time": "2026-05-19T00:00:00Z", "end_time": "2026-05-21T00:00:00Z"},
        "execution_environment": {"target_environment": "staging"},
    }
    event = {
        "scheduled_at": "2026-05-20T00:00:00Z",
        "burst": {"request_count": 101, "concurrency": 1},
    }
    with pytest.raises(ValidationError):
        ensure_execution_allowed(audit, event)

    event["burst"]["request_count"] = 100
    ensure_execution_allowed(audit, event)

    audit["execution_environment"] = {
        "target_environment": "production",
        "allow_production_execution": True,
    }
    event["burst"]["request_count"] = 26
    with pytest.raises(ValidationError):
        ensure_execution_allowed(audit, event)

    event["burst"]["request_count"] = 25
    ensure_execution_allowed(audit, event)


def test_execution_guard_blocks_expired_terminal_production_and_token():
    event = {
        "scheduled_at": "2026-05-20T00:00:00Z",
        "burst": {"request_count": 1, "concurrency": 1},
    }
    audit = {
        "lifecycle_state": "FAILED",
        "audit_window": {"start_time": "2026-05-19T00:00:00Z", "end_time": "2026-05-21T00:00:00Z"},
    }
    with pytest.raises(ValidationError):
        ensure_execution_allowed(audit, event)
    audit["lifecycle_state"] = "RUNNING"
    audit["execution_environment"] = {
        "target_environment": "production",
        "allow_production_execution": False,
    }
    with pytest.raises(ValidationError):
        ensure_execution_allowed(audit, event)
    audit["execution_environment"] = {"target_environment": "staging"}
    audit["temporary_token"] = {"expires_at": "2026-05-19T23:00:00Z"}
    with pytest.raises(ValidationError):
        ensure_execution_allowed(audit, event)
