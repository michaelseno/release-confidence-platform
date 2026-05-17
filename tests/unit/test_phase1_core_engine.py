import json
from io import BytesIO

import pytest
import requests

from apps.backend.orchestrator.service import CoreEngineOrchestrator
from apps.backend.runner.api_runner import ApiRunner
from packages.config.validators import validate_endpoint_config
from packages.core.constants.engine import DUPLICATE_RUN_ID, FAILURE_CONNECTION, FAILURE_PASS
from packages.core.exceptions import ConfigError, DuplicateRunIdError, ValidationError
from packages.core.validators import validate_event, validate_run_id
from packages.sanitization.sanitizer import REDACTION_TOKEN, sanitize
from packages.storage.dynamodb_client import DynamoDBMetadataClient
from packages.storage.s3_client import S3StorageClient
from packages.storage.secrets_client import SecretsManagerClient


class FakeS3Api:
    def __init__(self, objects=None):
        self.objects = objects or {}

    def get_object(self, Bucket, Key):  # noqa: N803, ARG002
        if Key not in self.objects:
            raise FileNotFoundError(Key)
        return {"Body": BytesIO(json.dumps(self.objects[Key]).encode())}

    def head_object(self, Bucket, Key):  # noqa: N803, ARG002
        if Key not in self.objects:
            raise FileNotFoundError(Key)
        return {}

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803, ARG002
        self.objects[Key] = json.loads(Body.decode())


class FakeDynamo:
    def __init__(self):
        self.items = {}

    def get_item(self, TableName, Key):  # noqa: N803, ARG002
        key = tuple(Key.values())
        return {"Item": self.items[key]} if key in self.items else {}

    def put_item(self, TableName, Item, ConditionExpression):  # noqa: N803, ARG002
        key = (Item["PK"], Item["SK"])
        if key in self.items:
            raise DuplicateRunIdError()
        self.items[key] = Item

    def update_item(self, TableName, Key, **kwargs):  # noqa: N803, ARG002
        names = kwargs["ExpressionAttributeNames"]
        values = kwargs["ExpressionAttributeValues"]
        for index, name in enumerate(names.values()):
            self.items[tuple(Key.values())][name] = values[f":v{index}"]


class FakeSecrets:
    def get_secret_value(self, SecretId):  # noqa: N803
        return {"SecretString": f"secret-for-{SecretId}"}


def test_run_id_validation_rejects_unsafe_values_without_replacement() -> None:
    assert validate_run_id("safe_RUN-123") == "safe_RUN-123"
    for value in ["short", "../unsafe", "bad.value", "bad value", "bad%2fvalue", "line\nbreak"]:
        with pytest.raises(ValidationError):
            validate_run_id(value)

    with pytest.raises(ValidationError):
        validate_event(
            {
                "client_id": "c",
                "audit_id": "a",
                "scenario_type": "s",
                "triggered_by": "operator",
                "run_id": "../unsafe",
            }
        )


def test_generated_run_id_satisfies_policy() -> None:
    event = validate_event(
        {"client_id": "c", "audit_id": "a", "scenario_type": "s", "triggered_by": "operator"}
    )
    assert validate_run_id(event.run_id) == event.run_id


def test_sanitizer_redacts_sensitive_keys_and_patterns() -> None:
    payload = {
        "headers": {"Authorization": "Bearer abc123", "x-api-key": "secret"},
        "email_text": "user@example.com",
        "url": "https://example.test/path?token=abc&ok=1",
    }
    sanitized = sanitize(payload)
    assert sanitized["headers"]["Authorization"] == REDACTION_TOKEN
    assert sanitized["headers"]["x-api-key"] == REDACTION_TOKEN
    assert sanitized["email_text"] == REDACTION_TOKEN
    assert "token=%5BREDACTED%5D" in sanitized["url"]


def test_endpoint_config_validation_enforces_timeout_retry_and_secret_refs() -> None:
    valid = validate_endpoint_config(
        {
            "endpoints": [
                {
                    "endpoint_id": "ep1",
                    "method": "GET",
                    "url": "https://example.test/health",
                    "payload_strategy": "static",
                    "headers": {"Authorization": {"secret_ref": "arn"}},
                }
            ]
        }
    )
    assert valid[0]["timeout_seconds"] == 10
    with pytest.raises(ConfigError):
        validate_endpoint_config(
            {
                "endpoints": [
                    {
                        "endpoint_id": "ep1",
                        "method": "GET",
                        "url": "https://example.test/health",
                        "payload_strategy": "static",
                        "timeout_seconds": 31,
                    }
                ]
            }
        )
    with pytest.raises(ConfigError):
        validate_endpoint_config(
            {
                "endpoints": [
                    {
                        "endpoint_id": "ep1",
                        "method": "GET",
                        "url": "https://example.test/health",
                        "payload_strategy": "static",
                        "headers": {"Authorization": "Bearer literal"},
                    }
                ]
            }
        )


def test_storage_clients_build_keys_and_detect_duplicates() -> None:
    s3 = S3StorageClient("bucket", FakeS3Api())
    key = s3.build_raw_result_key("client", "audit", "run_12345")
    assert key == "raw-results/client/audit/run_12345/results.json"
    s3.write_raw_results_once(key, {"secret": "value"})
    with pytest.raises(DuplicateRunIdError):
        s3.write_raw_results_once(key, {})


def test_api_runner_records_retries_and_connection_error() -> None:
    class Session:
        def __init__(self):
            self.calls = 0

        def request(self, **kwargs):  # noqa: ARG002
            self.calls += 1
            raise requests.ConnectionError("nope")

    session = Session()
    outcome = ApiRunner(session).execute(
        {
            "endpoint_id": "ep1",
            "method": "GET",
            "url": "https://example.test",
            "timeout_seconds": 1,
            "retries": 2,
            "payload_strategy": "static",
            "assertions": {},
        }
    )
    assert outcome.retry_attempts == 2
    assert outcome.failure_type == FAILURE_CONNECTION
    assert session.calls == 3


def test_api_runner_passes_foundational_assertions() -> None:
    class Response:
        status_code = 200

        def json(self):
            return {"ok": True}

    class Session:
        def request(self, **kwargs):  # noqa: ARG002
            return Response()

    outcome = ApiRunner(Session()).execute(
        {
            "endpoint_id": "ep1",
            "method": "GET",
            "url": "https://example.test",
            "timeout_seconds": 1,
            "retries": 0,
            "payload_strategy": "static",
            "assertions": {
                "expected_status_codes": [200],
                "expect_json": True,
                "required_response_fields": ["ok"],
            },
        }
    )
    assert outcome.failure_type == FAILURE_PASS


def test_orchestrator_duplicate_fails_fast_before_config_load() -> None:
    s3api = FakeS3Api({"raw-results/client/audit/safe_run_123/results.json": {}})
    orchestrator = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", s3api),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
    )
    response = orchestrator.run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "release_smoke",
            "triggered_by": "operator",
            "run_id": "safe_run_123",
        }
    )
    assert response["status"] == "FAILED"
    assert response["failure_summary"]["error_type"] == DUPLICATE_RUN_ID
