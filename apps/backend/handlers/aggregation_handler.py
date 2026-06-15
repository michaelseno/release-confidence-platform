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
from release_confidence_platform.sanitization.sanitizer import sanitize
from release_confidence_platform.storage.s3_client import S3StorageClient


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
            status_code = 400 if exc.error_type not in {"STORAGE_ERROR"} else 500
            body = {"status": "FAILED", "reason_code": exc.error_type}
            self.logger.log(
                "aggregation_handler_failed",
                level="ERROR",
                reason_code=exc.error_type,
                input_type=type(event).__name__,
            )
            return {"statusCode": status_code, "body": sanitize(body)}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    dynamodb_client = boto3.client("dynamodb")
    s3_client = boto3.client("s3")
    repository = AggregationRepository(os.environ["METADATA_TABLE"], dynamodb_client)
    s3_storage = S3StorageClient(os.environ["RAW_RESULTS_BUCKET"], s3_client)
    return AggregationHandler(
        orchestrator=AggregationOrchestrator(repository=repository, s3_storage=s3_storage)
    ).handle(event, context)
