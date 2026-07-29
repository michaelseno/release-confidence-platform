"""Internal Phase 4 aggregation Lambda handler."""

from __future__ import annotations

import os
from typing import Any

import boto3

from release_confidence_platform.aggregation.events import validate_aggregation_event
from release_confidence_platform.aggregation.orchestrator import AggregationOrchestrator
from release_confidence_platform.aggregation.repository import AggregationRepository
from release_confidence_platform.core.exceptions import EngineError
from release_confidence_platform.core.logging import StructuredLogger
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from release_confidence_platform.sanitization.sanitizer import sanitize
from release_confidence_platform.storage.s3_client import S3StorageClient

# Evidence Governance Workstream A1.3c.1 (Technical Design Section 19.4,
# 19.15): server-side wiring/configuration gaps -- a Category 1/2 governed
# write refusing to proceed because ITS OWN dependency (hold coordination,
# custody-period configuration) is missing or exhausted, never because the
# caller's request was invalid. CUSTODY_PERIOD_CONFIG_MISSING is added here
# alongside the already-established HOLD_COORDINATION_NOT_CONFIGURED /
# HOLD_STATE_CONCURRENCY_EXCEEDED pair by the same reasoning (flagged
# explicitly in the implementation report rather than treated as
# self-evidently correct, since it was not explicitly enumerated in the
# handler-classification correction round that established the other two
# codes). AGGREGATE_SET_TOO_LARGE and CONDITIONAL_WRITE_FAILED are
# deliberately NOT included -- both remain caller-facing 400s (an oversized
# request; a genuine write conflict), unchanged from the pre-A1.3c.1
# classification.
_SERVER_SIDE_FAILURE_REASON_CODES = frozenset(
    {
        "STORAGE_ERROR",
        "HOLD_COORDINATION_NOT_CONFIGURED",
        "HOLD_STATE_CONCURRENCY_EXCEEDED",
        "CUSTODY_PERIOD_CONFIG_MISSING",
    }
)

# ---------------------------------------------------------------------------
# Startup import validation — fail fast on missing critical modules
# ---------------------------------------------------------------------------
try:
    from release_confidence_platform.aggregation import orchestrator as _orch  # noqa: F401
    from release_confidence_platform.storage import audit_metadata_client as _amc  # noqa: F401
except ImportError as _exc:  # pragma: no cover
    import logging as _logging
    _logging.critical("STARTUP_IMPORT_FAILURE: %s", _exc)
    raise


class AggregationHandler:
    def __init__(self, *, orchestrator: Any, logger: StructuredLogger | None = None):
        self.orchestrator = orchestrator
        self.logger = logger or StructuredLogger()

    def handle(self, event: dict[str, Any], context: Any | None = None) -> dict[str, Any]:
        try:
            validated = validate_aggregation_event(event)
            result = self.orchestrator.run(validated)
            return {"statusCode": 200, "body": sanitize(result)}
        except EngineError as exc:
            status_code = (
                500 if exc.error_type in _SERVER_SIDE_FAILURE_REASON_CODES else 400
            )
            body = {"status": "FAILED", "reason_code": exc.error_type}
            self.logger.log(
                "aggregation_handler_failed",
                level="ERROR",
                reason_code=exc.error_type,
                input_type=type(event).__name__,
            )
            return {"statusCode": status_code, "body": sanitize(body)}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    # Evidence Governance Workstream A1.3c.1 (Technical Design Section 19.4):
    # single-client wiring -- ONE boto3 DynamoDB client backs both
    # HoldRepository and AggregationRepository (and, transitively,
    # HoldCoordinatedTransactionRunner, constructed from
    # AggregationRepository.dynamodb_client at write time). No second
    # DynamoDB client is constructed.
    dynamodb_client = boto3.client("dynamodb")
    s3_client = boto3.client("s3")
    hold_repository = HoldRepository(os.environ["METADATA_TABLE"], dynamodb_client)
    repository = AggregationRepository(
        os.environ["METADATA_TABLE"], dynamodb_client, hold_repository
    )
    s3_storage = S3StorageClient(os.environ["RAW_RESULTS_BUCKET"], s3_client)
    return AggregationHandler(
        orchestrator=AggregationOrchestrator(repository=repository, s3_storage=s3_storage)
    ).handle(event, context)
