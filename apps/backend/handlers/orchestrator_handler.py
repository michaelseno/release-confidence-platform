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
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository

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
    # Evidence Governance Workstream A1.LH3 (Technical Design Section 19.8,
    # 19.10 item (c+d)): `table` remains a Table RESOURCE for
    # DynamoDBMetadataClient's existing (pre-A1.LH3) get_item/put_item/
    # update_item operations, unchanged. `table.meta.client` -- the verified
    # low-level client accessor -- is what HoldRepository and, via
    # DynamoDBMetadataClient's own constructor, HoldCoordinatedTransactionRunner
    # require: TransactWriteItems and the wire-format item encoding it needs
    # (dynamodb_codec.encode_item) do not exist on a Table resource. One
    # HoldRepository instance is constructed here and injected into both the
    # DynamoDB path (DynamoDBMetadataClient) and the S3 path
    # (S3StorageClient) so both governed write paths resolve legal-hold state
    # against the same authoritative repository.
    table = boto3.resource("dynamodb").Table(os.environ["METADATA_TABLE"])
    hold_repository = HoldRepository(os.environ["METADATA_TABLE"], table.meta.client)
    s3_storage = S3StorageClient(
        os.environ["RAW_RESULTS_BUCKET"], boto3.client("s3"), hold_repository
    )
    metadata = DynamoDBMetadataClient(
        os.environ["METADATA_TABLE"], table, hold_repository, table.meta.client
    )
    secrets = SecretsManagerClient(boto3.client("secretsmanager"))
    return CoreEngineOrchestrator(
        s3_storage=s3_storage,
        metadata_storage=metadata,
        secrets_client=secrets,
    ).run(event)
