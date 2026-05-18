"""Deterministic Phase 1 API runner."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

from packages.core.constants.engine import (
    FAILURE_ASSERTION,
    FAILURE_CONNECTION,
    FAILURE_HTTP,
    FAILURE_INVALID_RESPONSE,
    FAILURE_PASS,
    FAILURE_PAYLOAD_VALIDATION,
    FAILURE_RUNNER,
    FAILURE_TIMEOUT,
)
from packages.core.time import utc_now_iso
from packages.data_generation.duplicate_checker import DuplicateChecker
from packages.data_generation.fingerprints import response_fingerprint
from packages.data_generation.generator import PayloadPreparationService, RunContext
from packages.data_generation.validators import PayloadValidationError


@dataclass(frozen=True)
class RunnerOutcome:
    endpoint_id: str
    method: str
    url: str
    status_code: int | None
    duration_ms: int | None
    failure_type: str
    payload_strategy: str
    timestamp: str
    retry_attempts: int
    assertion_results: dict[str, Any] | None = None
    error_code: str | None = None
    payload_metadata: dict[str, Any] | None = None
    response_fingerprint: str | None = None


class ApiRunner:
    def __init__(self, session: Any | None = None):
        self.session = session or requests.Session()

    def execute(
        self,
        endpoint: dict[str, Any],
        *,
        run_context: RunContext | None = None,
        duplicate_checker: DuplicateChecker | None = None,
        payload_preparation: PayloadPreparationService | None = None,
        iteration: int = 1,
    ) -> RunnerOutcome:
        prepared_metadata: dict[str, Any] | None = None
        if (
            run_context is not None
            and duplicate_checker is not None
            and payload_preparation is not None
        ):
            try:
                prepared = payload_preparation.prepare(
                    endpoint=endpoint,
                    run_context=run_context,
                    iteration=iteration,
                    duplicate_checker=duplicate_checker,
                )
                endpoint = {**endpoint, "payload": prepared.payload}
                prepared_metadata = prepared.metadata
            except PayloadValidationError:
                return RunnerOutcome(
                    endpoint_id=endpoint["endpoint_id"],
                    method=endpoint["method"],
                    url=endpoint["url"],
                    status_code=None,
                    duration_ms=None,
                    failure_type=FAILURE_PAYLOAD_VALIDATION,
                    payload_strategy=endpoint.get("payload_strategy", "static"),
                    timestamp=utc_now_iso(),
                    retry_attempts=0,
                    error_code=FAILURE_PAYLOAD_VALIDATION,
                    payload_metadata=prepared_metadata,
                )
        retry_attempts = 0
        final_duration: int | None = None
        last_error = None
        for attempt in range(endpoint["retries"] + 1):
            if attempt > 0:
                retry_attempts += 1
            started = time.monotonic()
            try:
                response = self.session.request(
                    method=endpoint["method"],
                    url=endpoint["url"],
                    headers=endpoint.get("headers") or {},
                    json=endpoint.get("payload"),
                    timeout=endpoint["timeout_seconds"],
                )
                final_duration = int((time.monotonic() - started) * 1000)
                failure_type, assertion_results = evaluate_response(
                    response, endpoint.get("assertions") or {}
                )
                response_body = _response_body_for_fingerprint(response)
                return RunnerOutcome(
                    endpoint_id=endpoint["endpoint_id"],
                    method=endpoint["method"],
                    url=endpoint["url"],
                    status_code=response.status_code,
                    duration_ms=final_duration,
                    failure_type=failure_type,
                    payload_strategy=endpoint["payload_strategy"],
                    timestamp=utc_now_iso(),
                    retry_attempts=retry_attempts,
                    assertion_results=assertion_results,
                    payload_metadata=prepared_metadata,
                    response_fingerprint=response_fingerprint(response_body),
                )
            except requests.Timeout as exc:
                final_duration = int((time.monotonic() - started) * 1000)
                last_error = (FAILURE_TIMEOUT, exc)
            except requests.ConnectionError as exc:
                final_duration = int((time.monotonic() - started) * 1000)
                last_error = (FAILURE_CONNECTION, exc)
            except (TypeError, ValueError) as exc:
                final_duration = int((time.monotonic() - started) * 1000)
                last_error = (FAILURE_PAYLOAD_VALIDATION, exc)
                break
            except requests.RequestException as exc:
                final_duration = int((time.monotonic() - started) * 1000)
                last_error = (FAILURE_HTTP, exc)
            except Exception as exc:  # defensive runner boundary
                final_duration = int((time.monotonic() - started) * 1000)
                last_error = (FAILURE_RUNNER, exc)
                break
        failure_type = last_error[0] if last_error else FAILURE_RUNNER
        return RunnerOutcome(
            endpoint_id=endpoint["endpoint_id"],
            method=endpoint["method"],
            url=endpoint["url"],
            status_code=None,
            duration_ms=final_duration,
            failure_type=failure_type,
            payload_strategy=endpoint["payload_strategy"],
            timestamp=utc_now_iso(),
            retry_attempts=retry_attempts,
            error_code=failure_type,
            payload_metadata=prepared_metadata,
        )


def evaluate_response(response: Any, assertions: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    expected = assertions.get("expected_status_codes") or assertions.get("expected_status_code")
    if expected is None:
        expected_codes = list(range(200, 400))
    elif isinstance(expected, int):
        expected_codes = [expected]
    else:
        expected_codes = list(expected)
    assertion_results: dict[str, Any] = {"expected_status_codes": expected_codes}
    if response.status_code >= 400:
        if response.status_code in expected_codes:
            return FAILURE_PASS, {**assertion_results, "status_code_matched": True}
        return FAILURE_HTTP, {**assertion_results, "status_code_matched": False}
    if response.status_code not in expected_codes:
        return FAILURE_ASSERTION, {**assertion_results, "status_code_matched": False}
    if assertions.get("expect_json") or assertions.get("required_response_fields"):
        try:
            body = response.json()
        except ValueError:
            return FAILURE_INVALID_RESPONSE, {**assertion_results, "json_valid": False}
        assertion_results["json_valid"] = True
        required = assertions.get("required_response_fields") or []
        missing = [field for field in required if not _has_field(body, field)]
        if missing:
            return FAILURE_ASSERTION, {**assertion_results, "missing_fields": missing}
    return FAILURE_PASS, {**assertion_results, "status_code_matched": True}


def _has_field(body: Any, field: str) -> bool:
    current = body
    for part in str(field).split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _response_body_for_fingerprint(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return getattr(response, "text", None)
