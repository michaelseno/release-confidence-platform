"""AWS client construction boundary for operator services."""

from __future__ import annotations

import boto3

from packages.config.stage_config import StageConfig
from packages.core.exceptions import ConfigError, StorageError
from packages.storage.audit_metadata_client import AuditMetadataRepository
from packages.storage.eventbridge_scheduler_client import (
    EventBridgeSchedulerClient,
)
from packages.storage.lambda_client import LambdaInvocationClient
from packages.storage.s3_client import S3StorageClient


class AwsClientFactory:
    def __init__(self, stage_config: StageConfig):
        self.stage_config = stage_config
        try:
            self._session = boto3.Session(
                profile_name=stage_config.aws_profile,
                region_name=stage_config.region,
            )
        except Exception as exc:
            _raise_structured_aws_setup_error(exc)

    def s3_storage(self) -> S3StorageClient:
        try:
            client = self._session.client("s3")
        except Exception as exc:
            _raise_structured_aws_setup_error(exc)
        return S3StorageClient(self.stage_config.config_bucket, client)

    def audit_metadata_repository(self) -> AuditMetadataRepository:
        try:
            client = self._session.client("dynamodb")
        except Exception as exc:
            _raise_structured_aws_setup_error(exc)
        return AuditMetadataRepository(self.stage_config.audit_metadata_table, client)

    def scheduler(self) -> EventBridgeSchedulerClient:
        try:
            client = self._session.client("scheduler")
        except Exception as exc:
            _raise_structured_aws_setup_error(exc)
        return EventBridgeSchedulerClient(
            client,
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
        try:
            client = self._session.client("lambda")
        except Exception as exc:
            _raise_structured_aws_setup_error(exc)
        return LambdaInvocationClient(client)


def _raise_structured_aws_setup_error(exc: Exception) -> None:
    """Map known boto/botocore setup failures to sanitized CLI errors."""

    exc_type = exc.__class__.__name__
    exc_module = exc.__class__.__module__
    if exc_type == "ProfileNotFound":
        raise ConfigError("AWS profile could not be loaded for stage", "AWS_PROFILE_ERROR") from exc
    if exc_type in {"NoCredentialsError", "PartialCredentialsError"}:
        raise ConfigError(
            "AWS credentials could not be loaded for stage", "AWS_CREDENTIALS_ERROR"
        ) from exc
    if exc_type in {"NoRegionError", "InvalidRegionError"}:
        raise ConfigError(
            "AWS region configuration is invalid for stage", "AWS_REGION_ERROR"
        ) from exc
    if exc_module.startswith(("botocore", "boto3")) or exc_type in {"BotoCoreError", "ClientError"}:
        raise StorageError("AWS client setup failed for stage", "AWS_CLIENT_SETUP_ERROR") from exc
    raise exc
