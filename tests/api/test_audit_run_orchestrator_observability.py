import json
import logging
from io import BytesIO

import pytest
from botocore.exceptions import ClientError

from apps.backend.handlers import orchestrator_handler
from apps.backend.orchestrator.service import CoreEngineOrchestrator
from apps.backend.runner.api_runner import RunnerOutcome
from packages.core.constants.engine import FAILURE_PASS
from packages.core.logging import StructuredLogger
from packages.core.time import utc_now_iso
from packages.storage.dynamodb_client import DynamoDBMetadataClient
from packages.storage.s3_client import S3StorageClient
from packages.storage.secrets_client import SecretsManagerClient


class CapturingLogger:
    def __init__(self):
        self.records = []

    def log(self, message, **fields):
        self.records.append({"message": message, **fields})


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
        self.items[tuple(Item[key] for key in ("PK", "SK"))] = Item

    def update_item(self, TableName, Key, **kwargs):  # noqa: N803, ARG002
        names = kwargs["ExpressionAttributeNames"]
        values = kwargs["ExpressionAttributeValues"]
        for index, name in enumerate(names.values()):
            self.items[tuple(Key.values())][name] = values[f":v{index}"]


class FakeSecrets:
    def get_secret_value(self, SecretId):  # noqa: N803
        return {"SecretString": f"secret-for-{SecretId}"}


class PassingRunner:
    def execute(self, endpoint, **kwargs):  # noqa: ARG002
        return RunnerOutcome(
            endpoint_id=endpoint["endpoint_id"],
            method=endpoint["method"],
            url=endpoint["url"],
            status_code=200,
            duration_ms=1,
            failure_type=FAILURE_PASS,
            payload_strategy=endpoint["payload_strategy"],
            timestamp=utc_now_iso(),
            retry_attempts=0,
        )


def valid_config_objects():
    return {
        "configs/client/audits/audit/audit_config.json": {"audit_id": "audit"},
        "configs/client/client_config.json": {"client_id": "client"},
        "configs/client/audits/audit/endpoints.json": {
            "endpoints": [
                {
                    "endpoint_id": "ep1",
                    "method": "GET",
                    "url": "https://example.test/health?token=secret-token-value",
                    "payload_strategy": "static",
                    "payload_iterations": 1,
                    "headers": {"Authorization": {"secret_ref": "arn:test:secret"}},
                }
            ]
        },
    }


def valid_event():
    return {
        "client_id": "client",
        "audit_id": "audit",
        "scenario_type": "release_smoke",
        "triggered_by": "manual",
        "schedule_type": "manual",
        "stage": "dev",
        "run_id": "safe_run_123",
    }


def test_handler_logging_configuration_enables_info_and_preserves_print_fallback(
    monkeypatch, capsys
):
    class FakeOrchestrator:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def run(self, event):
            return {"status": "COMPLETED", "run_id": event["run_id"]}

    class FakeBoto3:
        def client(self, name):
            return object()

        def resource(self, name):
            class Resource:
                def Table(self, table_name):
                    return object()

            return Resource()

    monkeypatch.setenv("RAW_RESULTS_BUCKET", "bucket")
    monkeypatch.setenv("METADATA_TABLE", "table")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setattr(orchestrator_handler, "boto3", FakeBoto3())
    monkeypatch.setattr(orchestrator_handler, "CoreEngineOrchestrator", FakeOrchestrator)
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger("release-confidence-platform").setLevel(logging.WARNING)

    response = orchestrator_handler.handler({**valid_event(), "token": "secret-token-value"}, None)

    first_line = json.loads(capsys.readouterr().out.splitlines()[0])
    assert response["status"] == "COMPLETED"
    assert logging.getLogger().level <= logging.INFO
    assert logging.getLogger("release-confidence-platform").level <= logging.INFO
    assert first_line["event_type"] == "orchestrator_handler_started"
    assert first_line["event_keys"]
    assert "secret-token-value" not in json.dumps(first_line)


def test_success_path_emits_required_sanitized_milestone_logs():
    logger = CapturingLogger()
    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", FakeS3Api(valid_config_objects())),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=PassingRunner(),
        logger=logger,
    ).run(valid_event())

    messages = [record["message"] for record in logger.records]
    required_order = [
        "event_validation_started",
        "event_validation_completed",
        "duplicate_preflight_started",
        "duplicate_preflight_completed",
        "metadata_started_write_started",
        "metadata_started_write_completed",
        "config_load_started",
        "config_load_completed",
        "endpoint_execution_started",
        "endpoint_execution_completed",
        "raw_result_write_started",
        "raw_result_write_completed",
        "terminal_metadata_update_started",
        "terminal_metadata_update_completed",
        "run_returning",
    ]

    assert response["status"] == "COMPLETED"
    assert [messages.index(message) for message in required_order] == sorted(
        messages.index(message) for message in required_order
    )
    serialized = json.dumps(logger.records)
    assert "secret-for-arn:test:secret" not in serialized
    assert "secret-token-value" not in serialized
    assert "Authorization" not in serialized
    assert "headers" not in serialized


@pytest.mark.parametrize(
    ("event_override", "expected_log"),
    [({"client_id": None}, "event_validation_failed"), ({}, "config_load_failed")],
)
def test_validation_and_config_failures_emit_error_logs_and_structured_failure(
    event_override, expected_log
):
    logger = CapturingLogger()
    event = valid_event()
    event.update(event_override)
    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", FakeS3Api()),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        logger=logger,
    ).run(event)

    failure_record = next(record for record in logger.records if record["message"] == expected_log)
    assert response["status"] == "FAILED"
    assert response["failure_summary"]["error_type"]
    assert failure_record["level"] == "ERROR"
    assert "secret-token-value" not in json.dumps(logger.records)


def test_raw_result_and_metadata_failures_emit_error_logs_and_structured_failure():
    class FailingRawWrite(FakeS3Api):
        def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803, ARG002
            if Key.startswith("raw-results/"):
                raise RuntimeError("token=secret-token-value")
            super().put_object(Bucket, Key, Body, ContentType)

    class FailingMetadata(FakeDynamo):
        def put_item(self, TableName, Item, ConditionExpression):  # noqa: N803, ARG002
            raise RuntimeError("token=secret-token-value")

    for s3_api, dynamo, expected_log in (
        (FailingRawWrite(valid_config_objects()), FakeDynamo(), "raw_result_write_failed"),
        (FakeS3Api(valid_config_objects()), FailingMetadata(), "metadata_started_write_failed"),
    ):
        logger = CapturingLogger()
        response = CoreEngineOrchestrator(
            s3_storage=S3StorageClient("bucket", s3_api),
            metadata_storage=DynamoDBMetadataClient("table", dynamo),
            secrets_client=SecretsManagerClient(FakeSecrets()),
            runner=PassingRunner(),
            logger=logger,
        ).run(valid_event())

        failure_record = next(
            record for record in logger.records if record["message"] == expected_log
        )
        assert response["status"] == "FAILED"
        assert response["failure_summary"]["error_type"]
        assert failure_record["level"] == "ERROR"
        assert "secret-token-value" not in json.dumps(logger.records)


def test_structured_logs_do_not_leak_full_payloads_or_tracebacks(caplog):
    caplog.set_level(logging.INFO, logger="release-confidence-platform")
    CoreEngineOrchestrator(
        s3_storage=object(),
        metadata_storage=object(),
        secrets_client=object(),
        logger=StructuredLogger(),
    ).run(
        {
            "audit_id": "audit",
            "scenario_type": "release_smoke",
            "triggered_by": "manual",
            "headers": {"Authorization": "Bearer secret-token-value"},
            "payload": {"token": "secret-token-value"},
        }
    )

    emitted = "\n".join(record.getMessage() for record in caplog.records)
    assert "secret-token-value" not in emitted
    assert '"headers"' not in emitted
    assert '"payload"' not in emitted
    assert "Traceback" not in emitted


def test_dynamodb_clienterror_maps_to_actionable_sanitized_storage_error():
    class DeniedDynamo:
        def get_item(self, TableName, Key):  # noqa: N803, ARG002
            raise ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "token=super-secret"}},
                "GetItem",
            )

    with pytest.raises(Exception) as exc:
        DynamoDBMetadataClient("table", DeniedDynamo()).metadata_exists(
            "client", "audit", "safe_run_123"
        )

    assert exc.value.error_type == "STORAGE_PERMISSION_ERROR"
    assert "operation=get_item" in exc.value.message
    assert "aws_error_code=AccessDeniedException" in exc.value.message
    assert "required_permissions=dynamodb:GetItem" in exc.value.message
    assert "super-secret" not in exc.value.message
