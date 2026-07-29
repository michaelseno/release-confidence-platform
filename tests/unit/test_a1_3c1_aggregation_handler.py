"""Evidence Governance Workstream A1.3c.1 — dedicated handler-level coverage
for apps/backend/handlers/aggregation_handler.py's single-client wiring and
corrected server-side-vs-caller-facing error classification (Technical
Design Section 19.4, 19.15).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import apps.backend.handlers.aggregation_handler as aggregation_handler
from apps.backend.handlers.aggregation_handler import AggregationHandler
from release_confidence_platform.aggregation.constants import (
    AGGREGATION_EVENT_SCHEMA_VERSION,
    AGGREGATION_EVENT_TYPE,
    AGGREGATION_VERSION,
)
from release_confidence_platform.core.exceptions import StorageError, ValidationError


def _valid_event(**overrides) -> dict:
    event = {
        "event_type": AGGREGATION_EVENT_TYPE,
        "schema_version": AGGREGATION_EVENT_SCHEMA_VERSION,
        "client_id": "client",
        "audit_id": "audit",
        "aggregation_version": AGGREGATION_VERSION,
    }
    event.update(overrides)
    return event


# ---------------------------------------------------------------------------
# Single-client wiring / object identity
# ---------------------------------------------------------------------------


def test_handler_wires_hold_repository_and_aggregation_repository_to_same_client(monkeypatch):
    monkeypatch.setenv("METADATA_TABLE", "table-x")
    monkeypatch.setenv("RAW_RESULTS_BUCKET", "bucket-x")

    mock_orchestrator = MagicMock()
    mock_orchestrator.run.return_value = {"status": "COMPLETED"}

    captured = {}

    def capturing_hold_repo(table_name, client):
        captured["hold_repo_client"] = client
        return MagicMock()

    def capturing_agg_repo(table_name, client, hold_repository=None):
        captured["agg_repo_client"] = client
        captured["agg_repo_hold_repository"] = hold_repository
        return MagicMock()

    with (
        patch("apps.backend.handlers.aggregation_handler.boto3") as mock_boto3,
        patch(
            "apps.backend.handlers.aggregation_handler.AggregationOrchestrator"
        ) as mock_orch_cls,
        patch(
            "apps.backend.handlers.aggregation_handler.HoldRepository",
            side_effect=capturing_hold_repo,
        ) as mock_hold_repo_cls,
        patch(
            "apps.backend.handlers.aggregation_handler.AggregationRepository",
            side_effect=capturing_agg_repo,
        ),
    ):
        dynamodb_sentinel = MagicMock(name="dynamodb_client_sentinel")
        s3_sentinel = MagicMock(name="s3_client_sentinel")

        def boto3_client_side_effect(service_name, *args, **kwargs):
            return dynamodb_sentinel if service_name == "dynamodb" else s3_sentinel

        mock_boto3.client.side_effect = boto3_client_side_effect
        mock_orch_cls.return_value = mock_orchestrator

        aggregation_handler.handler(_valid_event(), None)

        # Exactly one dynamodb client constructed (plus one s3 client) --
        # never a second, separate DynamoDB client.
        dynamodb_client_calls = [
            call for call in mock_boto3.client.call_args_list if call.args[:1] == ("dynamodb",)
        ]
        assert len(dynamodb_client_calls) == 1

        assert mock_hold_repo_cls.call_count == 1
        assert captured["hold_repo_client"] is dynamodb_sentinel
        assert captured["agg_repo_client"] is dynamodb_sentinel
        assert captured["agg_repo_client"] is captured["hold_repo_client"], (
            "HoldRepository and AggregationRepository must be constructed "
            "against the SAME DynamoDB client object"
        )
        assert captured["agg_repo_hold_repository"] is not None


# ---------------------------------------------------------------------------
# Status-code classification
# ---------------------------------------------------------------------------


class _RaisingOrchestrator:
    def __init__(self, exc: Exception):
        self._exc = exc

    def run(self, event):
        raise self._exc


@pytest.mark.parametrize(
    "error_type",
    [
        "STORAGE_ERROR",
        "HOLD_COORDINATION_NOT_CONFIGURED",
        "HOLD_STATE_CONCURRENCY_EXCEEDED",
        "CUSTODY_PERIOD_CONFIG_MISSING",
    ],
)
def test_server_side_failure_reason_codes_map_to_500(error_type):
    handler = AggregationHandler(
        orchestrator=_RaisingOrchestrator(StorageError("internal detail", error_type))
    )

    result = handler.handle(_valid_event())

    assert result["statusCode"] == 500
    assert result["body"] == {"status": "FAILED", "reason_code": error_type}


@pytest.mark.parametrize("error_type", ["AGGREGATE_SET_TOO_LARGE", "CONDITIONAL_WRITE_FAILED"])
def test_caller_facing_reason_codes_remain_400(error_type):
    handler = AggregationHandler(
        orchestrator=_RaisingOrchestrator(StorageError("caller detail", error_type))
    )

    result = handler.handle(_valid_event())

    assert result["statusCode"] == 400
    assert result["body"] == {"status": "FAILED", "reason_code": error_type}


def test_generic_validation_error_remains_400():
    handler = AggregationHandler(
        orchestrator=_RaisingOrchestrator(ValidationError("bad input", "SOME_VALIDATION_CODE"))
    )

    result = handler.handle(_valid_event())

    assert result["statusCode"] == 400


def test_no_503_status_code_ever_used():
    for error_type in [
        "STORAGE_ERROR",
        "HOLD_COORDINATION_NOT_CONFIGURED",
        "HOLD_STATE_CONCURRENCY_EXCEEDED",
        "CUSTODY_PERIOD_CONFIG_MISSING",
        "AGGREGATE_SET_TOO_LARGE",
        "CONDITIONAL_WRITE_FAILED",
    ]:
        handler = AggregationHandler(
            orchestrator=_RaisingOrchestrator(StorageError("x", error_type))
        )
        result = handler.handle(_valid_event())
        assert result["statusCode"] in (400, 500)


def test_successful_unheld_aggregation_returns_200():
    mock_orchestrator = MagicMock()
    mock_orchestrator.run.return_value = {
        "status": "COMPLETED",
        "client_id": "c",
        "audit_id": "a",
    }
    handler = AggregationHandler(orchestrator=mock_orchestrator)

    result = handler.handle(_valid_event())

    assert result["statusCode"] == 200
    assert result["body"]["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# No internal detail leakage on failure responses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error_type",
    [
        "STORAGE_ERROR",
        "HOLD_COORDINATION_NOT_CONFIGURED",
        "HOLD_STATE_CONCURRENCY_EXCEEDED",
        "CUSTODY_PERIOD_CONFIG_MISSING",
        "AGGREGATE_SET_TOO_LARGE",
        "CONDITIONAL_WRITE_FAILED",
    ],
)
def test_failure_response_body_exposes_no_internal_detail(error_type):
    sensitive_message = (
        "aws_error_code=AccessDeniedException; operation=transact_write_items; "
        "table=metadata-table-prod; PK=CLIENT#secret-client"
    )
    handler = AggregationHandler(
        orchestrator=_RaisingOrchestrator(StorageError(sensitive_message, error_type))
    )

    result = handler.handle(_valid_event())

    assert set(result["body"].keys()) == {"status", "reason_code"}
    assert result["body"]["status"] == "FAILED"
    assert result["body"]["reason_code"] == error_type
    body_text = repr(result["body"])
    assert "aws_error_code" not in body_text
    assert "AccessDeniedException" not in body_text
    assert "metadata-table-prod" not in body_text
    assert "secret-client" not in body_text
