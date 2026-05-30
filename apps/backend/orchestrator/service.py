"""Generic config-driven Phase 1 orchestrator."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from typing import Any

from apps.backend.runner.api_runner import ApiRunner, RunnerOutcome
from packages.audit_scheduling.constants import (
    MAX_REPEATED_ITERATIONS,
    SCENARIO_BURST_STABILITY,
    SCENARIO_REPEATED_STABILITY,
)
from packages.audit_scheduling.safeguards import effective_caps
from packages.config.loaders import AuditConfigLoader, ClientConfigLoader, EndpointConfigLoader
from packages.config.validators import validate_audit_config, validate_endpoint_config
from packages.core.constants.engine import (
    LOG_CATEGORY_CLIENT_SAFE,
    LOG_CATEGORY_INTERNAL,
    RAW_RESULT_VERSION,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_STARTED,
)
from packages.core.exceptions import ConfigError, DuplicateRunIdError, EngineError
from packages.core.logging import StructuredLogger
from packages.core.time import utc_now_iso
from packages.core.validators import (
    IDENTIFIER_PATTERN,
    RUN_ID_PATTERN,
    OrchestratorEvent,
    validate_event,
)
from packages.data_generation.data_pools import DataPoolLoader
from packages.data_generation.duplicate_checker import DuplicateChecker
from packages.data_generation.generator import PayloadPreparationService, RunContext
from packages.sanitization.sanitizer import sanitize


@dataclass(frozen=True)
class ExecutionConfig:
    endpoints: list[dict[str, Any]]
    schedule_iteration_count: int
    audit_config: dict[str, Any]
    client_config: dict[str, Any]


@dataclass(frozen=True)
class BurstPlan:
    mode: str
    request_count: int
    concurrency: int
    window_id: str | None = None
    window_start: str | None = None


class CoreEngineOrchestrator:
    def __init__(
        self,
        *,
        s3_storage: Any,
        metadata_storage: Any,
        secrets_client: Any,
        runner: ApiRunner | None = None,
        logger: StructuredLogger | None = None,
    ):
        self.s3_storage = s3_storage
        self.metadata_storage = metadata_storage
        self.secrets_client = secrets_client
        self.runner = runner or ApiRunner()
        self.logger = logger or StructuredLogger()

    def run(self, event: dict[str, Any]) -> dict[str, Any]:
        started_item: dict[str, Any] | None = None
        raw_result_key: str | None = None
        try:
            self._log_milestone("event_validation_started", raw_event=event)
            try:
                validated = validate_event(event)
            except Exception as exc:
                self._log_milestone(
                    "event_validation_failed", raw_event=event, level="ERROR", exc=exc
                )
                raise
            self._log_milestone("event_validation_completed", event=validated)
            raw_result_key = self.s3_storage.build_raw_result_key(
                validated.client_id, validated.audit_id, validated.run_id
            )
            self._log_milestone("duplicate_preflight_started", event=validated)
            try:
                self._fail_if_duplicate(validated, raw_result_key)
            except Exception as exc:
                self._log_milestone(
                    "duplicate_preflight_failed", event=validated, level="ERROR", exc=exc
                )
                raise
            self._log_milestone("duplicate_preflight_completed", event=validated)
            started_item = self._started_item(validated)
            self._log_milestone("metadata_started_write_started", event=validated)
            try:
                self.metadata_storage.put_started_once(started_item)
            except Exception as exc:
                self._log_milestone(
                    "metadata_started_write_failed", event=validated, level="ERROR", exc=exc
                )
                raise
            self._log_milestone("metadata_started_write_completed", event=validated)
            self.logger.log(
                "run_started",
                log_category=LOG_CATEGORY_INTERNAL,
                client_id=validated.client_id,
                audit_id=validated.audit_id,
                run_id=validated.run_id,
                scenario_type=validated.scenario_type,
            )
            run_timestamp = utc_now_iso()
            duplicate_checker = DuplicateChecker(
                client_id=validated.client_id, audit_id=validated.audit_id, run_id=validated.run_id
            )
            run_context = RunContext(
                client_id=validated.client_id,
                audit_id=validated.audit_id,
                run_id=validated.run_id,
                scenario_type=validated.scenario_type,
                run_timestamp=run_timestamp,
            )
            payload_preparation = PayloadPreparationService(
                data_pool_loader=DataPoolLoader(self.s3_storage)
            )
            self._log_milestone("config_load_started", event=validated)
            try:
                execution_config = self._load_and_validate_configs(validated)
            except Exception as exc:
                self._log_milestone("config_load_failed", event=validated, level="ERROR", exc=exc)
                raise
            self._log_milestone(
                "config_load_completed",
                event=validated,
                endpoint_count=len(execution_config.endpoints),
                schedule_iteration_count=execution_config.schedule_iteration_count,
            )
            if validated.scenario_type == SCENARIO_BURST_STABILITY:
                burst_plan = self._resolve_burst_plan(validated, execution_config)
                results = self._execute_burst(
                    validated,
                    execution_config,
                    burst_plan,
                    run_context=run_context,
                    duplicate_checker=duplicate_checker,
                    payload_preparation=payload_preparation,
                )
            else:
                results = []
                schedule_iterations = self._schedule_iteration_numbers(
                    validated, execution_config.schedule_iteration_count
                )
                for schedule_iteration in schedule_iterations:
                    for endpoint in execution_config.endpoints:
                        payload_iteration_count = endpoint.get("payload_iterations", 1)
                        for payload_iteration in range(1, payload_iteration_count + 1):
                            endpoint_fields = {
                                "endpoint_id": endpoint.get("endpoint_id"),
                                "method": endpoint.get("method"),
                                "schedule_iteration": schedule_iteration,
                                "schedule_iteration_count": (
                                    execution_config.schedule_iteration_count
                                ),
                                "payload_iteration": payload_iteration,
                                "payload_iteration_count": payload_iteration_count,
                            }
                            self._log_milestone(
                                "endpoint_execution_started", event=validated, **endpoint_fields
                            )
                            try:
                                outcome = self.runner.execute(
                                    self._resolve(endpoint),
                                    run_context=run_context,
                                    duplicate_checker=duplicate_checker,
                                    payload_preparation=payload_preparation,
                                    iteration=payload_iteration,
                                )
                            except Exception as exc:
                                self._log_milestone(
                                    "endpoint_execution_failed",
                                    event=validated,
                                    level="ERROR",
                                    exc=exc,
                                    **endpoint_fields,
                                )
                                raise
                            self._log_milestone(
                                "endpoint_execution_completed",
                                event=validated,
                                failure_type=outcome.failure_type,
                                status_code=outcome.status_code,
                                **endpoint_fields,
                            )
                            results.append(
                                self._raw_result(
                                    validated,
                                    outcome,
                                    schedule_iteration_number=schedule_iteration,
                                    schedule_iteration_count=execution_config.schedule_iteration_count,
                                    payload_iteration_number=payload_iteration,
                                    payload_iteration_count=payload_iteration_count,
                                )
                            )
            envelope = sanitize(
                {
                    "raw_result_version": RAW_RESULT_VERSION,
                    "client_id": validated.client_id,
                    "audit_id": validated.audit_id,
                    "run_id": validated.run_id,
                    "results": results,
                }
            )
            self._log_milestone(
                "raw_result_write_started", event=validated, key_prefix="raw-results"
            )
            try:
                self.s3_storage.write_raw_results_once(raw_result_key, envelope)
            except Exception as exc:
                self._log_milestone(
                    "raw_result_write_failed", event=validated, level="ERROR", exc=exc
                )
                raise
            self._log_milestone(
                "raw_result_write_completed", event=validated, key_prefix="raw-results"
            )
            completed_at = utc_now_iso()
            self._log_milestone(
                "terminal_metadata_update_started",
                event=validated,
                terminal_status=RUN_STATUS_COMPLETED,
            )
            try:
                self.metadata_storage.update_terminal(
                    self.metadata_storage.keys(
                        validated.client_id, validated.audit_id, validated.run_id
                    ),
                    {
                        "status": RUN_STATUS_COMPLETED,
                        "completed_at": completed_at,
                        "raw_result_s3_key": raw_result_key,
                        "failure_summary": None,
                    },
                )
            except Exception as exc:
                self._log_milestone(
                    "terminal_metadata_update_failed",
                    event=validated,
                    level="ERROR",
                    exc=exc,
                    terminal_status=RUN_STATUS_COMPLETED,
                )
                raise
            self._log_milestone(
                "terminal_metadata_update_completed",
                event=validated,
                terminal_status=RUN_STATUS_COMPLETED,
            )
            self.logger.log(
                "run_completed",
                log_category=LOG_CATEGORY_CLIENT_SAFE,
                client_id=validated.client_id,
                audit_id=validated.audit_id,
                run_id=validated.run_id,
                scenario_type=validated.scenario_type,
                raw_result_version=RAW_RESULT_VERSION,
            )
            self._log_milestone("run_returning", event=validated, status=RUN_STATUS_COMPLETED)
            return sanitize(
                {
                    "client_id": validated.client_id,
                    "audit_id": validated.audit_id,
                    "run_id": validated.run_id,
                    "status": RUN_STATUS_COMPLETED,
                    "raw_result_s3_key": raw_result_key,
                }
            )
        except DuplicateRunIdError as exc:
            return self._failure_response(
                exc, event=locals().get("validated"), started_item=started_item, raw_event=event
            )
        except EngineError as exc:
            return self._failure_response(
                exc, event=locals().get("validated"), started_item=started_item, raw_event=event
            )
        except Exception as exc:  # top-level sanitized boundary
            error = EngineError("ORCHESTRATION_ERROR", "Orchestration failed")
            error.__cause__ = exc
            return self._failure_response(
                error, event=locals().get("validated"), started_item=started_item, raw_event=event
            )

    def _fail_if_duplicate(self, event: OrchestratorEvent, raw_result_key: str) -> None:
        if self.s3_storage.object_exists(raw_result_key) or self.metadata_storage.metadata_exists(
            event.client_id, event.audit_id, event.run_id
        ):
            self.logger.log(
                "duplicate_run_id",
                log_category=LOG_CATEGORY_INTERNAL,
                event_type="DUPLICATE_RUN_ID",
                client_id=event.client_id,
                audit_id=event.audit_id,
                run_id=event.run_id,
            )
            raise DuplicateRunIdError()

    def _load_and_validate_configs(self, event: OrchestratorEvent) -> ExecutionConfig:
        client_config = ClientConfigLoader(self.s3_storage).load(event.client_id)
        audit_config = AuditConfigLoader(self.s3_storage).load(event.client_id, event.audit_id)
        validate_audit_config(audit_config, event.audit_id)
        endpoint_config = EndpointConfigLoader(self.s3_storage).load(
            event.client_id, event.audit_id
        )
        endpoints = validate_endpoint_config(endpoint_config)
        return ExecutionConfig(
            endpoints=endpoints,
            schedule_iteration_count=self._resolve_schedule_iteration_count(event, audit_config),
            audit_config=audit_config,
            client_config=client_config,
        )

    def _resolve_burst_plan(
        self, event: OrchestratorEvent, execution_config: ExecutionConfig
    ) -> BurstPlan:
        caps = effective_caps(
            execution_config.audit_config.get("execution_environment"),
            audit_config=execution_config.audit_config,
            client_config=execution_config.client_config,
        )
        if event.triggered_by == "manual" and event.schedule_type in {None, "manual"}:
            defaults = (execution_config.audit_config.get("burst_schedule") or {}).get(
                "manual_burst_defaults"
            )
            if defaults is None:
                defaults = {"enabled": True, "request_count": 10, "concurrency": 2}
            if not isinstance(defaults, dict) or defaults.get("enabled") is not True:
                raise ConfigError("Manual burst defaults are disabled", "CONFIG_VALIDATION_ERROR")
            request_count = self._positive_int(
                defaults.get("request_count"), "Invalid burst request_count"
            )
            concurrency = self._positive_int(
                defaults.get("concurrency"), "Invalid burst concurrency"
            )
            return BurstPlan(
                mode="manual_fallback",
                request_count=min(request_count, caps["max_requests_per_run"]),
                concurrency=min(concurrency, caps["max_concurrency"]),
            )
        burst_schedule = execution_config.audit_config.get("burst_schedule") or {}
        windows = burst_schedule.get("windows") or []
        if (event.schedule_type == "burst" or event.triggered_by != "manual") and (
            burst_schedule.get("enabled") is not True or not windows or not event.burst
        ):
            raise ConfigError(
                "Scheduled burst requires enabled burst window metadata",
                "CONFIG_VALIDATION_ERROR",
            )
        request_count = self._positive_int(
            event.burst.get("request_count"), "Invalid burst request_count"
        )
        concurrency = self._positive_int(
            event.burst.get("concurrency"), "Invalid burst concurrency"
        )
        if request_count > caps["max_requests_per_run"] or concurrency > caps["max_concurrency"]:
            raise ConfigError("Burst cap exceeded", "CONFIG_VALIDATION_ERROR")
        return BurstPlan(
            mode="scheduled_window",
            request_count=request_count,
            concurrency=concurrency,
            window_id=event.burst.get("window_id"),
            window_start=event.burst.get("window_start"),
        )

    def _positive_int(self, value: Any, message: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ConfigError(message, "CONFIG_VALIDATION_ERROR")
        return value

    def _execute_burst(
        self,
        event: OrchestratorEvent,
        execution_config: ExecutionConfig,
        burst_plan: BurstPlan,
        *,
        run_context: RunContext,
        duplicate_checker: DuplicateChecker,
        payload_preparation: PayloadPreparationService,
    ) -> list[dict[str, Any]]:
        request_plan = [
            (
                request_number,
                execution_config.endpoints[(request_number - 1) % len(execution_config.endpoints)],
            )
            for request_number in range(1, burst_plan.request_count + 1)
        ]

        def execute_one(request_number: int, endpoint: dict[str, Any]) -> tuple[int, RunnerOutcome]:
            endpoint_fields = {
                "endpoint_id": endpoint.get("endpoint_id"),
                "method": endpoint.get("method"),
                "burst_request_number": request_number,
                "burst_request_count": burst_plan.request_count,
                "burst_concurrency": burst_plan.concurrency,
            }
            self._log_milestone("burst_request_started", event=event, **endpoint_fields)
            try:
                outcome = self.runner.execute(
                    self._resolve(endpoint),
                    run_context=run_context,
                    duplicate_checker=duplicate_checker,
                    payload_preparation=payload_preparation,
                    iteration=request_number,
                )
            except Exception as exc:
                self._log_milestone(
                    "burst_request_failed", event=event, level="ERROR", exc=exc, **endpoint_fields
                )
                raise
            self._log_milestone(
                "burst_request_completed",
                event=event,
                failure_type=outcome.failure_type,
                status_code=outcome.status_code,
                **endpoint_fields,
            )
            return request_number, outcome

        outcomes: dict[int, RunnerOutcome] = {}
        with ThreadPoolExecutor(max_workers=burst_plan.concurrency) as executor:
            futures = [
                executor.submit(execute_one, number, endpoint) for number, endpoint in request_plan
            ]
            for future in as_completed(futures):
                number, outcome = future.result()
                outcomes[number] = outcome
        return [
            self._raw_result(
                event,
                outcomes[number],
                schedule_iteration_number=number,
                schedule_iteration_count=burst_plan.request_count,
                payload_iteration_number=1,
                payload_iteration_count=1,
                burst_plan=burst_plan,
                burst_request_number=number,
            )
            for number in range(1, burst_plan.request_count + 1)
        ]

    def _resolve_schedule_iteration_count(
        self, event: OrchestratorEvent, audit_config: dict[str, Any]
    ) -> int:
        if event.scenario_type != SCENARIO_REPEATED_STABILITY:
            return 1
        if event.schedule_iteration_count is not None:
            self._validate_schedule_iteration_count(event.schedule_iteration_count)
            if (
                event.schedule_iteration_number is not None
                and event.schedule_iteration_number > event.schedule_iteration_count
            ):
                raise ConfigError(
                    "Repeated iteration exceeds iteration count", "CONFIG_VALIDATION_ERROR"
                )
            return event.schedule_iteration_count
        repeated_schedule = audit_config.get("repeated_schedule")
        if isinstance(repeated_schedule, list):
            repeated_schedule = next(
                (
                    schedule
                    for schedule in repeated_schedule
                    if isinstance(schedule, dict)
                    and schedule.get("scenario_type", SCENARIO_REPEATED_STABILITY)
                    == SCENARIO_REPEATED_STABILITY
                ),
                None,
            )
        if not isinstance(repeated_schedule, dict):
            raise ConfigError("Missing repeated_schedule", "CONFIG_VALIDATION_ERROR")
        iteration_count = repeated_schedule.get("iteration_count")
        self._validate_schedule_iteration_count(iteration_count)
        if (
            event.schedule_iteration_number is not None
            and event.schedule_iteration_number > iteration_count
        ):
            raise ConfigError(
                "Repeated iteration exceeds iteration count", "CONFIG_VALIDATION_ERROR"
            )
        return iteration_count

    def _validate_schedule_iteration_count(self, iteration_count: Any) -> None:
        if (
            not isinstance(iteration_count, int)
            or isinstance(iteration_count, bool)
            or iteration_count <= 0
        ):
            raise ConfigError("Invalid repeated iteration_count", "CONFIG_VALIDATION_ERROR")
        if iteration_count > MAX_REPEATED_ITERATIONS:
            raise ConfigError("Repeated iteration cap exceeded", "CONFIG_VALIDATION_ERROR")

    def _schedule_iteration_numbers(
        self, event: OrchestratorEvent, schedule_iteration_count: int
    ) -> range:
        if event.schedule_iteration_number is not None:
            return range(event.schedule_iteration_number, event.schedule_iteration_number + 1)
        return range(1, schedule_iteration_count + 1)

    def _log_milestone(
        self,
        message: str,
        *,
        event: OrchestratorEvent | None = None,
        raw_event: Any | None = None,
        level: str = "INFO",
        exc: Exception | None = None,
        **fields: Any,
    ) -> None:
        log_fields: dict[str, Any] = {**fields}
        if event is not None:
            log_fields.update(
                {
                    "client_id": event.client_id,
                    "audit_id": event.audit_id,
                    "run_id": event.run_id,
                    "scenario_type": event.scenario_type,
                }
            )
        elif isinstance(raw_event, dict):
            scenario_type = raw_event.get("scenario_type")
            if not isinstance(scenario_type, str) and isinstance(raw_event.get("detail"), dict):
                scenario_type = raw_event["detail"].get("scenario_type")
            if isinstance(scenario_type, str) and IDENTIFIER_PATTERN.fullmatch(scenario_type):
                log_fields["scenario_type"] = scenario_type[:120]
            log_fields["input_type"] = "dict"
        elif raw_event is not None:
            log_fields["input_type"] = type(raw_event).__name__
        if exc is not None:
            error_type = getattr(exc, "error_type", type(exc).__name__)
            error_message = getattr(exc, "message", "Orchestrator milestone failed")
            log_fields.update(
                {
                    "error_type": error_type,
                    "error_message": error_message,
                }
            )
        self.logger.log(message, log_category=LOG_CATEGORY_INTERNAL, level=level, **log_fields)

    def _resolve(self, endpoint: dict[str, Any]) -> dict[str, Any]:
        resolved = {**endpoint, "headers": dict(endpoint.get("headers") or {})}
        for key, value in list(resolved["headers"].items()):
            if isinstance(value, dict) and "secret_ref" in value:
                resolved["headers"][key] = self.secrets_client.resolve(value)
        return resolved

    def _raw_result(
        self,
        event: OrchestratorEvent,
        outcome: RunnerOutcome,
        *,
        schedule_iteration_number: int,
        schedule_iteration_count: int,
        payload_iteration_number: int,
        payload_iteration_count: int,
        burst_plan: BurstPlan | None = None,
        burst_request_number: int | None = None,
    ) -> dict[str, Any]:
        record = {
            "raw_result_version": RAW_RESULT_VERSION,
            "client_id": event.client_id,
            "audit_id": event.audit_id,
            "run_id": event.run_id,
            "scenario_type": event.scenario_type,
            "iteration_number": schedule_iteration_number,
            "iteration_count": schedule_iteration_count,
            "schedule_iteration_number": schedule_iteration_number,
            "schedule_iteration_count": schedule_iteration_count,
            "payload_iteration_number": payload_iteration_number,
            "payload_iteration_count": payload_iteration_count,
            **asdict(outcome),
        }
        if burst_plan is not None:
            record.update(
                {
                    "burst_mode": burst_plan.mode,
                    "burst_request_number": burst_request_number,
                    "burst_request_count": burst_plan.request_count,
                    "burst_concurrency": burst_plan.concurrency,
                    "burst_window_id": burst_plan.window_id,
                    "burst_window_start": burst_plan.window_start,
                }
            )
        return sanitize(record)

    def _started_item(self, event: OrchestratorEvent) -> dict[str, Any]:
        started_at = utc_now_iso()
        return sanitize(
            {
                **self.metadata_storage.keys(event.client_id, event.audit_id, event.run_id),
                "client_id": event.client_id,
                "audit_id": event.audit_id,
                "run_id": event.run_id,
                "scenario_type": event.scenario_type,
                "triggered_by": event.triggered_by,
                "status": RUN_STATUS_STARTED,
                "raw_result_s3_key": None,
                "raw_result_version": RAW_RESULT_VERSION,
                "started_at": started_at,
                "completed_at": None,
                "failure_summary": None,
            }
        )

    def _failure_response(
        self,
        exc: EngineError,
        *,
        event: OrchestratorEvent | None,
        started_item: dict[str, Any] | None,
        raw_event: Any | None = None,
    ) -> dict[str, Any]:
        failure_summary = {"error_type": exc.error_type, "message": exc.message}
        if event and started_item:
            try:
                self._log_milestone(
                    "terminal_metadata_update_started",
                    event=event,
                    terminal_status=RUN_STATUS_FAILED,
                )
                self.metadata_storage.update_terminal(
                    self.metadata_storage.keys(event.client_id, event.audit_id, event.run_id),
                    {
                        "status": RUN_STATUS_FAILED,
                        "completed_at": utc_now_iso(),
                        "failure_summary": failure_summary,
                    },
                )
                self._log_milestone(
                    "terminal_metadata_update_completed",
                    event=event,
                    terminal_status=RUN_STATUS_FAILED,
                )
            except Exception as metadata_exc:
                self._log_milestone(
                    "terminal_metadata_update_failed",
                    event=event,
                    level="ERROR",
                    exc=metadata_exc,
                    terminal_status=RUN_STATUS_FAILED,
                )
        event_fields = (
            {
                "client_id": event.client_id,
                "audit_id": event.audit_id,
                "run_id": event.run_id,
                "scenario_type": event.scenario_type,
            }
            if event
            else self._safe_raw_correlation_fields(raw_event)
        )
        self.logger.log(
            "run_failed",
            log_category=LOG_CATEGORY_CLIENT_SAFE,
            level="ERROR",
            event_type=exc.error_type,
            **event_fields,
            failure_summary=failure_summary,
        )
        if event:
            self._log_milestone(
                "run_returning", event=event, level="ERROR", status=RUN_STATUS_FAILED
            )
        else:
            self.logger.log(
                "run_returning",
                log_category=LOG_CATEGORY_INTERNAL,
                level="ERROR",
                status=RUN_STATUS_FAILED,
                **event_fields,
            )
        return sanitize(
            {
                **event_fields,
                "status": RUN_STATUS_FAILED,
                "failure_summary": failure_summary,
            }
        )

    def _safe_raw_correlation_fields(self, raw_event: Any | None) -> dict[str, str]:
        if not isinstance(raw_event, dict):
            return {}
        source = raw_event.get("detail") if isinstance(raw_event.get("detail"), dict) else raw_event
        fields: dict[str, str] = {}
        for name in ("client_id", "audit_id", "scenario_type"):
            value = source.get(name)
            if isinstance(value, str) and IDENTIFIER_PATTERN.fullmatch(value):
                fields[name] = value
        run_id = source.get("run_id")
        if isinstance(run_id, str) and RUN_ID_PATTERN.fullmatch(run_id):
            fields["run_id"] = run_id
        return fields
