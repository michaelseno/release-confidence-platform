"""AWS client construction boundary for operator services."""

from __future__ import annotations

import boto3

from release_confidence_platform.config.stage_config import StageConfig
from release_confidence_platform.storage.audit_metadata_client import AuditMetadataRepository
from release_confidence_platform.storage.eventbridge_scheduler_client import (
    EventBridgeSchedulerClient,
)
from release_confidence_platform.storage.lambda_client import LambdaInvocationClient
from release_confidence_platform.storage.s3_client import S3StorageClient


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
            self._session.client("scheduler"),
            target_arns={
                "baseline": self.stage_config.scheduler_execution_target_arn,
                "burst": self.stage_config.scheduler_execution_target_arn,
                "repeated": self.stage_config.scheduler_execution_target_arn,
                "finalization": self.stage_config.scheduler_finalization_target_arn,
            },
            role_arn=self.stage_config.scheduler_role_arn,
            group_name=self.stage_config.scheduler_group_name,
        )

    def lambda_invocation(self) -> LambdaInvocationClient:
        return LambdaInvocationClient(self._session.client("lambda"))
