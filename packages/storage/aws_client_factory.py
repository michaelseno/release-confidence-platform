"""AWS client construction boundary for operator services."""

from __future__ import annotations

import boto3

from packages.config.stage_config import StageConfig
from packages.storage.audit_metadata_client import AuditMetadataRepository
from packages.storage.eventbridge_scheduler_client import EventBridgeSchedulerClient
from packages.storage.lambda_client import LambdaInvocationClient
from packages.storage.s3_client import S3StorageClient


class AwsClientFactory:
    def __init__(self, stage_config: StageConfig):
        self.stage_config = stage_config
        self._session = boto3.Session(
            profile_name=stage_config.aws_profile,
            region_name=stage_config.region,
        )

    def s3_storage(self) -> S3StorageClient:
        return S3StorageClient(self.stage_config.config_bucket, self._session.client("s3"))

    def audit_metadata_repository(self) -> AuditMetadataRepository:
        return AuditMetadataRepository(
            self.stage_config.audit_metadata_table, self._session.client("dynamodb")
        )

    def scheduler(self) -> EventBridgeSchedulerClient:
        return EventBridgeSchedulerClient(
            self._session.client("scheduler"), group_name=self.stage_config.scheduler_group_name
        )

    def lambda_invocation(self) -> LambdaInvocationClient:
        return LambdaInvocationClient(self._session.client("lambda"))
