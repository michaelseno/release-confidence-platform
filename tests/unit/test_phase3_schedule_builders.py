import pytest

from packages.audit_scheduling.builders import ScheduleBuilder, schedule_name
from packages.core.exceptions import ValidationError


def test_schedule_names_exact_and_finalization():
    name, suffix = schedule_name(
        stage="staging",
        client_id="client123",
        audit_id="audit456",
        schedule_type="baseline",
        scenario_type="baseline_health",
    )
    assert name == "rcp-staging-client123-audit456-baseline-baseline_health"
    assert suffix is None
    final, _ = schedule_name(
        stage="staging", client_id="client123", audit_id="audit456", schedule_type="finalization"
    )
    assert final == "rcp-staging-client123-audit456-finalization"


def test_schedule_name_truncation_is_deterministic_and_distinct():
    kwargs = {
        "stage": "staging",
        "client_id": "client" + "a" * 80,
        "audit_id": "audit" + "b" * 80,
        "schedule_type": "baseline",
        "scenario_type": "baseline_health",
    }
    one, suffix_one = schedule_name(**kwargs)
    two, suffix_two = schedule_name(**kwargs)
    different, suffix_different = schedule_name(**{**kwargs, "audit_id": "audit" + "c" * 80})
    assert len(one) <= 64
    assert one == two
    assert suffix_one == suffix_two
    assert suffix_one != suffix_different
    assert one != different


def test_builder_payloads_omit_run_id_and_baseline_defaults():
    config = {"client_id": "client123", "audit_id": "audit456"}
    window = {"start_time": "2026-05-19T00:00:00Z", "end_time": "2026-05-21T00:00:00Z"}
    definition = ScheduleBuilder(stage="dev").build_baseline(config, window)
    assert definition.expression == "rate(15 minutes)"
    assert "run_id" not in definition.target_payload
    assert definition.target_payload["schedule_occurrence_id"].startswith("baseline#")


def test_burst_timezone_and_invalid_identifier():
    config = {"client_id": "client123", "audit_id": "audit456"}
    window = {
        "start_time": "2026-05-19T00:00:00Z",
        "end_time": "2026-05-21T00:00:00Z",
        "timezone": "America/New_York",
    }
    definition = ScheduleBuilder(stage="dev").build_burst(
        config,
        window,
        {"start_time": "09:00", "duration_minutes": 30, "request_count": 100, "concurrency": 5},
        0,
    )
    assert definition.target_payload["burst"]["window_start"] == "2026-05-19T13:00:00Z"
    with pytest.raises(ValidationError):
        schedule_name(
            stage="dev/unsafe",
            client_id="client123",
            audit_id="audit456",
            schedule_type="baseline",
            scenario_type="baseline_health",
        )
