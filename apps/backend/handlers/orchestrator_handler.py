"""Lambda entry point for the Phase 1 core engine."""

from __future__ import annotations

import os
from typing import Any

import boto3

from apps.backend.orchestrator.service import CoreEngineOrchestrator
from packages.storage.dynamodb_client import DynamoDBMetadataClient
from packages.storage.s3_client import S3StorageClient
from packages.storage.secrets_client import SecretsManagerClient


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    s3_storage = S3StorageClient(os.environ["RAW_RESULTS_BUCKET"], boto3.client("s3"))
    table = boto3.resource("dynamodb").Table(os.environ["METADATA_TABLE"])
    metadata = DynamoDBMetadataClient(os.environ["METADATA_TABLE"], table)
    secrets = SecretsManagerClient(boto3.client("secretsmanager"))
    return CoreEngineOrchestrator(
        s3_storage=s3_storage,
        metadata_storage=metadata,
        secrets_client=secrets,
    ).run(event)
