"""Generic config-driven Phase 1 orchestrator."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from apps.backend.runner.api_runner import ApiRunner, RunnerOutcome
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
from packages.core.exceptions import DuplicateRunIdError, EngineError
from packages.core.logging import StructuredLogger
from packages.core.time import utc_now_iso
from packages.core.validators import OrchestratorEvent, validate_event
from packages.sanitization.sanitizer import sanitize


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
            validated = validate_event(event)
            raw_result_key = self.s3_storage.build_raw_result_key(
                validated.client_id, validated.audit_id, validated.run_id
            )
            self._fail_if_duplicate(validated, raw_result_key)
            started_item = self._started_item(validated)
            self.metadata_storage.put_started_once(started_item)
            self.logger.log(
                "run_started",
                log_category=LOG_CATEGORY_INTERNAL,
                client_id=validated.client_id,
                audit_id=validated.audit_id,
                run_id=validated.run_id,
                scenario_type=validated.scenario_type,
            )
            endpoints = self._load_and_validate_configs(validated)
            results = [
                self._raw_result(validated, self.runner.execute(self._resolve(endpoint)))
                for endpoint in endpoints
            ]
            envelope = sanitize(
                {
                    "raw_result_version": RAW_RESULT_VERSION,
                    "client_id": validated.client_id,
                    "audit_id": validated.audit_id,
                    "run_id": validated.run_id,
                    "results": results,
                }
            )
            self.s3_storage.write_raw_results_once(raw_result_key, envelope)
            completed_at = utc_now_iso()
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
            self.logger.log(
                "run_completed",
                log_category=LOG_CATEGORY_CLIENT_SAFE,
                client_id=validated.client_id,
                audit_id=validated.audit_id,
                run_id=validated.run_id,
                scenario_type=validated.scenario_type,
                raw_result_version=RAW_RESULT_VERSION,
            )
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
                exc, event=locals().get("validated"), started_item=started_item
            )
        except EngineError as exc:
            return self._failure_response(
                exc, event=locals().get("validated"), started_item=started_item
            )
        except Exception as exc:  # top-level sanitized boundary
            error = EngineError("ORCHESTRATION_ERROR", "Orchestration failed")
            error.__cause__ = exc
            return self._failure_response(
                error, event=locals().get("validated"), started_item=started_item
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

    def _load_and_validate_configs(self, event: OrchestratorEvent) -> list[dict[str, Any]]:
        ClientConfigLoader(self.s3_storage).load(event.client_id)
        audit_config = AuditConfigLoader(self.s3_storage).load(event.client_id, event.audit_id)
        validate_audit_config(audit_config, event.audit_id)
        endpoint_config = EndpointConfigLoader(self.s3_storage).load(
            event.client_id, event.audit_id
        )
        return validate_endpoint_config(endpoint_config)

    def _resolve(self, endpoint: dict[str, Any]) -> dict[str, Any]:
        resolved = {**endpoint, "headers": dict(endpoint.get("headers") or {})}
        for key, value in list(resolved["headers"].items()):
            if isinstance(value, dict) and "secret_ref" in value:
                resolved["headers"][key] = self.secrets_client.resolve(value)
        return resolved

    def _raw_result(self, event: OrchestratorEvent, outcome: RunnerOutcome) -> dict[str, Any]:
        record = {
            "raw_result_version": RAW_RESULT_VERSION,
            "client_id": event.client_id,
            "audit_id": event.audit_id,
            "run_id": event.run_id,
            "scenario_type": event.scenario_type,
            **asdict(outcome),
        }
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
    ) -> dict[str, Any]:
        failure_summary = {"error_type": exc.error_type, "message": exc.message}
        if event and started_item:
            try:
                self.metadata_storage.update_terminal(
                    self.metadata_storage.keys(event.client_id, event.audit_id, event.run_id),
                    {
                        "status": RUN_STATUS_FAILED,
                        "completed_at": utc_now_iso(),
                        "failure_summary": failure_summary,
                    },
                )
            except Exception:
                pass
        event_fields = (
            {"client_id": event.client_id, "audit_id": event.audit_id, "run_id": event.run_id}
            if event
            else {}
        )
        self.logger.log(
            "run_failed",
            log_category=LOG_CATEGORY_CLIENT_SAFE,
            event_type=exc.error_type,
            **event_fields,
            failure_summary=failure_summary,
        )
        return sanitize(
            {
                **event_fields,
                "status": RUN_STATUS_FAILED,
                "failure_summary": failure_summary,
            }
        )
