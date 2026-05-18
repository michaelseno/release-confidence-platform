"""QA supplemental coverage for Phase 2 payload data generation acceptance criteria."""

from __future__ import annotations

from typing import Any

import pytest

from apps.backend.runner.api_runner import ApiRunner
from packages.core.constants.engine import FAILURE_PAYLOAD_VALIDATION
from packages.data_generation.duplicate_checker import DuplicateChecker
from packages.data_generation.generator import PayloadPreparationService, RunContext
from packages.data_generation.validators import PayloadValidationError


def _run_context() -> RunContext:
    return RunContext(
        client_id="client-a",
        audit_id="audit-a",
        run_id="run_phase2_qa",
        scenario_type="release_smoke",
        run_timestamp="2026-05-18T12:00:00Z",
    )


def _duplicate_checker() -> DuplicateChecker:
    return DuplicateChecker(client_id="client-a", audit_id="audit-a", run_id="run_phase2_qa")


def _generated_endpoint(**overrides: Any) -> dict[str, Any]:
    endpoint = {
        "endpoint_id": "generated-endpoint",
        "method": "POST",
        "url": "https://service.example.test/generated",
        "timeout_seconds": 1,
        "retries": 0,
        "payload_strategy": "generated",
        "payload_template": {"request_id": "fixed"},
        "duplicate_policy": "regenerate",
        "duplicate_check_scope": "current_run",
        "payload_safety": {"allow_generated_payloads": True},
        "assertions": {"expected_status_codes": [200]},
    }
    endpoint.update(overrides)
    return endpoint


class _Response:
    status_code = 200

    def json(self) -> dict[str, bool]:
        return {"ok": True}


class _Session:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> _Response:
        self.requests.append(kwargs)
        return _Response()


def test_malformed_generated_token_with_extra_closing_brace_fails_before_request() -> None:
    """AC-004/FR-003: malformed variable tokens must fail validation pre-request."""
    service = PayloadPreparationService()
    endpoint = _generated_endpoint(payload_template={"request_id": "{{uuid}}}"})

    with pytest.raises(PayloadValidationError):
        service.prepare(
            endpoint=endpoint,
            run_context=_run_context(),
            iteration=1,
            duplicate_checker=_duplicate_checker(),
        )


def test_fail_fast_duplicate_failure_preserves_safe_duplicate_metadata() -> None:
    """AC-013/AC-029: duplicate-related failures must expose safe outcome metadata."""
    session = _Session()
    runner = ApiRunner(session)
    duplicate_checker = _duplicate_checker()
    payload_preparation = PayloadPreparationService()
    endpoint = _generated_endpoint(duplicate_policy="fail_fast")

    first = runner.execute(
        endpoint,
        run_context=_run_context(),
        duplicate_checker=duplicate_checker,
        payload_preparation=payload_preparation,
        iteration=1,
    )
    second = runner.execute(
        endpoint,
        run_context=_run_context(),
        duplicate_checker=duplicate_checker,
        payload_preparation=payload_preparation,
        iteration=1,
    )

    assert first.failure_type == "PASS"
    assert len(session.requests) == 1, "duplicate failure must not send a second request"
    assert second.failure_type == FAILURE_PAYLOAD_VALIDATION
    assert second.payload_metadata is not None
    assert second.payload_metadata["duplicate_detected"] is True
    assert second.payload_metadata["duplicate_policy"] == "fail_fast"
    assert second.payload_metadata["duplicate_allowed"] is False
    assert second.payload_metadata["duplicate_check_scope"] == "current_run"
