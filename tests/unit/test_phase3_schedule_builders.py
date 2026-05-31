import pytest

from packages.audit_scheduling.builders import (
    ScheduleBuilder,
    eventbridge_scheduler_at_datetime,
    schedule_name,
)
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
    window = {"start_time": "2026-05-19T00:00:00Z", "end_time": "2026-05-19T00:30:00Z"}
    definitions = ScheduleBuilder(stage="dev").build_baseline(config, window)
    assert [definition.expression for definition in definitions] == [
        "at(2026-05-19T00:00:00)",
        "at(2026-05-19T00:15:00)",
    ]
    assert all("run_id" not in definition.target_payload for definition in definitions)
    occurrence_ids = [
        definition.target_payload["schedule_occurrence_id"] for definition in definitions
    ]
    assert occurrence_ids == [
        "client123:audit456:baseline:baseline_health:2026-05-19T00:00:00Z",
        "client123:audit456:baseline:baseline_health:2026-05-19T00:15:00Z",
    ]
    assert len({definition.name for definition in definitions}) == 2


def test_baseline_occurrence_ids_are_distinct_and_deterministic():
    config = {"client_id": "client123", "audit_id": "audit456"}
    window = {"start_time": "2026-05-19T00:00:00Z", "end_time": "2026-05-19T00:30:00Z"}
    first = ScheduleBuilder(stage="dev").build_baseline(config, window)
    second = ScheduleBuilder(stage="dev").build_baseline(config, window)
    first_ids = [definition.target_payload["schedule_occurrence_id"] for definition in first]
    second_ids = [definition.target_payload["schedule_occurrence_id"] for definition in second]
    assert first_ids == second_ids
    assert len(set(first_ids)) == 2


def test_baseline_cadence_guardrail_rejects_explosive_schedule_count():
    config = {"client_id": "client123", "audit_id": "audit456", "baseline": {"interval_minutes": 1}}
    window = {"start_time": "2026-05-19T00:00:00Z", "end_time": "2026-05-19T04:00:00Z"}
    with pytest.raises(ValidationError) as exc:
        ScheduleBuilder(stage="dev").build_baseline(config, window)
    assert exc.value.error_type == "CAP_EXCEEDED"


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


def test_scheduler_at_formatter_strips_microseconds_and_timezone_suffix_for_utc():
    assert (
        eventbridge_scheduler_at_datetime(
            "2026-05-30T12:03:37.080790Z", schedule_expression_timezone="UTC"
        )
        == "2026-05-30T12:03:37"
    )


def test_burst_schedule_uses_timezone_metadata_without_expression_suffix():
    config = {"client_id": "client123", "audit_id": "audit456"}
    window = {
        "start_time": "2026-05-30T00:00:00.080790Z",
        "end_time": "2026-06-01T00:00:00.080790Z",
        "timezone": "Asia/Hong_Kong",
    }

    definition = ScheduleBuilder(stage="dev").build_burst(
        config,
        window,
        {"start_time": "09:00", "duration_minutes": 30, "request_count": 10, "concurrency": 2},
        0,
    )

    assert definition.expression == "at(2026-05-30T09:00:00)"
    assert definition.schedule_expression_timezone == "Asia/Hong_Kong"
    assert definition.metadata["schedule_expression_timezone"] == "Asia/Hong_Kong"
    assert "." not in definition.expression
    assert not definition.expression.endswith("Z)")


def test_finalization_expression_strips_microseconds_and_z_suffix():
    config = {"client_id": "client123", "audit_id": "audit456"}
    window = {
        "start_time": "2026-05-30T00:00:00.080790Z",
        "end_time": "2026-05-30T12:03:37.080790Z",
    }

    definition = ScheduleBuilder(stage="dev").build_finalization(config, window)

    assert definition.expression == "at(2026-05-30T12:03:37)"
    assert definition.schedule_expression_timezone == "UTC"
    assert definition.target_payload["audit_window_end"] == "2026-05-30T12:03:37.080790Z"


def test_burst_expression_strips_timezone_suffix():
    config = {"client_id": "client123", "audit_id": "audit456"}
    window = {
        "start_time": "2026-05-30T00:00:00.080790Z",
        "end_time": "2026-06-01T00:00:00.080790Z",
    }

    definition = ScheduleBuilder(stage="dev").build_burst(
        config,
        window,
        {"start_time": "12:03", "duration_minutes": 30, "request_count": 10, "concurrency": 2},
        0,
    )

    assert definition.expression == "at(2026-05-30T12:03:00)"
    assert "." not in definition.expression
    assert not definition.expression.endswith("Z)")


@pytest.mark.parametrize(
    ("schedule_time", "expected_expression"),
    [
        ("2026-05-30T12:03:37.080790Z", "at(2026-05-30T12:03:37)"),
        ("2026-05-30T12:03:37Z", "at(2026-05-30T12:03:37)"),
        ("2026-05-30T12:03:37+00:00", "at(2026-05-30T12:03:37)"),
        ("2026-05-30T12:03:37", "at(2026-05-30T12:03:37)"),
    ],
)
def test_repeated_expression_handles_supported_datetime_forms(schedule_time, expected_expression):
    config = {"client_id": "client123", "audit_id": "audit456"}
    window = {"start_time": "2026-05-30T00:00:00Z", "end_time": "2026-06-01T00:00:00Z"}

    definition = ScheduleBuilder(stage="dev").build_repeated(
        config,
        window,
        {"schedule_time": schedule_time, "iteration_count": 3},
        0,
    )

    assert definition.expression == expected_expression
    assert definition.target_payload["scheduled_at"] == schedule_time
