"""Schedule definition builders for EventBridge Scheduler."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from packages.audit_scheduling.constants import (
    BASELINE_DEFAULT_INTERVAL_MINUTES,
    SCENARIO_BASELINE_HEALTH,
    SCENARIO_BURST_STABILITY,
    SCENARIO_REPEATED_STABILITY,
    SCHEDULE_TYPE_BASELINE,
    SCHEDULE_TYPE_BURST,
    SCHEDULE_TYPE_FINALIZATION,
    SCHEDULE_TYPE_REPEATED,
)
from packages.audit_scheduling.safeguards import isoformat_z, parse_iso_datetime
from packages.audit_scheduling.taxonomy import reliability_category_for, validate_scenario_type
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
            definitions.append(self.build_baseline(config, audit_window))
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
    ) -> ScheduleDefinition:
        baseline = config.get("baseline") or {}
        scenario_type = validate_scenario_type(
            baseline.get("scenario_type", SCENARIO_BASELINE_HEALTH)
        )
        interval = baseline.get("interval_minutes", BASELINE_DEFAULT_INTERVAL_MINUTES)
        if not isinstance(interval, int) or interval <= 0:
            raise ValidationError("Invalid baseline interval", "INVALID_SCHEDULE_CONFIG")
        name, suffix = schedule_name(
            stage=self.stage,
            client_id=config["client_id"],
            audit_id=config["audit_id"],
            schedule_type=SCHEDULE_TYPE_BASELINE,
            scenario_type=scenario_type,
            stable_config=baseline,
            name_prefix=self.name_prefix,
        )
        scheduled_at = audit_window["start_time"]
        payload = self._execution_payload(
            config, name, SCHEDULE_TYPE_BASELINE, scenario_type, scheduled_at
        )
        return self._definition(
            name,
            SCHEDULE_TYPE_BASELINE,
            scenario_type,
            f"rate({interval} minutes)",
            payload,
            suffix,
        )

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
            "window_start": isoformat_z(start),
            "window_end": isoformat_z(end),
        }
        return self._definition(
            name, SCHEDULE_TYPE_BURST, scenario_type, f"at({isoformat_z(start)})", payload, suffix
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
        return self._definition(
            name, SCHEDULE_TYPE_REPEATED, scenario_type, f"at({scheduled_at})", payload, suffix
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
        return self._definition(
            name,
            SCHEDULE_TYPE_FINALIZATION,
            "finalization",
            f"at({audit_window['end_time']})",
            payload,
            suffix,
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
        occurrence_id = f"{schedule_type}#{scheduled_at}"
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

    def _definition(
        self,
        name: str,
        schedule_type: str,
        scenario_type: str,
        expression: str,
        payload: dict[str, Any],
        hash_suffix: str | None,
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
            "target_handler": "audit_finalization_handler"
            if schedule_type == SCHEDULE_TYPE_FINALIZATION
            else "scheduled_execution_handler",
            "name_hash_suffix": hash_suffix,
        }
        return ScheduleDefinition(name, schedule_type, scenario_type, expression, payload, metadata)

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
