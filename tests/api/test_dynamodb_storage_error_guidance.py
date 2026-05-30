from __future__ import annotations

import boto3
import pytest
from botocore.exceptions import ParamValidationError
from botocore.stub import Stubber

from release_confidence_platform.config.stage_config import StageConfig
from release_confidence_platform.core.audit_creation_service import AuditCreationService
from release_confidence_platform.core.exceptions import EngineError, StorageError
from release_confidence_platform.storage.audit_metadata_client import AuditMetadataRepository
from release_confidence_platform.storage.dynamodb_client import DynamoDBMetadataClient


def _ddb_client():
    return boto3.client(
        "dynamodb",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        aws_session_token="test",
    )


def test_audit_metadata_put_uses_attribute_value_encoded_low_level_payload():
    client = _ddb_client()
    stubber = Stubber(client)
    stubber.add_response(
        "put_item",
        {},
        {
            "TableName": "metadata-table",
            "Item": {
                "PK": {"S": "CLIENT#client1"},
                "SK": {"S": "AUDIT#audit1"},
                "client_id": {"S": "client1"},
                "audit_id": {"S": "audit1"},
                "lifecycle_state": {"S": "DRAFT"},
                "schedules": {"L": []},
                "config_s3_keys": {
                    "M": {"client_config": {"S": "configs/client1/client_config.json"}}
                },
            },
            "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
        },
    )

    with stubber:
        AuditMetadataRepository("metadata-table", client).put_audit_metadata_once(
            {
                "PK": "CLIENT#client1",
                "SK": "AUDIT#audit1",
                "client_id": "client1",
                "audit_id": "audit1",
                "lifecycle_state": "DRAFT",
                "schedules": [],
                "config_s3_keys": {"client_config": "configs/client1/client_config.json"},
            }
        )


def test_run_metadata_put_uses_attribute_value_encoded_low_level_payload():
    client = _ddb_client()
    stubber = Stubber(client)
    stubber.add_response(
        "put_item",
        {},
        {
            "TableName": "metadata-table",
            "Item": {
                "PK": {"S": "CLIENT#client1"},
                "SK": {"S": "AUDIT#audit1#RUN#run1"},
                "client_id": {"S": "client1"},
                "audit_id": {"S": "audit1"},
                "run_id": {"S": "run1"},
                "status": {"S": "STARTED"},
            },
            "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
        },
    )

    with stubber:
        DynamoDBMetadataClient("metadata-table", client).put_started_once(
            {
                "PK": "CLIENT#client1",
                "SK": "AUDIT#audit1#RUN#run1",
                "client_id": "client1",
                "audit_id": "audit1",
                "run_id": "run1",
                "status": "STARTED",
            }
        )


@pytest.mark.parametrize(
    ("aws_code", "expected_type", "expected_message"),
    [
        (
            "ResourceNotFoundException",
            "STORAGE_CONFIG_ERROR",
            "RCP_AUDIT_METADATA_TABLE=<real-metadata-table>",
        ),
        (
            "AccessDeniedException",
            "STORAGE_PERMISSION_ERROR",
            "required_permissions=dynamodb:GetItem,dynamodb:PutItem",
        ),
    ],
)
def test_dynamodb_client_errors_map_to_actionable_storage_errors(
    aws_code: str, expected_type: str, expected_message: str
):
    client = _ddb_client()
    stubber = Stubber(client)
    stubber.add_client_error(
        "put_item",
        service_error_code=aws_code,
        service_message="contains token=super-secret",
        expected_params={
            "TableName": "metadata-table",
            "Item": {"PK": {"S": "CLIENT#client1"}, "SK": {"S": "AUDIT#audit1"}},
            "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
        },
    )

    with stubber, pytest.raises(EngineError) as exc:
        AuditMetadataRepository("metadata-table", client).put_audit_metadata_once(
            {"PK": "CLIENT#client1", "SK": "AUDIT#audit1"}
        )

    assert exc.value.error_type == expected_type
    assert expected_message in exc.value.message
    assert "super-secret" not in exc.value.message


def test_dynamodb_param_validation_maps_to_structured_storage_config_error():
    class BadLowLevelClient:
        def put_item(self, **kwargs):  # noqa: ARG002
            raise ParamValidationError(report="Invalid type for parameter Item.PK")

    with pytest.raises(EngineError) as exc:
        AuditMetadataRepository("metadata-table", BadLowLevelClient()).put_audit_metadata_once(
            {"PK": "CLIENT#client1", "SK": "AUDIT#audit1"}
        )

    assert exc.value.error_type == "STORAGE_CONFIG_ERROR"
    assert "DynamoDB request shape validation failed" in exc.value.message


def test_audit_create_surfaces_prewrite_metadata_failures_before_s3_writes(tmp_path):
    class S3:
        writes = []

        def object_exists(self, key):  # noqa: ARG002
            return False

        def write_json(self, key, payload, *, overwrite=False):  # noqa: ARG002
            self.writes.append(key)

    class Repo:
        def audit_keys(self, client_id, audit_id):
            return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}"}

        def get_audit_metadata(self, client_id, audit_id):  # noqa: ARG002
            raise StorageError("DynamoDB audit metadata table not found", "STORAGE_CONFIG_ERROR")

    paths = _write_valid_configs(tmp_path)
    s3 = S3()

    with pytest.raises(EngineError) as exc:
        AuditCreationService(
            stage_config=_stage_config(), s3_storage=s3, repository=Repo()
        ).create_from_files(
            client_config_path=str(paths[0]),
            audit_config_path=str(paths[1]),
            endpoints_config_path=str(paths[2]),
        )

    assert exc.value.error_type == "STORAGE_CONFIG_ERROR"
    assert s3.writes == []


def test_audit_create_post_s3_metadata_failures_remain_structured(tmp_path):
    class S3:
        def __init__(self):
            self.writes = []

        def object_exists(self, key):  # noqa: ARG002
            return False

        def write_json(self, key, payload, *, overwrite=False):  # noqa: ARG002
            self.writes.append(key)

    class Repo:
        def audit_keys(self, client_id, audit_id):
            return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}"}

        def get_audit_metadata(self, client_id, audit_id):  # noqa: ARG002
            raise StorageError("Audit metadata not found", "AUDIT_NOT_FOUND")

        def put_audit_metadata_once(self, item):  # noqa: ARG002
            raise StorageError(
                "DynamoDB audit metadata permission denied", "STORAGE_PERMISSION_ERROR"
            )

    paths = _write_valid_configs(tmp_path)
    s3 = S3()

    with pytest.raises(EngineError) as exc:
        AuditCreationService(
            stage_config=_stage_config(), s3_storage=s3, repository=Repo()
        ).create_from_files(
            client_config_path=str(paths[0]),
            audit_config_path=str(paths[1]),
            endpoints_config_path=str(paths[2]),
        )

    assert exc.value.error_type == "STORAGE_PERMISSION_ERROR"
    assert len(s3.writes) == 3


def _write_valid_configs(tmp_path):
    import json

    client = {"client_id": "client1", "safety": {"allowed_methods": ["GET"]}}
    audit = {
        "client_id": "client1",
        "audit_id": "audit1",
        "audit_window": {"start_at": "2026-01-01T00:00:00Z", "end_at": "2026-01-02T00:00:00Z"},
        "execution_environment": {
            "target_environment": "staging",
            "allow_production_execution": False,
        },
        "baseline_schedule": {"enabled": True, "interval_minutes": 15},
        "finalization_schedule": {"enabled": True},
    }
    endpoints = {
        "client_id": "client1",
        "audit_id": "audit1",
        "endpoints": [{"endpoint_id": "e1", "method": "GET", "url": "https://example.com/health"}],
    }
    paths = []
    for name, data in zip(
        ("client.json", "audit.json", "endpoints.json"),
        (client, audit, endpoints),
        strict=True,
    ):
        path = tmp_path / name
        path.write_text(json.dumps(data), encoding="utf-8")
        paths.append(path)
    return paths


def _stage_config():
    return StageConfig(
        stage="dev",
        region="us-east-1",
        aws_profile="test",
        config_bucket="bucket",
        audit_metadata_table="table",
        orchestrator_function_name="orchestrator",
        scheduler_group_name="group",
        schedule_name_prefix="rcp-dev",
        scheduler_execution_target_arn="execution",
        scheduler_finalization_target_arn="finalization",
        scheduler_role_arn="role",
    )
