import json
import logging
import threading
import time
from io import BytesIO

import pytest
import requests
from botocore.exceptions import ClientError

from apps.backend.handlers import orchestrator_handler
from apps.backend.orchestrator.service import CoreEngineOrchestrator
from apps.backend.runner.api_runner import ApiRunner, RunnerOutcome
from packages.audit_scheduling.constants import MAX_REPEATED_ITERATIONS
from packages.audit_scheduling.validators import validate_schedule_config
from packages.config.validators import validate_endpoint_config
from packages.core.constants.engine import (
    DUPLICATE_RUN_ID,
    FAILURE_ASSERTION,
    FAILURE_CONNECTION,
    FAILURE_PASS,
)
from packages.core.exceptions import (
    ConfigError,
    DuplicateRunIdError,
    EngineError,
    StorageError,
    ValidationError,
)
from packages.core.logging import StructuredLogger
from packages.core.time import utc_now_iso
from packages.core.validators import validate_event, validate_run_id
from packages.sanitization.sanitizer import REDACTION_TOKEN, sanitize
from packages.storage.dynamodb_client import DynamoDBMetadataClient
from packages.storage.s3_client import S3StorageClient
from packages.storage.secrets_client import SecretsManagerClient
from release_confidence_platform.config.validators import (
    validate_endpoint_config as validate_src_endpoint_config,
)
from release_confidence_platform.core.exceptions import ConfigError as SrcConfigError


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


class CapturingLogger:
    def __init__(self):
        self.records = []

    def log(self, message, **fields):
        self.records.append({"message": message, **fields})


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


class TrackingRunner:
    def __init__(self, *, sleep_seconds=0.0):
        self.sleep_seconds = sleep_seconds
        self.endpoint_ids = []
        self.iterations = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def execute(self, endpoint, *, iteration=1, **kwargs):  # noqa: ARG002
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.sleep_seconds:
                time.sleep(self.sleep_seconds)
            with self._lock:
                self.endpoint_ids.append(endpoint["endpoint_id"])
                self.iterations.append(iteration)
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
        finally:
            with self._lock:
                self.active -= 1

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


def valid_config_objects():
    return {
        "configs/client/client_config.json": {"client_id": "client"},
        "configs/client/audits/audit/audit_config.json": {"audit_id": "audit"},
        "configs/client/audits/audit/endpoints.json": {
            "endpoints": [
                {
                    "endpoint_id": "ep1",
                    "method": "GET",
                    "url": "https://example.test/health",
                    "payload_strategy": "static",
                    "payload_iterations": 1,
                }
            ]
        },
    }


def endpoint_config_with(endpoint_overrides):
    endpoint = {
        "endpoint_id": "ep1",
        "method": "GET",
        "url": "https://example.test/health",
        "payload_strategy": "static",
    }
    endpoint.update(endpoint_overrides)
    return {"endpoints": [endpoint]}


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


def test_eventbridge_detail_wrapper_is_accepted_without_schedule_occurrence_id() -> None:
    event = validate_event(
        {
            "version": "0",
            "detail": {
                "client_id": "c",
                "audit_id": "a",
                "scenario_type": "baseline_health",
                "triggered_by": "manual",
                "schedule_type": "manual",
            },
        }
    )

    assert event.client_id == "c"
    assert event.audit_id == "a"
    assert event.scenario_type == "baseline_health"
    assert event.triggered_by == "manual"
    assert validate_run_id(event.run_id) == event.run_id


def test_direct_manual_event_is_accepted_without_schedule_occurrence_id() -> None:
    event = validate_event(
        {
            "client_id": "c",
            "audit_id": "a",
            "scenario_type": "baseline_health",
            "triggered_by": "manual",
            "schedule_type": "manual",
            "stage": "dev",
        }
    )

    assert event.client_id == "c"
    assert event.triggered_by == "manual"


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


VALIDATOR_MIRRORS = [
    (validate_endpoint_config, ConfigError),
    (validate_src_endpoint_config, SrcConfigError),
]


@pytest.mark.parametrize("validator,error_cls", VALIDATOR_MIRRORS)
def test_endpoint_expected_status_nested_and_top_level_aliases_normalize(
    validator, error_cls
) -> None:
    del error_cls
    nested = validator(endpoint_config_with({"assertions": {"expected_status_codes": [200]}}))
    top_level_list = validator(endpoint_config_with({"expected_status_codes": [200]}))
    top_level_int = validator(endpoint_config_with({"expected_status_code": 200}))
    top_level_multi = validator(endpoint_config_with({"expected_status_codes": [200, 204]}))
    agreeing = validator(
        endpoint_config_with(
            {
                "expected_status_codes": [200],
                "assertions": {"expected_status_codes": [200], "expect_json": True},
            }
        )
    )

    assert nested[0]["assertions"]["expected_status_codes"] == [200]
    assert top_level_list[0]["assertions"]["expected_status_codes"] == [200]
    assert "expected_status_codes" not in top_level_list[0]
    assert top_level_int[0]["assertions"]["expected_status_codes"] == [200]
    assert "expected_status_code" not in top_level_int[0]
    assert top_level_multi[0]["assertions"]["expected_status_codes"] == [200, 204]
    assert agreeing[0]["assertions"] == {"expected_status_codes": [200], "expect_json": True}


@pytest.mark.parametrize("validator,error_cls", VALIDATOR_MIRRORS)
def test_endpoint_expected_status_conflicts_fail_validation(validator, error_cls) -> None:
    with pytest.raises(error_cls) as exc:
        validator(
            endpoint_config_with(
                {
                    "expected_status_codes": [201],
                    "assertions": {"expected_status_codes": [200]},
                }
            )
        )

    assert exc.value.error_type == "CONFIG_VALIDATION_ERROR"
    assert "Conflicting expected status assertions" in str(exc.value)


@pytest.mark.parametrize(
    "expected_status",
    [[], [True], ["200"], [200.0], True, "200", [99], [600]],
)
@pytest.mark.parametrize("validator,error_cls", VALIDATOR_MIRRORS)
def test_endpoint_expected_status_invalid_values_fail_validation(
    validator, error_cls, expected_status
) -> None:
    with pytest.raises(error_cls) as exc:
        validator(endpoint_config_with({"expected_status_codes": expected_status}))

    assert exc.value.error_type == "CONFIG_VALIDATION_ERROR"


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


def test_api_runner_missing_assertions_uses_default_status_range() -> None:
    class Response:
        status_code = 302

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
            "assertions": {},
        }
    )

    assert outcome.failure_type == FAILURE_PASS
    assert outcome.assertion_results["expected_status_codes"] == list(range(200, 400))


def test_api_runner_status_302_fails_when_only_200_configured() -> None:
    class Response:
        status_code = 302

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
            "assertions": {"expected_status_codes": [200]},
        }
    )

    assert outcome.failure_type == FAILURE_ASSERTION
    assert outcome.assertion_results["expected_status_codes"] == [200]
    assert outcome.assertion_results["status_code_matched"] is False


def test_orchestrator_raw_result_uses_normalized_top_level_expected_status_codes() -> None:
    class Response:
        status_code = 200

    class Session:
        def request(self, **kwargs):  # noqa: ARG002
            return Response()

    objects = valid_config_objects()
    endpoint = objects["configs/client/audits/audit/endpoints.json"]["endpoints"][0]
    endpoint["expected_status_codes"] = [200]
    s3api = FakeS3Api(objects)
    orchestrator = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", s3api),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=ApiRunner(Session()),
    )

    response = orchestrator.run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "baseline_health",
            "triggered_by": "operator",
            "run_id": "raw_norm_123",
        }
    )

    records = s3api.objects[response["raw_result_s3_key"]]["results"]
    assert response["status"] == "COMPLETED"
    assert records[0]["assertion_results"]["expected_status_codes"] == [200]
    assert records[0]["assertion_results"]["status_code_matched"] is True


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


def test_handler_first_line_log_contains_only_event_keys(monkeypatch, capsys) -> None:
    class FakeOrchestrator:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def run(self, event):
            return {"status": "completed", "run_id": "safe_run_123"}

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
    monkeypatch.setattr(orchestrator_handler, "boto3", FakeBoto3())
    monkeypatch.setattr(orchestrator_handler, "CoreEngineOrchestrator", FakeOrchestrator)

    response = orchestrator_handler.handler(
        {"client_id": "client", "audit_id": "audit", "token": "secret-token-value"}, None
    )

    log_record = json.loads(capsys.readouterr().out.splitlines()[0])
    assert response["status"] == "completed"
    assert log_record["event_type"] == "orchestrator_handler_started"
    assert log_record["event_keys"] == ["client_id", "audit_id", "token"]
    assert "secret-token-value" not in json.dumps(log_record)


def test_failure_metadata_update_error_is_logged_safely() -> None:
    class FailingMetadata:
        def keys(self, client_id, audit_id, run_id):
            return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#RUN#{run_id}"}

        def update_terminal(self, keys, payload):
            raise RuntimeError("token=secret-token-value")

    logger = CapturingLogger()
    orchestrator = CoreEngineOrchestrator(
        s3_storage=object(),
        metadata_storage=FailingMetadata(),
        secrets_client=object(),
        logger=logger,
    )
    event = validate_event(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "release_smoke",
            "triggered_by": "manual",
            "run_id": "safe_run_123",
        }
    )

    response = orchestrator._failure_response(  # noqa: SLF001
        EngineError("ORCHESTRATION_ERROR", "Orchestration failed"),
        event=event,
        started_item={"status": "STARTED"},
    )

    assert response["status"] == "FAILED"
    messages = [record["message"] for record in logger.records]
    assert "terminal_metadata_update_started" in messages
    assert "terminal_metadata_update_failed" in messages
    assert "run_failed" in messages
    failed_record = next(
        record
        for record in logger.records
        if record["message"] == "terminal_metadata_update_failed"
    )
    assert failed_record["error_type"] == "RuntimeError"
    assert "secret-token-value" not in json.dumps(logger.records)


def test_orchestrator_success_emits_sanitized_milestone_logs_in_order() -> None:
    logger = CapturingLogger()
    orchestrator = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", FakeS3Api(valid_config_objects())),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=PassingRunner(),
        logger=logger,
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

    messages = [record["message"] for record in logger.records]
    assert response["status"] == "COMPLETED"
    expected_order = [
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
    positions = [messages.index(message) for message in expected_order]
    assert positions == sorted(positions)
    assert "secret-for" not in json.dumps(logger.records)


def test_repeated_stability_iteration_count_one_records_iteration_metadata() -> None:
    objects = valid_config_objects()
    objects["configs/client/audits/audit/audit_config.json"]["repeated_schedule"] = {
        "scenario_type": "repeated_stability",
        "iteration_count": 1,
    }
    s3api = FakeS3Api(objects)
    orchestrator = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", s3api),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=PassingRunner(),
    )

    response = orchestrator.run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "repeated_stability",
            "triggered_by": "operator",
            "run_id": "repeat_run_1",
        }
    )

    raw = s3api.objects[response["raw_result_s3_key"]]
    assert len(raw["results"]) == 1
    assert raw["results"][0]["schedule_iteration_number"] == 1
    assert raw["results"][0]["schedule_iteration_count"] == 1
    assert raw["results"][0]["payload_iteration_number"] == 1


def test_repeated_stability_iteration_count_five_runs_each_endpoint_five_times() -> None:
    objects = valid_config_objects()
    objects["configs/client/audits/audit/audit_config.json"]["repeated_schedule"] = {
        "scenario_type": "repeated_stability",
        "iteration_count": 5,
    }
    s3api = FakeS3Api(objects)
    orchestrator = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", s3api),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=PassingRunner(),
    )

    response = orchestrator.run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "repeated_stability",
            "triggered_by": "operator",
            "run_id": "repeat_run_5",
        }
    )

    records = s3api.objects[response["raw_result_s3_key"]]["results"]
    assert len(records) == 5
    assert [record["schedule_iteration_number"] for record in records] == [1, 2, 3, 4, 5]
    assert {record["schedule_iteration_count"] for record in records} == {5}
    assert {record["iteration_count"] for record in records} == {5}


def test_repeated_stability_static_get_no_body_includes_iteration_metadata() -> None:
    objects = valid_config_objects()
    objects["configs/client/audits/audit/audit_config.json"]["repeated_schedule"] = {
        "scenario_type": "repeated_stability",
        "iteration_count": 2,
    }
    # The default fixture endpoint is a static GET with no payload/body.
    s3api = FakeS3Api(objects)
    orchestrator = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", s3api),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=PassingRunner(),
    )

    response = orchestrator.run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "repeated_stability",
            "triggered_by": "operator",
            "run_id": "repeat_static_get",
        }
    )

    records = s3api.objects[response["raw_result_s3_key"]]["results"]
    assert len(records) == 2
    assert all(record["method"] == "GET" for record in records)
    assert [record["schedule_iteration_number"] for record in records] == [1, 2]


def test_repeated_stability_multiplies_schedule_and_payload_iterations() -> None:
    objects = valid_config_objects()
    objects["configs/client/audits/audit/audit_config.json"]["repeated_schedule"] = {
        "scenario_type": "repeated_stability",
        "iteration_count": 2,
    }
    objects["configs/client/audits/audit/endpoints.json"]["endpoints"][0]["payload_iterations"] = 3
    s3api = FakeS3Api(objects)
    orchestrator = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", s3api),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=PassingRunner(),
    )

    response = orchestrator.run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "repeated_stability",
            "triggered_by": "operator",
            "run_id": "repeat_payloads",
        }
    )

    records = s3api.objects[response["raw_result_s3_key"]]["results"]
    assert len(records) == 6
    assert [
        (record["schedule_iteration_number"], record["payload_iteration_number"])
        for record in records
    ] == [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (2, 3)]
    assert {record["payload_iteration_count"] for record in records} == {3}


def test_scheduled_repeated_event_preserves_iteration_metadata() -> None:
    objects = valid_config_objects()
    objects["configs/client/audits/audit/audit_config.json"]["repeated_schedule"] = {
        "scenario_type": "repeated_stability",
        "iteration_count": 5,
    }
    s3api = FakeS3Api(objects)
    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", s3api),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=PassingRunner(),
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "repeated_stability",
            "triggered_by": "eventbridge_scheduler",
            "repeated": {"iteration_count": 5},
            "iteration": 3,
            "run_id": "repeat_sched_3",
        }
    )

    records = s3api.objects[response["raw_result_s3_key"]]["results"]
    assert len(records) == 1
    assert records[0]["schedule_iteration_number"] == 3
    assert records[0]["schedule_iteration_count"] == 5


def test_repeated_stability_rejects_missing_and_non_integer_iteration_count() -> None:
    for repeated_schedule in ({"scenario_type": "repeated_stability"}, {"iteration_count": "5"}):
        objects = valid_config_objects()
        objects["configs/client/audits/audit/audit_config.json"]["repeated_schedule"] = (
            repeated_schedule
        )
        response = CoreEngineOrchestrator(
            s3_storage=S3StorageClient("bucket", FakeS3Api(objects)),
            metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
            secrets_client=SecretsManagerClient(FakeSecrets()),
            runner=PassingRunner(),
        ).run(
            {
                "client_id": "client",
                "audit_id": "audit",
                "scenario_type": "repeated_stability",
                "triggered_by": "operator",
                "run_id": f"repeat_bad_{len(str(repeated_schedule))}",
            }
        )

        assert response["status"] == "FAILED"
        assert response["failure_summary"]["error_type"] == "CONFIG_VALIDATION_ERROR"


def test_repeated_stability_accepts_max_iteration_count() -> None:
    objects = valid_config_objects()
    objects["configs/client/audits/audit/audit_config.json"]["repeated_schedule"] = {
        "scenario_type": "repeated_stability",
        "iteration_count": MAX_REPEATED_ITERATIONS,
    }
    s3api = FakeS3Api(objects)
    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", s3api),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=PassingRunner(),
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "repeated_stability",
            "triggered_by": "operator",
            "run_id": "repeat_max_count",
        }
    )

    assert response["status"] == "COMPLETED"
    assert len(s3api.objects[response["raw_result_s3_key"]]["results"]) == MAX_REPEATED_ITERATIONS


def test_repeated_stability_rejects_max_plus_one_iteration_count() -> None:
    objects = valid_config_objects()
    objects["configs/client/audits/audit/audit_config.json"]["repeated_schedule"] = {
        "scenario_type": "repeated_stability",
        "iteration_count": MAX_REPEATED_ITERATIONS + 1,
    }

    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", FakeS3Api(objects)),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=PassingRunner(),
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "repeated_stability",
            "triggered_by": "operator",
            "run_id": "repeat_over_max",
        }
    )

    assert response["status"] == "FAILED"
    assert response["failure_summary"]["error_type"] == "CONFIG_VALIDATION_ERROR"


def test_schedule_validation_rejects_max_plus_one_repeated_iterations() -> None:
    with pytest.raises(ValidationError):
        validate_schedule_config(
            {
                "client_id": "client",
                "audit_id": "audit",
                "repeated": [
                    {
                        "scenario_type": "repeated_stability",
                        "iteration_count": MAX_REPEATED_ITERATIONS + 1,
                    }
                ],
            },
            {
                "start_time": "2026-05-19T00:00:00Z",
                "end_time": "2026-05-21T00:00:00Z",
            },
        )


def test_baseline_health_remains_single_pass_by_default() -> None:
    objects = valid_config_objects()
    objects["configs/client/audits/audit/audit_config.json"]["repeated_schedule"] = {
        "scenario_type": "repeated_stability",
        "iteration_count": 5,
    }
    s3api = FakeS3Api(objects)
    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", s3api),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=PassingRunner(),
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "baseline_health",
            "triggered_by": "operator",
            "run_id": "baseline_single",
        }
    )

    records = s3api.objects[response["raw_result_s3_key"]]["results"]
    assert len(records) == 1
    assert records[0]["schedule_iteration_count"] == 1


def test_manual_burst_without_windows_uses_fallback_defaults_and_raw_evidence() -> None:
    objects = valid_config_objects()
    s3api = FakeS3Api(objects)

    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", s3api),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=PassingRunner(),
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "burst_stability",
            "triggered_by": "manual",
            "run_id": "burst_manual",
        }
    )

    records = s3api.objects[response["raw_result_s3_key"]]["results"]
    assert response["status"] == "COMPLETED"
    assert len(records) == 10
    assert [record["burst_request_number"] for record in records] == list(range(1, 11))
    assert {record["burst_request_count"] for record in records} == {10}
    assert {record["burst_concurrency"] for record in records} == {2}
    assert {record["burst_mode"] for record in records} == {"manual_fallback"}
    assert {record["burst_window_id"] for record in records} == {None}
    assert {record["burst_window_start"] for record in records} == {None}


def test_manual_burst_caps_lower_than_defaults_clamp_effective_values() -> None:
    objects = valid_config_objects()
    audit = objects["configs/client/audits/audit/audit_config.json"]
    audit["operational_caps"] = {"max_requests_per_run": 3, "max_concurrency": 1}
    s3api = FakeS3Api(objects)

    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", s3api),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=PassingRunner(),
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "burst_stability",
            "triggered_by": "manual",
            "run_id": "burst_clamp",
        }
    )

    records = s3api.objects[response["raw_result_s3_key"]]["results"]
    assert len(records) == 3
    assert {record["burst_request_count"] for record in records} == {3}
    assert {record["burst_concurrency"] for record in records} == {1}


def test_scheduled_burst_uses_window_metadata_and_ignores_manual_defaults() -> None:
    objects = valid_config_objects()
    audit = objects["configs/client/audits/audit/audit_config.json"]
    audit["burst_schedule"] = {
        "enabled": True,
        "manual_burst_defaults": {"enabled": True, "request_count": 99, "concurrency": 9},
        "windows": [{"request_count": 4, "concurrency": 2, "start_time": "09:00"}],
    }
    s3api = FakeS3Api(objects)

    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", s3api),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=PassingRunner(),
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "burst_stability",
            "triggered_by": "eventbridge_scheduler",
            "schedule_type": "burst",
            "scheduled_at": "2026-05-20T09:00:00Z",
            "burst": {
                "request_count": 4,
                "concurrency": 2,
                "window_id": "window-1",
                "window_start": "2026-05-20T09:00:00Z",
            },
            "run_id": "burst_sched",
        }
    )

    records = s3api.objects[response["raw_result_s3_key"]]["results"]
    assert len(records) == 4
    assert {record["burst_mode"] for record in records} == {"scheduled_window"}
    assert {record["burst_request_count"] for record in records} == {4}
    assert {record["burst_window_id"] for record in records} == {"window-1"}
    assert {record["burst_window_start"] for record in records} == {"2026-05-20T09:00:00Z"}


def test_scheduled_burst_without_enabled_window_fails_before_outbound_requests() -> None:
    class FailingRunner:
        def execute(self, *args, **kwargs):  # noqa: ARG002
            raise AssertionError("scheduled burst should fail before outbound requests")

    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", FakeS3Api(valid_config_objects())),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=FailingRunner(),
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "burst_stability",
            "triggered_by": "eventbridge_scheduler",
            "schedule_type": "burst",
            "scheduled_at": "2026-05-20T09:00:00Z",
            "burst": {"request_count": 4, "concurrency": 2},
            "run_id": "burst_no_window",
        }
    )

    assert response["status"] == "FAILED"
    assert response["failure_summary"]["error_type"] == "CONFIG_VALIDATION_ERROR"


def test_burst_request_count_is_total_and_endpoints_are_round_robin() -> None:
    objects = valid_config_objects()
    endpoints = objects["configs/client/audits/audit/endpoints.json"]["endpoints"]
    endpoints.extend(
        [{**endpoints[0], "endpoint_id": "ep2"}, {**endpoints[0], "endpoint_id": "ep3"}]
    )
    objects["configs/client/audits/audit/audit_config.json"]["burst_schedule"] = {
        "enabled": False,
        "windows": [],
        "manual_burst_defaults": {"enabled": True, "request_count": 5, "concurrency": 2},
    }
    runner = TrackingRunner()
    s3api = FakeS3Api(objects)

    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", s3api),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=runner,
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "burst_stability",
            "triggered_by": "manual",
            "run_id": "burst_rr",
        }
    )

    records = s3api.objects[response["raw_result_s3_key"]]["results"]
    assert len(records) == 5
    assert [record["endpoint_id"] for record in records] == ["ep1", "ep2", "ep3", "ep1", "ep2"]


def test_burst_concurrency_is_global_cap() -> None:
    objects = valid_config_objects()
    objects["configs/client/audits/audit/audit_config.json"]["burst_schedule"] = {
        "enabled": False,
        "windows": [],
        "manual_burst_defaults": {"enabled": True, "request_count": 6, "concurrency": 2},
    }
    runner = TrackingRunner(sleep_seconds=0.01)

    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", FakeS3Api(objects)),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=runner,
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "burst_stability",
            "triggered_by": "manual",
            "run_id": "burst_conc",
        }
    )

    assert response["status"] == "COMPLETED"
    assert runner.max_active <= 2


def test_validation_failure_emits_sanitized_error_log_without_payload_leak() -> None:
    logger = CapturingLogger()
    response = CoreEngineOrchestrator(
        s3_storage=object(), metadata_storage=object(), secrets_client=object(), logger=logger
    ).run(
        {
            "audit_id": "audit",
            "scenario_type": "release_smoke",
            "triggered_by": "operator",
            "authorization": "Bearer secret-token-value",
        }
    )

    assert response["status"] == "FAILED"
    messages = [record["message"] for record in logger.records]
    assert "event_validation_failed" in messages
    run_failed = next(record for record in logger.records if record["message"] == "run_failed")
    assert run_failed["level"] == "ERROR"
    serialized = json.dumps(logger.records)
    assert "secret-token-value" not in serialized
    assert "authorization" not in serialized


def test_config_load_failure_emits_sanitized_error_log() -> None:
    logger = CapturingLogger()
    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", FakeS3Api()),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        logger=logger,
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "release_smoke",
            "triggered_by": "operator",
            "run_id": "safe_run_123",
        }
    )

    assert response["status"] == "FAILED"
    record = next(record for record in logger.records if record["message"] == "config_load_failed")
    assert record["level"] == "ERROR"
    assert record["error_type"] == "CONFIG_LOAD_ERROR"
    assert "token" not in json.dumps(record).lower()


def test_raw_result_write_failure_emits_sanitized_error_log() -> None:
    class FailingPutS3(FakeS3Api):
        def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803, ARG002
            if Key.startswith("raw-results/"):
                raise RuntimeError("token=secret-token-value")
            super().put_object(Bucket, Key, Body, ContentType)

    logger = CapturingLogger()
    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", FailingPutS3(valid_config_objects())),
        metadata_storage=DynamoDBMetadataClient("table", FakeDynamo()),
        secrets_client=SecretsManagerClient(FakeSecrets()),
        runner=PassingRunner(),
        logger=logger,
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "release_smoke",
            "triggered_by": "operator",
            "run_id": "safe_run_123",
        }
    )

    assert response["status"] == "FAILED"
    record = next(
        record for record in logger.records if record["message"] == "raw_result_write_failed"
    )
    assert record["level"] == "ERROR"
    assert record["error_type"] == "STORAGE_ERROR"
    assert "secret-token-value" not in json.dumps(logger.records)


def test_logging_configuration_enables_info_logs(monkeypatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger("release-confidence-platform").setLevel(logging.WARNING)

    orchestrator_handler.configure_logging()

    assert logging.getLogger().level <= logging.INFO
    assert logging.getLogger("release-confidence-platform").level <= logging.INFO


def test_structured_orchestrator_logs_do_not_leak_payload_or_traceback(caplog) -> None:
    caplog.set_level(logging.INFO, logger="release-confidence-platform")
    orchestrator = CoreEngineOrchestrator(
        s3_storage=object(),
        metadata_storage=object(),
        secrets_client=object(),
        logger=StructuredLogger(),
    )

    orchestrator.run(
        {
            "audit_id": "audit",
            "scenario_type": "release_smoke",
            "triggered_by": "operator",
            "headers": {"Authorization": "Bearer secret-token-value"},
            "payload": {"token": "secret-token-value"},
        }
    )

    emitted = "\n".join(record.getMessage() for record in caplog.records)
    assert "secret-token-value" not in emitted
    assert '"headers"' not in emitted
    assert '"payload"' not in emitted
    assert "Traceback" not in emitted


def test_dynamodb_client_errors_map_to_actionable_storage_errors() -> None:
    class DeniedDynamo:
        def get_item(self, TableName, Key):  # noqa: N803, ARG002
            raise ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "token=super-secret"}},
                "GetItem",
            )

    with pytest.raises(StorageError) as exc:
        DynamoDBMetadataClient("table", DeniedDynamo()).metadata_exists(
            "client", "audit", "safe_run_123"
        )

    assert exc.value.error_type == "STORAGE_PERMISSION_ERROR"
    assert "operation=get_item" in exc.value.message
    assert "required_permissions=dynamodb:GetItem" in exc.value.message
    assert "super-secret" not in exc.value.message
