"""Lambda entry point for the Phase 1 core engine."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

from apps.backend.orchestrator.service import CoreEngineOrchestrator
from packages.core.time import utc_now_iso
from packages.sanitization.sanitizer import sanitize
from packages.storage.dynamodb_client import DynamoDBMetadataClient
from packages.storage.s3_client import S3StorageClient
from packages.storage.secrets_client import SecretsManagerClient

# ---------------------------------------------------------------------------
# Startup import validation — fail fast on missing critical modules
# ---------------------------------------------------------------------------
try:
    from packages.core import logging as _core_logging  # noqa: F401
    from packages.storage import audit_metadata_client as _amc  # noqa: F401
except ImportError as _exc:  # pragma: no cover
    import logging as _logging
    _logging.critical("STARTUP_IMPORT_FAILURE: %s", _exc)
    raise


def configure_logging() -> None:
    """Configure Lambda-visible structured logging without relying on basicConfig only."""

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root_logger = logging.getLogger()
    app_logger = logging.getLogger("release-confidence-platform")

    if not root_logger.handlers:
        logging.basicConfig(level=level)
    root_logger.setLevel(level)
    for handler in root_logger.handlers:
        handler.setLevel(level)
    app_logger.setLevel(level)
    app_logger.propagate = True


configure_logging()


def _emit_handler_started(event: Any) -> None:
    record = sanitize(
        {
            "timestamp": utc_now_iso(),
            "level": "INFO",
            "message": "orchestrator_handler_started",
            "service": "release-confidence-platform",
            "event_type": "orchestrator_handler_started",
            "event_keys": list(event.keys()) if isinstance(event, dict) else [],
            "input_type": type(event).__name__,
        }
    )
    print(json.dumps(record, sort_keys=True))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    configure_logging()
    _emit_handler_started(event)
    s3_storage = S3StorageClient(os.environ["RAW_RESULTS_BUCKET"], boto3.client("s3"))
    table = boto3.resource("dynamodb").Table(os.environ["METADATA_TABLE"])
    metadata = DynamoDBMetadataClient(os.environ["METADATA_TABLE"], table)
    secrets = SecretsManagerClient(boto3.client("secretsmanager"))
    return CoreEngineOrchestrator(
        s3_storage=s3_storage,
        metadata_storage=metadata,
        secrets_client=secrets,
    ).run(event)
