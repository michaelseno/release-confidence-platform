"""Schedule definition builders for EventBridge Scheduler."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from packages.audit_scheduling.constants import (
    BASELINE_DEFAULT_INTERVAL_MINUTES,
    MAX_BASELINE_OCCURRENCES_PER_AUDIT,
    SCENARIO_BASELINE_HEALTH,
    SCENARIO_BURST_STABILITY,
    SCENARIO_REPEATED_STABILITY,
    SCHEDULE_TYPE_BASELINE,
    SCHEDULE_TYPE_BURST,
    SCHEDULE_TYPE_FINALIZATION,
    SCHEDULE_TYPE_REPEATED,
)
from packages.audit_scheduling.safeguards import isoformat_z, parse_iso_datetime
from packages.audit_scheduling.taxonomy import (
    reliability_category_for,
    validate_scenario_type,
)
from packages.core.exceptions import ValidationError
from packages.core.validators import validate_identifier

AWS_SCHEDULER_NAME_MAX_LENGTH = 64


@dataclass(frozen=True)
class ScheduleDefinition:
    name: str
    schedule_type: str
    scenario_type: str
    expression: str
    target_payload: dict[str, Any]
    metadata: dict[str, Any]
    schedule_expression_timezone: str | None = None


def eventbridge_scheduler_at_datetime(
    value: str | datetime, *, schedule_expression_timezone: str | None = None
) -> str:
    """Format an EventBridge Scheduler at() datetime without fractions or timezone suffix."""

    parsed = parse_iso_datetime(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if schedule_expression_timezone:
        parsed = parsed.astimezone(ZoneInfo(schedule_expression_timezone))
    return parsed.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def schedule_name(
    *,
    stage: str,
    client_id: str,
    audit_id: str,
    schedule_type: str,
    scenario_type: str | None = None,
    stable_config: dict[str, Any] | None = None,
    name_prefix: str | None = None,
    max_length: int = AWS_SCHEDULER_NAME_MAX_LENGTH,
) -> tuple[str, str | None]:
    stage = validate_identifier("stage", stage)
    client_id = validate_identifier("client_id", client_id)
    audit_id = validate_identifier("audit_id", audit_id)
    prefix = name_prefix or f"rcp-{stage}"
    if schedule_type == SCHEDULE_TYPE_FINALIZATION:
        full_name = f"{prefix}-{client_id}-{audit_id}-finalization"
    else:
        scenario_type = validate_scenario_type(scenario_type or "")
        full_name = f"{prefix}-{client_id}-{audit_id}-{schedule_type}-{scenario_type}"
    if len(full_name) <= max_length:
        return full_name, None
    hash_input = json.dumps(
        {"name": full_name, "stable_config": stable_config or {}}, sort_keys=True, default=str
    )
    suffix = _stable_hash(hash_input)
    prefix_length = max_length - len(suffix) - 1
    if prefix_length < 8:
        raise ValidationError("Schedule name max length too small", "INVALID_SCHEDULE_NAME")
    return f"{full_name[:prefix_length]}-{suffix}", suffix


class ScheduleBuilder:
    def __init__(self, *, stage: str, name_prefix: str | None = None):
        self.stage = validate_identifier("stage", stage)
        self.name_prefix = name_prefix

    def build_all(
        self, config: dict[str, Any], audit_window: dict[str, Any]
    ) -> list[ScheduleDefinition]:
        definitions: list[ScheduleDefinition] = []
        if config.get("baseline", {"enabled": True}).get("enabled", True):
            definitions.extend(self.build_baseline(config, audit_window))
        for index, window in enumerate((config.get("burst_schedule") or {}).get("windows", [])):
            if (config.get("burst_schedule") or {}).get("enabled"):
                definitions.append(self.build_burst(config, audit_window, window, index))
        for index, repeated in enumerate(config.get("repeated") or []):
            if repeated.get("enabled", True):
                definitions.append(self.build_repeated(config, audit_window, repeated, index))
        if (config.get("finalization_schedule") or {"enabled": True}).get("enabled", True):
            definitions.append(self.build_finalization(config, audit_window))
        return definitions

    def build_baseline(
        self, config: dict[str, Any], audit_window: dict[str, Any]
    ) -> list[ScheduleDefinition]:
        baseline = config.get("baseline") or {}
        scenario_type = validate_scenario_type(
            baseline.get("scenario_type", SCENARIO_BASELINE_HEALTH)
        )
        interval = baseline.get("interval_minutes", BASELINE_DEFAULT_INTERVAL_MINUTES)
        if not isinstance(interval, int) or interval <= 0:
            raise ValidationError("Invalid baseline interval", "INVALID_SCHEDULE_CONFIG")
        occurrence_times = self._baseline_occurrence_times(audit_window, interval)
        if len(occurrence_times) > MAX_BASELINE_OCCURRENCES_PER_AUDIT:
            # Guardrail: the approved audit window is bounded to 48 hours and the default
            # 15-minute cadence yields 192 baseline schedules. Reject smaller cadences that
            # would unexpectedly expand per-audit EventBridge Scheduler resource usage.
            raise ValidationError("Baseline occurrence cap exceeded", "CAP_EXCEEDED")
        expression_timezone = self._schedule_expression_timezone(audit_window)
        definitions: list[ScheduleDefinition] = []
        for scheduled_at_dt in occurrence_times:
            scheduled_at = isoformat_z(scheduled_at_dt)
            occurrence_token = scheduled_at_dt.strftime("%Y%m%dT%H%M%SZ")
            name, suffix = schedule_name(
                stage=self.stage,
                client_id=config["client_id"],
                audit_id=config["audit_id"],
                schedule_type=SCHEDULE_TYPE_BASELINE,
                scenario_type=scenario_type,
                stable_config={**baseline, "scheduled_at": scheduled_at},
                name_prefix=self.name_prefix,
            )
            if suffix is None:
                name, suffix = schedule_name(
                    stage=self.stage,
                    client_id=config["client_id"],
                    audit_id=config["audit_id"],
                    schedule_type=SCHEDULE_TYPE_BASELINE,
                    scenario_type=scenario_type,
                    stable_config={**baseline, "scheduled_at": scheduled_at},
                    name_prefix=f"{self.name_prefix or f'rcp-{self.stage}'}-{occurrence_token}",
                )
            payload = self._execution_payload(
                config, name, SCHEDULE_TYPE_BASELINE, scenario_type, scheduled_at
            )
            expression_time = eventbridge_scheduler_at_datetime(
                scheduled_at_dt, schedule_expression_timezone=expression_timezone
            )
            definitions.append(
                self._definition(
                    name,
                    SCHEDULE_TYPE_BASELINE,
                    scenario_type,
                    f"at({expression_time})",
                    payload,
                    suffix,
                    schedule_expression_timezone=expression_timezone,
                )
            )
        return definitions

    def build_burst(
        self,
        config: dict[str, Any],
        audit_window: dict[str, Any],
        window: dict[str, Any],
        index: int,
    ) -> ScheduleDefinition:
        scenario_type = validate_scenario_type(
            window.get("scenario_type", SCENARIO_BURST_STABILITY)
        )
        start, end = self._burst_window_times(audit_window, window)
        name, suffix = schedule_name(
            stage=self.stage,
            client_id=config["client_id"],
            audit_id=config["audit_id"],
            schedule_type=SCHEDULE_TYPE_BURST,
            scenario_type=scenario_type,
            stable_config={**window, "index": index},
            name_prefix=self.name_prefix,
        )
        payload = self._execution_payload(
            config,
            name,
            SCHEDULE_TYPE_BURST,
            scenario_type,
            isoformat_z(start),
            occurrence_suffix=str(index),
        )
        payload["burst"] = {
            "request_count": window["request_count"],
            "concurrency": window["concurrency"],
            "window_id": window.get("window_id") or window.get("id"),
            "window_start": isoformat_z(start),
            "window_end": isoformat_z(end),
        }
        expression_timezone = self._schedule_expression_timezone(audit_window)
        expression_time = eventbridge_scheduler_at_datetime(
            start, schedule_expression_timezone=expression_timezone
        )
        return self._definition(
            name,
            SCHEDULE_TYPE_BURST,
            scenario_type,
            f"at({expression_time})",
            payload,
            suffix,
            schedule_expression_timezone=expression_timezone,
        )

    def build_repeated(
        self,
        config: dict[str, Any],
        audit_window: dict[str, Any],
        repeated: dict[str, Any],
        index: int,
    ) -> ScheduleDefinition:
        scenario_type = validate_scenario_type(
            repeated.get("scenario_type", SCENARIO_REPEATED_STABILITY)
        )
        scheduled_at = repeated.get("schedule_time", audit_window["start_time"])
        name, suffix = schedule_name(
            stage=self.stage,
            client_id=config["client_id"],
            audit_id=config["audit_id"],
            schedule_type=SCHEDULE_TYPE_REPEATED,
            scenario_type=scenario_type,
            stable_config={**repeated, "index": index},
            name_prefix=self.name_prefix,
        )
        payload = self._execution_payload(
            config,
            name,
            SCHEDULE_TYPE_REPEATED,
            scenario_type,
            scheduled_at,
            occurrence_suffix=str(index),
        )
        payload["repeated"] = {
            "iteration_count": repeated["iteration_count"],
            "execution_mode": "sequential",
        }
        expression_timezone = self._schedule_expression_timezone(audit_window)
        expression_time = eventbridge_scheduler_at_datetime(
            scheduled_at, schedule_expression_timezone=expression_timezone
        )
        return self._definition(
            name,
            SCHEDULE_TYPE_REPEATED,
            scenario_type,
            f"at({expression_time})",
            payload,
            suffix,
            schedule_expression_timezone=expression_timezone,
        )

    def build_finalization(
        self, config: dict[str, Any], audit_window: dict[str, Any]
    ) -> ScheduleDefinition:
        name, suffix = schedule_name(
            stage=self.stage,
            client_id=config["client_id"],
            audit_id=config["audit_id"],
            schedule_type=SCHEDULE_TYPE_FINALIZATION,
            stable_config=audit_window,
            name_prefix=self.name_prefix,
        )
        payload = {
            "event_type": "audit_finalization",
            "schema_version": "phase3.finalization_event.v1",
            "client_id": config["client_id"],
            "audit_id": config["audit_id"],
            "schedule_name": name,
            "triggered_by": "eventbridge_scheduler",
            "audit_window_end": audit_window["end_time"],
            "schedule_occurrence_id": f"finalization#{audit_window['end_time']}",
        }
        expression_timezone = self._schedule_expression_timezone(audit_window)
        expression_time = eventbridge_scheduler_at_datetime(
            audit_window["end_time"], schedule_expression_timezone=expression_timezone
        )
        return self._definition(
            name,
            SCHEDULE_TYPE_FINALIZATION,
            "finalization",
            f"at({expression_time})",
            payload,
            suffix,
            schedule_expression_timezone=expression_timezone,
        )

    def _execution_payload(
        self,
        config: dict[str, Any],
        name: str,
        schedule_type: str,
        scenario_type: str,
        scheduled_at: str,
        *,
        occurrence_suffix: str | None = None,
    ) -> dict[str, Any]:
        occurrence_id = self._occurrence_id(
            config=config,
            schedule_type=schedule_type,
            scenario_type=scenario_type,
            scheduled_at=scheduled_at,
        )
        if occurrence_suffix:
            occurrence_id = f"{occurrence_id}#{occurrence_suffix}"
        return {
            "event_type": "audit_schedule_execution",
            "schema_version": "phase3.schedule_event.v1",
            "client_id": config["client_id"],
            "audit_id": config["audit_id"],
            "schedule_name": name,
            "schedule_type": schedule_type,
            "scenario_type": scenario_type,
            "triggered_by": "eventbridge_scheduler",
            "schedule_occurrence_id": occurrence_id,
            "scheduled_at": scheduled_at,
            "burst": None,
            "repeated": None,
        }

    def _occurrence_id(
        self,
        *,
        config: dict[str, Any],
        schedule_type: str,
        scenario_type: str,
        scheduled_at: str,
    ) -> str:
        canonical = ":".join(
            [config["client_id"], config["audit_id"], schedule_type, scenario_type, scheduled_at]
        )
        if len(canonical) <= 256:
            return canonical
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"occurrence:{_stable_hash(canonical)}:{digest}"

    def _baseline_occurrence_times(
        self, audit_window: dict[str, Any], interval_minutes: int
    ) -> list[datetime]:
        start = parse_iso_datetime(audit_window["start_time"])
        end = parse_iso_datetime(audit_window["end_time"])
        current = start
        occurrences: list[datetime] = []
        while current < end:
            occurrences.append(current)
            current = current + timedelta(minutes=interval_minutes)
        if not occurrences:
            raise ValidationError(
                "No baseline occurrences in audit window", "INVALID_SCHEDULE_CONFIG"
            )
        return occurrences

    def _definition(
        self,
        name: str,
        schedule_type: str,
        scenario_type: str,
        expression: str,
        payload: dict[str, Any],
        hash_suffix: str | None,
        *,
        schedule_expression_timezone: str | None = None,
    ) -> ScheduleDefinition:
        if "run_id" in payload:
            raise ValidationError("Schedule payload must omit run_id", "INVALID_SCHEDULE_EVENT")
        metadata = {
            "stage": self.stage,
            "schedule_name": name,
            "schedule_group": None,
            "schedule_type": schedule_type,
            "scenario_type": scenario_type,
            "reliability_category": reliability_category_for(scenario_type)
            if scenario_type != "finalization"
            else None,
            "status": "planned",
            "schedule_expression_summary": expression,
            "schedule_expression_timezone": schedule_expression_timezone,
            "target_handler": "audit_finalization_handler"
            if schedule_type == SCHEDULE_TYPE_FINALIZATION
            else "scheduled_execution_handler",
            "name_hash_suffix": hash_suffix,
        }
        return ScheduleDefinition(
            name,
            schedule_type,
            scenario_type,
            expression,
            payload,
            metadata,
            schedule_expression_timezone,
        )

    def _schedule_expression_timezone(self, audit_window: dict[str, Any]) -> str:
        return str(audit_window.get("timezone") or "UTC")

    def _burst_window_times(
        self, audit_window: dict[str, Any], window: dict[str, Any]
    ) -> tuple[datetime, datetime]:
        for field in ("duration_minutes", "request_count", "concurrency"):
            if not isinstance(window.get(field), int) or window[field] <= 0:
                raise ValidationError("Invalid burst window", "INVALID_SCHEDULE_CONFIG")
        hour, minute = [int(part) for part in window["start_time"].split(":", 1)]
        tz = ZoneInfo(audit_window.get("timezone") or "UTC")
        # Interpret configured HH:MM in the audit timezone on the audit start calendar date.
        # The audit start date is taken from the configured UTC audit boundary for deterministic
        # scheduling even when the local offset falls on the prior evening.
        audit_start = parse_iso_datetime(audit_window["start_time"])
        local_start = datetime.combine(audit_start.date(), time(hour, minute), tzinfo=tz)
        local_end = local_start + timedelta(minutes=window["duration_minutes"])
        start = local_start.astimezone(parse_iso_datetime(audit_window["start_time"]).tzinfo)
        end = local_end.astimezone(parse_iso_datetime(audit_window["start_time"]).tzinfo)
        audit_start_utc = parse_iso_datetime(audit_window["start_time"])
        audit_end_utc = parse_iso_datetime(audit_window["end_time"])
        if start < audit_start_utc or end > audit_end_utc:
            raise ValidationError("Burst window outside audit window", "INVALID_SCHEDULE_CONFIG")
        return start, end
