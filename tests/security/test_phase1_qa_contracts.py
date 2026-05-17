import json
from io import BytesIO

import pytest
import requests

from apps.backend.orchestrator.service import CoreEngineOrchestrator
from apps.backend.runner.api_runner import ApiRunner
from packages.config.validators import validate_endpoint_config
from packages.core.constants.engine import DUPLICATE_RUN_ID, ENDPOINT_FAILURE_TYPES
from packages.core.exceptions import ConfigError
from packages.storage.dynamodb_client import DynamoDBMetadataClient
from packages.storage.s3_client import S3StorageClient
from packages.storage.secrets_client import SecretsManagerClient


class CapturingLogger:
    def __init__(self):
        self.records = []

    def log(self, message, **fields):
        record = {"message": message, **fields}
        self.records.append(record)
        return record


class FakeS3:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.get_keys = []
        self.put_keys = []
        self.head_keys = []

    def get_object(self, Bucket, Key):  # noqa: N803, ARG002
        self.get_keys.append(Key)
        if Key not in self.objects:
            raise FileNotFoundError(Key)
        value = self.objects[Key]
        if isinstance(value, bytes):
            return {"Body": BytesIO(value)}
        return {"Body": BytesIO(json.dumps(value).encode())}

    def head_object(self, Bucket, Key):  # noqa: N803, ARG002
        self.head_keys.append(Key)
        if Key not in self.objects:
            raise FileNotFoundError(Key)
        return {}

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803, ARG002
        self.put_keys.append(Key)
        self.objects[Key] = json.loads(Body.decode())


class FakeDynamo:
    def __init__(self, existing=None):
        self.items = dict(existing or {})
        self.puts = []
        self.updates = []

    def get_item(self, TableName, Key):  # noqa: N803, ARG002
        key = (Key["PK"], Key["SK"])
        return {"Item": self.items[key]} if key in self.items else {}

    def put_item(self, TableName, Item, ConditionExpression):  # noqa: N803, ARG002
        self.puts.append(Item)
        self.items[(Item["PK"], Item["SK"])] = Item

    def update_item(self, TableName, Key, ExpressionAttributeValues, **kwargs):  # noqa: N803, ARG002
        self.updates.append((Key, ExpressionAttributeValues, kwargs))
        item = self.items[(Key["PK"], Key["SK"])]
        for index, name in enumerate(kwargs["ExpressionAttributeNames"].values()):
            item[name] = ExpressionAttributeValues[f":v{index}"]


class FakeSecrets:
    def __init__(self, value="Bearer top-secret-token"):
        self.value = value
        self.calls = []

    def get_secret_value(self, SecretId):  # noqa: N803
        self.calls.append(SecretId)
        return {"SecretString": self.value}


class PassResponse:
    status_code = 200

    def json(self):
        return {"ok": True}


def _config_objects():
    return {
        "configs/client/client_config.json": {"client_id": "client"},
        "configs/client/audits/audit/audit_config.json": {"audit_id": "audit"},
        "configs/client/audits/audit/endpoints.json": {
            "endpoints": [
                {
                    "endpoint_id": "ep1",
                    "method": "POST",
                    "url": "https://service.test/health?email=user@example.com&token=abc",
                    "headers": {"Authorization": {"secret_ref": "secret-id"}},
                    "payload": {"safe": True},
                    "payload_strategy": "static",
                    "assertions": {
                        "expected_status_codes": [200],
                        "expect_json": True,
                        "required_response_fields": ["ok"],
                    },
                }
            ]
        },
    }


def test_invalid_run_id_rejects_without_side_effects_or_raw_value_logging():
    raw_bad_run_id = " ../unsafe%2fvalue\n"
    s3_api = FakeS3(_config_objects())
    ddb_api = FakeDynamo()
    logger = CapturingLogger()

    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", s3_api),
        metadata_storage=DynamoDBMetadataClient("table", ddb_api),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        logger=logger,
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "release_smoke",
            "triggered_by": "operator",
            "run_id": raw_bad_run_id,
        }
    )

    assert response["status"] == "FAILED"
    assert response["failure_summary"]["error_type"] == "INVALID_RUN_ID"
    assert "run_id" not in response
    assert s3_api.get_keys == []
    assert s3_api.put_keys == []
    assert ddb_api.puts == []
    assert raw_bad_run_id not in json.dumps(logger.records)
    assert raw_bad_run_id not in json.dumps(response)


def test_valid_supplied_run_id_used_safely_in_outputs_and_secrets_are_not_persisted():
    class Session:
        def request(self, **kwargs):
            assert kwargs["headers"]["Authorization"] == "Bearer top-secret-token"
            return PassResponse()

    run_id = "safe_RUN-123"
    s3_api = FakeS3(_config_objects())
    ddb_api = FakeDynamo()
    logger = CapturingLogger()
    secrets = FakeSecrets()

    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", s3_api),
        metadata_storage=DynamoDBMetadataClient("table", ddb_api),
        secrets_client=SecretsManagerClient(secrets),
        runner=ApiRunner(Session()),
        logger=logger,
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "release_smoke",
            "triggered_by": "operator",
            "run_id": run_id,
        }
    )

    raw_key = f"raw-results/client/audit/{run_id}/results.json"
    ddb_key = ("CLIENT#client", f"AUDIT#audit#RUN#{run_id}")
    persisted = json.dumps(
        {
            "s3": s3_api.objects[raw_key],
            "ddb": ddb_api.items[ddb_key],
            "logs": logger.records,
        }
    )

    assert response["run_id"] == run_id
    assert response["raw_result_s3_key"] == raw_key
    assert s3_api.put_keys == [raw_key]
    assert ddb_key in ddb_api.items
    assert s3_api.objects[raw_key]["results"][0]["run_id"] == run_id
    assert "Bearer top-secret-token" not in persisted
    assert "user@example.com" not in persisted
    assert "REDACTED" in persisted
    assert secrets.calls == ["secret-id"]
    assert {record["log_category"] for record in logger.records} <= {
        "internal_operational_logs",
        "client_safe_logs",
    }


def test_dynamodb_duplicate_run_id_fails_without_endpoint_failure_pollution_or_overwrite():
    run_id = "safe_RUN-123"
    existing_key = ("CLIENT#client", f"AUDIT#audit#RUN#{run_id}")
    ddb_api = FakeDynamo({existing_key: {"PK": existing_key[0], "SK": existing_key[1]}})
    s3_api = FakeS3(_config_objects())

    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", s3_api),
        metadata_storage=DynamoDBMetadataClient("table", ddb_api),
        secrets_client=SecretsManagerClient(FakeSecrets()),
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "release_smoke",
            "triggered_by": "operator",
            "run_id": run_id,
        }
    )

    assert response["failure_summary"]["error_type"] == DUPLICATE_RUN_ID
    assert DUPLICATE_RUN_ID not in ENDPOINT_FAILURE_TYPES
    assert ddb_api.puts == []
    assert ddb_api.updates == []
    assert s3_api.get_keys == []
    assert s3_api.put_keys == []


def test_endpoint_failure_classifications_are_approved_and_deterministic():
    class InvalidJsonResponse:
        status_code = 200

        def json(self):
            raise ValueError("malformed")

    class TimeoutSession:
        def request(self, **kwargs):  # noqa: ARG002
            raise requests.Timeout("timeout")

    class InvalidJsonSession:
        def request(self, **kwargs):  # noqa: ARG002
            return InvalidJsonResponse()

    timeout = ApiRunner(TimeoutSession()).execute(
        {
            "endpoint_id": "ep1",
            "method": "GET",
            "url": "https://service.test",
            "timeout_seconds": 1,
            "retries": 1,
            "payload_strategy": "static",
            "assertions": {},
        }
    )
    invalid_response = ApiRunner(InvalidJsonSession()).execute(
        {
            "endpoint_id": "ep1",
            "method": "GET",
            "url": "https://service.test",
            "timeout_seconds": 1,
            "retries": 0,
            "payload_strategy": "static",
            "assertions": {"expect_json": True},
        }
    )

    assert timeout.failure_type == "TIMEOUT"
    assert timeout.retry_attempts == 1
    assert timeout.duration_ms is not None
    assert invalid_response.failure_type == "INVALID_RESPONSE"
    assert {timeout.failure_type, invalid_response.failure_type} <= set(ENDPOINT_FAILURE_TYPES)


def test_payload_validation_blocks_non_serializable_payload_before_runner_execution():
    with pytest.raises(ConfigError):
        validate_endpoint_config(
            {
                "endpoints": [
                    {
                        "endpoint_id": "ep1",
                        "method": "POST",
                        "url": "https://service.test",
                        "payload": {"bad": object()},
                        "payload_strategy": "static",
                    }
                ]
            }
        )
