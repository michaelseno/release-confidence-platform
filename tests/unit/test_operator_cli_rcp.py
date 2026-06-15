from __future__ import annotations

import json
from argparse import Namespace
from datetime import date
from pathlib import Path

import pytest
from botocore.exceptions import ClientError, ParamValidationError

from packages.storage.eventbridge_scheduler_client import (
    EventBridgeSchedulerClient as PackagesEventBridgeSchedulerClient,
)
from release_confidence_platform.audit_lifecycle.cancellation import AuditCancellationService
from release_confidence_platform.audit_scheduling.service import AuditSchedulingService
from release_confidence_platform.config.audit_validation_service import AuditConfigValidationService
from release_confidence_platform.config.stage_config import StageConfig, StageConfigLoader
from release_confidence_platform.core.audit_creation_service import AuditCreationService
from release_confidence_platform.core.exceptions import EngineError
from release_confidence_platform.core.manual_run_service import ManualRunInvocationService
from release_confidence_platform.operator_cli import services
from release_confidence_platform.operator_cli.config_init import ConfigInitService
from release_confidence_platform.operator_cli.main import build_parser
from release_confidence_platform.operator_cli.result import render, render_error
from release_confidence_platform.storage.aws_client_factory import AwsClientFactory
from release_confidence_platform.storage.eventbridge_scheduler_client import (
    EventBridgeSchedulerClient,
    _create_schedule_request_shape,
)
from release_confidence_platform.storage.lambda_client import LambdaInvocationClient
from release_confidence_platform.storage.s3_client import S3StorageClient


class FakeS3:
    def __init__(self, objects=None):
        self.objects = objects or {}
        self.writes = []

    def object_exists(self, key):
        return key in self.objects

    def write_json(self, key, payload, *, overwrite=False):
        if not overwrite and key in self.objects:
            raise AssertionError("unexpected overwrite")
        self.writes.append((key, payload, overwrite))
        self.objects[key] = payload

    def read_json(self, key):
        return self.objects[key]


class FakeRepo:
    def __init__(self, item=None, *, fail_put=False):
        self.item = item
        self.fail_put = fail_put
        self.puts = []
        self.force_updates = []
        self.transitions = []
        self.schedules = []
        self.cleanup_errors = []

    def audit_keys(self, client_id, audit_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}"}

    def get_audit_metadata(self, client_id, audit_id):
        if self.item is None:
            from release_confidence_platform.core.exceptions import StorageError

            raise StorageError("not found", "AUDIT_NOT_FOUND")
        return self.item

    def put_audit_metadata_once(self, item):
        if self.fail_put:
            from release_confidence_platform.core.exceptions import StorageError

            raise StorageError("metadata write failed", "STORAGE_ERROR")
        self.puts.append(item)
        self.item = item

    def update_for_force_recreate(self, item):
        self.force_updates.append(item)
        self.item = {
            **(self.item or {}),
            **item,
            "lifecycle_history": [item["force_history_entry"]],
        }

    def append_lifecycle_transition(self, **kwargs):
        self.transitions.append(kwargs)
        self.item["lifecycle_state"] = kwargs["next_state"]

    def set_schedules(self, client_id, audit_id, schedules):
        self.schedules = schedules
        self.item["schedules"] = schedules

    def record_cleanup_errors(self, client_id, audit_id, cleanup_errors):
        self.cleanup_errors = cleanup_errors
        self.item["cleanup_errors"] = cleanup_errors


class FakeScheduler:
    def __init__(self, fail_delete=False):
        self.created = []
        self.deleted = []
        self.disabled = []
        self.fail_delete = fail_delete

    def create_schedule(self, definition):
        self.created.append(definition.name)
        return {**definition.metadata, "schedule_name": definition.name, "status": "created"}

    def delete_schedule(self, name, group=None):
        self.deleted.append((name, group))
        if self.fail_delete:
            raise RuntimeError("token=secret")

    def disable_schedule(self, name, group=None):
        self.disabled.append((name, group))
        if self.fail_delete:
            raise RuntimeError("Bearer abc")


class FakeLambda:
    def __init__(self):
        self.invocations = []

    def invoke(self, **kwargs):
        self.invocations.append(kwargs)
        return {"status_code": 202}


class FailingAwsS3:
    def __init__(self, code: str, message: str = "AWS service failure"):
        self.error = ClientError(
            {"Error": {"Code": code, "Message": message}}, operation_name="PutObject"
        )

    def put_object(self, **kwargs):
        raise self.error


class FailingAwsS3Head:
    def __init__(self, code: str, message: str = "AWS service failure"):
        self.error = ClientError(
            {"Error": {"Code": code, "Message": message}}, operation_name="HeadObject"
        )

    def head_object(self, **kwargs):
        raise self.error


class FailingAwsLambda:
    def __init__(self, code: str, message: str = "AWS Lambda failure"):
        self.error = ClientError(
            {"Error": {"Code": code, "Message": message}}, operation_name="Invoke"
        )
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        raise self.error


@pytest.fixture
def stage_config():
    return StageConfig(
        stage="dev",
        region="us-east-1",
        aws_profile="test",
        config_bucket="bucket",
        audit_metadata_table="table",
        orchestrator_function_name="orchestrator",
        scheduler_group_name="group",
        schedule_name_prefix="rcp-dev",
        scheduler_execution_target_arn="arn:aws:lambda:us-east-1:123:function:execution",
        scheduler_finalization_target_arn="arn:aws:lambda:us-east-1:123:function:finalization",
        scheduler_role_arn="arn:aws:iam::123:role/scheduler",
    )


def configs():
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
    return client, audit, endpoints


def write_configs(tmp_path: Path):
    paths = []
    for name, data in zip(("client.json", "audit.json", "endpoints.json"), configs(), strict=True):
        path = tmp_path / name
        path.write_text(json.dumps(data), encoding="utf-8")
        paths.append(path)
    return paths


def generated_config_init_paths(tmp_path: Path, *, include_sample_endpoints: bool = False):
    result = ConfigInitService(
        client_shortid="a8f3c2d1", audit_shortid="ef56ab78", today=date(2026, 5, 23)
    ).init(
        client_name="Demo Client",
        defaults="dev",
        output_dir=tmp_path,
        include_sample_endpoints=include_sample_endpoints,
    )
    root = Path(result["output_dir"])
    audit_dir = root / "audits" / result["audit_id"]
    return (
        root / "client_config.json",
        audit_dir / "audit_config.json",
        audit_dir / "endpoints.json",
    )


def test_generated_sample_endpoints_use_nested_expected_status_assertions(tmp_path):
    _, _, endpoints_path = generated_config_init_paths(tmp_path, include_sample_endpoints=True)
    endpoints = json.loads(endpoints_path.read_text(encoding="utf-8"))
    sample_endpoint = endpoints["endpoints"][0]

    assert sample_endpoint["assertions"]["expected_status_codes"] == [200]
    assert "expected_status_codes" not in sample_endpoint
    assert "expected_status_code" not in sample_endpoint


def create_args(client_config: Path, audit_config: Path, endpoints_config: Path, *, dry_run: bool):
    return Namespace(
        stage="dev",
        output="text",
        client_config=str(client_config),
        audit_config=str(audit_config),
        endpoints_config=str(endpoints_config),
        dry_run=dry_run,
        force=False,
    )


def test_parser_accepts_commands_and_requires_stage():
    parser = build_parser()
    args = parser.parse_args(
        [
            "audit",
            "run",
            "--client-id",
            "c",
            "--audit-id",
            "a",
            "--scenario-type",
            "baseline_health",
            "--stage",
            "dev",
        ]
    )
    assert args.audit_command == "run"
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["audit", "cancel", "--client-id", "c", "--audit-id", "a"])
    assert exc.value.code == 2


def test_packaged_entrypoint_exposes_operator_cli_parser():
    parser = build_parser()

    args = parser.parse_args(
        [
            "audit",
            "run",
            "--client-id",
            "c",
            "--audit-id",
            "a",
            "--scenario-type",
            "baseline_health",
            "--stage",
            "dev",
        ]
    )

    assert args.audit_command == "run"


def test_stage_config_env_override_precedence(tmp_path, monkeypatch):
    stage_dir = tmp_path / "config" / "stages"
    stage_dir.mkdir(parents=True)
    (stage_dir / "dev.json").write_text(
        json.dumps(
            StageConfig(
                stage="dev",
                region="file",
                aws_profile="p",
                config_bucket="b",
                audit_metadata_table="t",
                orchestrator_function_name="f",
                scheduler_group_name="g",
                schedule_name_prefix="x",
                scheduler_execution_target_arn="execution",
                scheduler_finalization_target_arn="finalization",
                scheduler_role_arn="role",
            ).to_dict()
        )
    )
    monkeypatch.setenv("RCP_AWS_REGION", "env-region")
    loaded = StageConfigLoader(root=tmp_path).load("dev")
    assert loaded.region == "env-region"
    monkeypatch.setenv("RCP_AWS_REGION", "")
    with pytest.raises(EngineError):
        StageConfigLoader(root=tmp_path).load("dev")
    monkeypatch.setenv("RCP_AWS_REGION", "   ")
    with pytest.raises(EngineError):
        StageConfigLoader(root=tmp_path).load("dev")


def test_aws_factory_maps_profile_setup_failure_to_structured_error(stage_config, monkeypatch):
    class ProfileNotFound(Exception):
        pass

    ProfileNotFound.__module__ = "botocore.exceptions"

    def fail_session(**kwargs):
        raise ProfileNotFound("The config profile (secret-profile) could not be found")

    monkeypatch.setattr(
        "release_confidence_platform.storage.aws_client_factory.boto3.Session", fail_session
    )

    with pytest.raises(EngineError) as exc:
        AwsClientFactory(stage_config)

    assert exc.value.error_type == "AWS_PROFILE_ERROR"
    assert exc.value.message == "AWS profile could not be loaded for stage"


def test_aws_profile_error_rendering_includes_stage_profile_next_step():
    rendered = render_error(
        "audit create",
        "dev",
        "AWS_PROFILE_ERROR",
        "AWS profile could not be loaded for stage",
    )

    assert "code: AWS_PROFILE_ERROR" in rendered
    assert "message: AWS profile could not be loaded for stage" in rendered
    assert "next_step: check config/stages/dev.json aws_profile" in rendered
    assert "RCP_AWS_PROFILE to a loadable AWS profile" in rendered
    assert "correct the error and retry" not in rendered


@pytest.mark.parametrize(
    ("aws_code", "expected_type", "expected_message"),
    [
        ("NoSuchBucket", "STORAGE_CONFIG_ERROR", "S3 config bucket not found for stage"),
        (
            "AccessDenied",
            "STORAGE_PERMISSION_ERROR",
            "S3 config bucket write permission denied",
        ),
    ],
)
def test_s3_write_client_errors_map_to_actionable_storage_errors(
    aws_code, expected_type, expected_message
):
    storage = S3StorageClient("configured-bucket", FailingAwsS3(aws_code))

    with pytest.raises(EngineError) as exc:
        storage.write_json(
            "configs/client1/client_config.json", {"token": "secret"}, overwrite=True
        )

    assert exc.value.error_type == expected_type
    assert expected_message in exc.value.message
    assert f"aws_error_code={aws_code}" in exc.value.message
    assert "key_prefix=configs" in exc.value.message
    assert "secret" not in exc.value.message.lower()


def test_s3_generic_write_error_remains_structured_with_safe_context():
    storage = S3StorageClient(
        "configured-bucket",
        FailingAwsS3("SlowDown", "Please reduce your request rate for Bearer abc123"),
    )

    with pytest.raises(EngineError) as exc:
        storage.write_json("configs/client1/client_config.json", {"ok": True}, overwrite=True)

    assert exc.value.error_type == "STORAGE_ERROR"
    assert "S3 config write failed" in exc.value.message
    assert "aws_error_code=SlowDown" in exc.value.message
    assert "aws_error_message=Please reduce your request rate for [REDACTED]" in exc.value.message
    assert "Bearer abc123" not in exc.value.message


def test_s3_write_existence_check_client_error_maps_to_actionable_guidance():
    storage = S3StorageClient("configured-bucket", FailingAwsS3Head("NoSuchBucket"))

    with pytest.raises(EngineError) as exc:
        storage.write_json("configs/client1/client_config.json", {"ok": True})

    assert exc.value.error_type == "STORAGE_CONFIG_ERROR"
    assert "S3 config bucket not found for stage" in exc.value.message
    assert "operation=head_object" in exc.value.message


def test_storage_error_rendering_includes_bucket_override_and_permissions_guidance():
    rendered = render_error(
        "audit create",
        "dev",
        "STORAGE_PERMISSION_ERROR",
        "S3 config bucket write permission denied (aws_error_code=AccessDenied)",
    )

    assert "code: STORAGE_PERMISSION_ERROR" in rendered
    assert "config/stages/dev.json config_bucket" in rendered
    assert "RCP_CONFIG_BUCKET=<real-dev-bucket>" in rendered
    assert "bucket exists in the configured region" in rendered
    assert "selected AWS profile has s3:PutObject and s3:HeadObject permissions" in rendered
    assert "configs/<client_id>/* prefix" in rendered
    assert "correct the error and retry" not in rendered


def test_lambda_resource_not_found_maps_to_actionable_config_error():
    client = FailingAwsLambda("ResourceNotFoundException", "Function not found: token=secret")
    storage = LambdaInvocationClient(client)

    with pytest.raises(EngineError) as exc:
        storage.invoke(
            function_name="rcp-dev-orchestrator-placeholder", payload={"token": "secret"}
        )

    assert exc.value.error_type == "LAMBDA_CONFIG_ERROR"
    assert "Lambda orchestrator function not found for stage" in exc.value.message
    assert "aws_error_code=ResourceNotFoundException" in exc.value.message
    assert "operation=invoke" in exc.value.message
    assert "function_name=rcp-dev-orchestrator-placeholder" in exc.value.message
    assert "secret" not in exc.value.message.lower()

    rendered = render_error("audit run", "dev", exc.value.error_type, exc.value.message)
    assert "config/stages/dev.json orchestrator_function_name" in rendered
    assert "RCP_ORCHESTRATOR_FUNCTION_NAME=<deployed-function-name>" in rendered
    assert "aws lambda get-function" in rendered
    assert "correct the error and retry" not in rendered


def test_lambda_access_denied_maps_to_actionable_permission_error():
    client = FailingAwsLambda("AccessDeniedException", "User is not authorized")
    storage = LambdaInvocationClient(client)

    with pytest.raises(EngineError) as exc:
        storage.invoke(
            function_name="release-confidence-platform-dev-coreEngineOrchestrator", payload={}
        )

    assert exc.value.error_type == "LAMBDA_PERMISSION_ERROR"
    assert "required_permission=lambda:InvokeFunction" in exc.value.message

    rendered = render_error("audit run", "dev", exc.value.error_type, exc.value.message)
    assert "lambda:InvokeFunction permissions" in rendered
    assert "selected AWS profile/region" in rendered


def test_lambda_generic_client_error_remains_structured_and_sanitized():
    client = FailingAwsLambda("TooManyRequestsException", "retry later with Bearer abc123")
    storage = LambdaInvocationClient(client)

    with pytest.raises(EngineError) as exc:
        storage.invoke(
            function_name="release-confidence-platform-dev-coreEngineOrchestrator", payload={}
        )

    assert exc.value.error_type == "LAMBDA_INVOCATION_FAILED"
    assert "Lambda invocation failed" in exc.value.message
    assert "aws_error_code=TooManyRequestsException" in exc.value.message
    assert "aws_error_message=retry later with [REDACTED]" in exc.value.message
    assert "Bearer abc123" not in exc.value.message


def test_lambda_success_notes_async_acceptance_not_handler_success():
    class AcceptedLambda:
        def invoke(self, **kwargs):
            return {"StatusCode": 202}

    result = LambdaInvocationClient(AcceptedLambda()).invoke(
        function_name="release-confidence-platform-dev-coreEngineOrchestrator", payload={}
    )

    assert result["status_code"] == 202
    assert result["accepted_async_invocation"] is True
    assert "does not guarantee handler success" in result["note"]


def test_lambda_sync_success_decodes_sanitized_handler_response():
    class SyncLambda:
        def invoke(self, **kwargs):
            return {
                "StatusCode": 200,
                "Payload": json.dumps(
                    {
                        "status": "completed",
                        "run_id": "safe_run_123",
                        "token": "secret-token-value",
                    }
                ).encode("utf-8"),
            }

    result = LambdaInvocationClient(SyncLambda()).invoke(
        function_name="release-confidence-platform-dev-coreEngineOrchestrator",
        payload={},
        invocation_type="RequestResponse",
    )

    assert result["handler_status"] == "completed"
    assert result["handler_succeeded"] is True
    assert result["handler_response"]["status"] == "completed"
    assert "secret-token-value" not in json.dumps(result)


def test_lambda_sync_failure_surfaces_handler_failure_without_api_acceptance_confusion():
    class SyncLambda:
        def invoke(self, **kwargs):
            return {
                "StatusCode": 200,
                "Payload": json.dumps(
                    {"status": "failed", "failure_summary": {"error_type": "INVALID_EVENT"}}
                ).encode("utf-8"),
            }

    result = LambdaInvocationClient(SyncLambda()).invoke(
        function_name="release-confidence-platform-dev-coreEngineOrchestrator",
        payload={},
        invocation_type="RequestResponse",
    )

    assert result["accepted_async_invocation"] is False
    assert result["handler_status"] == "failed"
    assert result["handler_succeeded"] is False


def test_lambda_sync_import_module_error_maps_to_dependency_diagnostic():
    class RuntimeImportFailureLambda:
        def invoke(self, **kwargs):
            return {
                "StatusCode": 200,
                "FunctionError": "Unhandled",
                "Payload": json.dumps(
                    {
                        "errorType": "Runtime.ImportModuleError",
                        "errorMessage": (
                            "Unable to import module "
                            "'apps.backend.handlers.orchestrator_handler': "
                            "No module named 'requests'; token=secret"
                        ),
                    }
                ).encode("utf-8"),
            }

    storage = LambdaInvocationClient(RuntimeImportFailureLambda())

    with pytest.raises(EngineError) as exc:
        storage.invoke(
            function_name="release-confidence-platform-dev-coreEngineOrchestrator",
            payload={"token": "secret"},
            invocation_type="RequestResponse",
        )

    assert exc.value.error_type == "LAMBDA_DEPENDENCY_IMPORT_ERROR"
    assert "Lambda runtime dependency/import failure detected" in exc.value.message
    assert "Runtime.ImportModuleError" in exc.value.message
    assert "No module named 'requests'" in exc.value.message
    assert "redeploy_with_packaged_backend_dependencies=true" in exc.value.message
    assert "token=secret" not in exc.value.message

    rendered = render_error("audit run", "dev", exc.value.error_type, exc.value.message)
    assert "redeploy the backend Lambda package" in rendered
    assert "apps/backend/requirements.txt" in rendered
    assert "async Lambda invocation may report acceptance" in rendered


def test_lambda_sync_runtime_error_remains_sanitized_when_not_import_failure():
    class RuntimeFailureLambda:
        def invoke(self, **kwargs):
            return {
                "StatusCode": 200,
                "FunctionError": "Unhandled",
                "Payload": b'{"errorType":"RuntimeError","errorMessage":"failed Bearer abc123"}',
            }

    storage = LambdaInvocationClient(RuntimeFailureLambda())

    with pytest.raises(EngineError) as exc:
        storage.invoke(
            function_name="release-confidence-platform-dev-coreEngineOrchestrator",
            payload={},
            invocation_type="RequestResponse",
        )

    assert exc.value.error_type == "LAMBDA_RUNTIME_ERROR"
    assert "Lambda runtime execution failed" in exc.value.message
    assert "Bearer abc123" not in exc.value.message


def test_scheduler_client_selects_target_by_schedule_type():
    class FakeAwsScheduler:
        def __init__(self):
            self.calls = []

        def create_schedule(self, **kwargs):
            self.calls.append(kwargs)
            return {}

    class Definition:
        name = "rcp-dev-client-audit-finalization"
        schedule_type = "finalization"
        expression = "at(2026-01-01T00:00:00)"
        schedule_expression_timezone = "UTC"
        target_payload = {"event_type": "audit_finalization"}
        metadata = {"schedule_type": "finalization"}

    aws_scheduler = FakeAwsScheduler()
    EventBridgeSchedulerClient(
        aws_scheduler,
        target_arns={
            "baseline": "arn:aws:lambda:us-east-1:123:function:execution",
            "finalization": "arn:aws:lambda:us-east-1:123:function:finalization",
        },
        role_arn="arn:aws:iam::123:role/scheduler",
        group_name="rcp-dev-schedules",
    ).create_schedule(Definition())

    assert aws_scheduler.calls[0]["Target"]["Arn"].endswith(":function:finalization")
    assert aws_scheduler.calls[0]["Target"]["RoleArn"] == "arn:aws:iam::123:role/scheduler"
    assert aws_scheduler.calls[0]["GroupName"] == "rcp-dev-schedules"
    assert aws_scheduler.calls[0]["ScheduleExpressionTimezone"] == "UTC"
    assert isinstance(aws_scheduler.calls[0]["Target"]["Input"], str)


def test_scheduler_client_includes_schedule_expression_timezone_from_metadata():
    class FakeAwsScheduler:
        def __init__(self):
            self.calls = []

        def create_schedule(self, **kwargs):
            self.calls.append(kwargs)
            return {}

    class Definition:
        name = "rcp-dev-client-audit-burst"
        schedule_type = "burst"
        expression = "at(2026-05-30T09:00:00)"
        target_payload = {"event_type": "audit_schedule_execution"}
        metadata = {
            "schedule_type": "burst",
            "schedule_expression_timezone": "Asia/Hong_Kong",
        }

    aws_scheduler = FakeAwsScheduler()
    EventBridgeSchedulerClient(aws_scheduler).create_schedule(Definition())

    assert aws_scheduler.calls[0]["ScheduleExpression"] == "at(2026-05-30T09:00:00)"
    assert aws_scheduler.calls[0]["ScheduleExpressionTimezone"] == "Asia/Hong_Kong"
    assert aws_scheduler.calls[0]["ActionAfterCompletion"] == "DELETE"


@pytest.mark.parametrize("expression", ["rate(15 minutes)", "cron(0 12 * * ? *)"])
def test_scheduler_client_does_not_set_auto_delete_for_recurring_expressions(expression):
    class FakeAwsScheduler:
        def __init__(self):
            self.calls = []

        def create_schedule(self, **kwargs):
            self.calls.append(kwargs)
            return {}

    class Definition:
        name = "rcp-dev-client-audit-baseline"
        schedule_type = "baseline"
        target_payload = {"event_type": "audit_schedule_execution"}
        metadata = {"schedule_type": "baseline"}

    Definition.expression = expression

    aws_scheduler = FakeAwsScheduler()
    EventBridgeSchedulerClient(aws_scheduler).create_schedule(Definition())

    assert "ActionAfterCompletion" not in aws_scheduler.calls[0]


def test_scheduler_client_serializes_sanitized_target_input_json():
    class FakeAwsScheduler:
        def __init__(self):
            self.calls = []

        def create_schedule(self, **kwargs):
            self.calls.append(kwargs)
            return {}

    class Definition:
        name = "rcp-dev-client-audit-baseline"
        schedule_type = "baseline"
        expression = "rate(15 minutes)"
        target_payload = {
            "event_type": "audit_schedule_execution",
            "client_id": "client1",
            "token_ref": "should-not-leak",
        }
        metadata = {"schedule_type": "baseline"}

    aws_scheduler = FakeAwsScheduler()
    EventBridgeSchedulerClient(
        aws_scheduler,
        target_arn="arn:aws:lambda:us-east-1:123:function:execution",
        role_arn="arn:aws:iam::123:role/scheduler",
    ).create_schedule(Definition())

    target_input = aws_scheduler.calls[0]["Target"]["Input"]
    assert isinstance(target_input, str)
    assert json.loads(target_input) == {
        "event_type": "audit_schedule_execution",
        "client_id": "client1",
        "token_ref": "[REDACTED]",
    }
    assert "should-not-leak" not in target_input


def test_scheduler_param_validation_maps_to_structured_error():
    class FailingAwsScheduler:
        def create_schedule(self, **kwargs):
            raise ParamValidationError(report="Invalid type for parameter Target.Input")

    class Definition:
        name = "rcp-dev-client-audit-baseline"
        schedule_type = "baseline"
        expression = "rate(15 minutes)"
        target_payload = {"event_type": "audit_schedule_execution"}
        metadata = {"schedule_type": "baseline"}

    with pytest.raises(EngineError) as exc:
        EventBridgeSchedulerClient(
            FailingAwsScheduler(),
            target_arn="arn:aws:lambda:us-east-1:123:function:execution",
            role_arn="arn:aws:iam::123:role/scheduler",
        ).create_schedule(Definition())

    assert exc.value.error_type == "SCHEDULE_REQUEST_VALIDATION_ERROR"
    assert "Target.Input" not in exc.value.message


@pytest.mark.parametrize(
    ("aws_code", "expected_type"),
    [
        ("AccessDeniedException", "SCHEDULE_PERMISSION_ERROR"),
        ("ResourceNotFoundException", "SCHEDULE_CONFIG_ERROR"),
    ],
)
def test_scheduler_client_errors_map_to_actionable_errors(aws_code, expected_type):
    class FailingAwsScheduler:
        def create_schedule(self, **kwargs):
            raise ClientError(
                {"Error": {"Code": aws_code, "Message": "token=secret"}},
                operation_name="CreateSchedule",
            )

    class Definition:
        name = "rcp-dev-client-audit-baseline"
        schedule_type = "baseline"
        expression = "rate(15 minutes)"
        target_payload = {"event_type": "audit_schedule_execution"}
        metadata = {"schedule_type": "baseline"}

    with pytest.raises(EngineError) as exc:
        EventBridgeSchedulerClient(
            FailingAwsScheduler(),
            target_arn="arn:aws:lambda:us-east-1:123:function:execution",
            role_arn="arn:aws:iam::123:role/scheduler",
        ).create_schedule(Definition())

    assert exc.value.error_type == expected_type
    assert f"aws_error_code={aws_code}" in exc.value.message
    assert "secret" not in exc.value.message.lower()


def _request_shape_from_scheduler_error(message: str) -> dict:
    marker = "request_shape="
    start = message.index(marker) + len(marker)
    end = message.rindex(")")
    return json.loads(message[start:end])


def test_scheduler_validation_error_includes_sanitized_provider_message_and_request_shape():
    class FailingAwsScheduler:
        def create_schedule(self, **kwargs):
            raise ClientError(
                {
                    "Error": {
                        "Code": "ValidationException",
                        "Message": "Invalid ScheduleExpression: rate(fifteen minutes)",
                    }
                },
                operation_name="CreateSchedule",
            )

    class Definition:
        name = "rcp-dev-client-audit-baseline"
        schedule_type = "baseline"
        expression = "rate(fifteen minutes)"
        target_payload = {
            "event_type": "audit_schedule_execution",
            "client_id": "client1",
            "token_ref": "should-not-leak",
        }
        metadata = {"schedule_type": "baseline"}

    with pytest.raises(EngineError) as exc:
        EventBridgeSchedulerClient(
            FailingAwsScheduler(),
            target_arn="arn:aws:lambda:us-east-1:123:function:execution",
            role_arn="arn:aws:iam::123:role/scheduler",
            group_name="rcp-dev-schedules",
        ).create_schedule(Definition())

    assert exc.value.error_type == "SCHEDULE_CONFIG_ERROR"
    assert "provider_message=Invalid ScheduleExpression: rate(fifteen minutes)" in exc.value.message
    request_shape = _request_shape_from_scheduler_error(exc.value.message)
    assert set(request_shape) == {
        "operation",
        "schedule_name",
        "group_name",
        "schedule_expression",
        "schedule_expression_timezone",
        "action_after_completion",
        "start_date",
        "end_date",
        "target_arn",
        "role_arn",
        "input_keys",
    }
    assert request_shape == {
        "operation": "create_schedule",
        "schedule_name": "rcp-dev-client-audit-baseline",
        "group_name": "rcp-dev-schedules",
        "schedule_expression": "rate(fifteen minutes)",
        "schedule_expression_timezone": None,
        "action_after_completion": None,
        "start_date": None,
        "end_date": None,
        "target_arn": "arn:aws:lambda:us-east-1:123:function:execution",
        "role_arn": "arn:aws:iam::123:role/scheduler",
        "input_keys": ["client_id", "event_type", "token_ref"],
    }
    assert "should-not-leak" not in exc.value.message
    assert "Target.Input" not in exc.value.message


def test_scheduler_validation_provider_message_redacts_auth_like_content():
    class FailingAwsScheduler:
        def create_schedule(self, **kwargs):
            raise ClientError(
                {
                    "Error": {
                        "Code": "ValidationException",
                        "Message": (
                            "Invalid target token=secret Bearer abc123 Cookie: session=xyz "
                            "api-key=raw password=hunter2"
                        ),
                    }
                },
                operation_name="CreateSchedule",
            )

    class Definition:
        name = "rcp-dev-client-audit-baseline"
        schedule_type = "baseline"
        expression = "rate(15 minutes)"
        target_payload = {"event_type": "audit_schedule_execution"}
        metadata = {"schedule_type": "baseline"}

    with pytest.raises(EngineError) as exc:
        EventBridgeSchedulerClient(
            FailingAwsScheduler(),
            target_arn="arn:aws:lambda:us-east-1:123:function:execution",
            role_arn="arn:aws:iam::123:role/scheduler",
        ).create_schedule(Definition())

    assert "provider_message=Invalid target token=[REDACTED] [REDACTED]" in exc.value.message
    assert "Cookie=[REDACTED]" in exc.value.message
    assert "api-key=[REDACTED]" in exc.value.message
    assert "password=[REDACTED]" in exc.value.message
    assert "secret" not in exc.value.message.lower()
    assert "abc123" not in exc.value.message
    assert "session=xyz" not in exc.value.message
    assert "raw" not in exc.value.message
    assert "hunter2" not in exc.value.message


def test_scheduler_request_shape_exposes_input_keys_only_and_handles_malformed_input():
    payload = {
        "Name": "rcp-dev-client-audit-baseline",
        "GroupName": "rcp-dev-schedules",
        "ScheduleExpression": "rate(15 minutes)",
        "ScheduleExpressionTimezone": "UTC",
        "StartDate": "2026-01-01T00:00:00Z",
        "EndDate": "2026-01-02T00:00:00Z",
        "Target": {
            "Arn": "arn:aws:lambda:us-east-1:123:function:execution",
            "RoleArn": "arn:aws:iam::123:role/scheduler",
            "Input": json.dumps({"event_type": "audit_schedule_execution", "payload": "value"}),
        },
        "Unsafe": "must-not-appear",
    }

    request_shape = _create_schedule_request_shape(payload)

    assert set(request_shape) == {
        "operation",
        "schedule_name",
        "group_name",
        "schedule_expression",
        "schedule_expression_timezone",
        "action_after_completion",
        "start_date",
        "end_date",
        "target_arn",
        "role_arn",
        "input_keys",
    }
    assert request_shape["input_keys"] == ["event_type", "payload"]
    assert "value" not in json.dumps(request_shape)
    assert "Input" not in request_shape
    payload["Target"]["Input"] = "{not-json"
    assert _create_schedule_request_shape(payload)["input_keys"] == []


def test_scheduler_config_error_rendering_includes_safe_diagnostics_text_and_json():
    message = (
        "EventBridge Scheduler rejected the request; verify scheduler stage configuration "
        "(operation=create_schedule, aws_error_code=ValidationException, "
        "provider_message=Invalid ScheduleExpression, "
        'request_shape={"operation": "create_schedule", "input_keys": ["event_type"]})'
    )

    text = render_error("audit schedule", "dev", "SCHEDULE_CONFIG_ERROR", message)
    rendered_json = json.loads(
        render_error("audit schedule", "dev", "SCHEDULE_CONFIG_ERROR", message, output="json")
    )

    assert "provider_message=Invalid ScheduleExpression" in text
    assert "request_shape=" in text
    assert "event_type" in text
    assert rendered_json["message"] == message


def test_packages_scheduler_mirror_includes_sanitized_validation_diagnostics():
    class FailingAwsScheduler:
        def create_schedule(self, **kwargs):
            raise ClientError(
                {
                    "Error": {
                        "Code": "ValidationException",
                        "Message": "Invalid ScheduleExpression token=secret",
                    }
                },
                operation_name="CreateSchedule",
            )

    class Definition:
        name = "rcp-dev-client-audit-baseline"
        schedule_type = "baseline"
        expression = "rate(15 minutes)"
        target_payload = {"event_type": "audit_schedule_execution", "secret_value": "nope"}
        metadata = {"schedule_type": "baseline"}

    with pytest.raises(Exception) as exc:
        PackagesEventBridgeSchedulerClient(
            FailingAwsScheduler(),
            target_arn="arn:aws:lambda:us-east-1:123:function:execution",
            role_arn="arn:aws:iam::123:role/scheduler",
        ).create_schedule(Definition())

    assert exc.value.error_type == "SCHEDULE_CONFIG_ERROR"
    assert "provider_message=Invalid ScheduleExpression token=[REDACTED]" in exc.value.message
    assert '"input_keys": ["event_type", "secret_value"]' in exc.value.message
    assert "nope" not in exc.value.message
    assert "token=secret" not in exc.value.message


def test_schedule_command_rejects_placeholder_scheduler_config_before_factory(monkeypatch):
    placeholder = StageConfig(
        stage="dev",
        region="us-east-1",
        aws_profile="test",
        config_bucket="bucket",
        audit_metadata_table="table",
        orchestrator_function_name="orchestrator",
        scheduler_group_name="rcp-dev-schedules-placeholder",
        schedule_name_prefix="rcp-dev",
        scheduler_execution_target_arn="arn:aws:lambda:us-east-1:000000000000:function:execution",
        scheduler_finalization_target_arn=(
            "arn:aws:lambda:us-east-1:000000000000:function:finalization"
        ),
        scheduler_role_arn="arn:aws:iam::000000000000:role/scheduler",
    )
    constructed = False

    class FailingFactory:
        def __init__(self, stage_config):
            nonlocal constructed
            constructed = True
            raise AssertionError("factory should not be constructed")

    monkeypatch.setattr(services, "_stage", lambda args: placeholder)
    monkeypatch.setattr(services, "AwsClientFactory", FailingFactory)

    with pytest.raises(EngineError) as exc:
        services.schedule_command(
            Namespace(
                stage="dev",
                client_id="client1",
                audit_id="audit1",
                allow_production=False,
                dry_run=False,
            )
        )

    assert exc.value.error_type == "SCHEDULER_CONFIG_ERROR"
    assert "scheduler_group_name" in exc.value.message
    assert "scheduler_execution_target_arn" in exc.value.message
    assert constructed is False


def test_scheduler_error_rendering_includes_config_next_step():
    rendered = render_error(
        "audit schedule",
        "dev",
        "SCHEDULE_PERMISSION_ERROR",
        "EventBridge Scheduler permission denied",
    )

    assert "code: SCHEDULE_PERMISSION_ERROR" in rendered
    assert "rcp config stage-info --stage dev" in rendered
    assert "RCP_SCHEDULER_GROUP_NAME" in rendered


def test_validate_rejects_over_48h(tmp_path):
    client, audit, endpoints = configs()
    audit["audit_window"]["end_at"] = "2026-01-04T00:00:01Z"
    with pytest.raises(EngineError):
        AuditConfigValidationService().validate_configs(
            client_config=client, audit_config=audit, endpoints_config=endpoints, stage="dev"
        )


def test_create_dry_run_reports_actions_no_mutation(tmp_path, stage_config):
    c, a, e = write_configs(tmp_path)
    s3 = FakeS3()
    repo = FakeRepo()
    result = AuditCreationService(
        stage_config=stage_config, s3_storage=s3, repository=repo
    ).create_from_files(
        client_config_path=str(c),
        audit_config_path=str(a),
        endpoints_config_path=str(e),
        dry_run=True,
    )
    assert result["status"] == "dry_run"
    assert len(result["planned_actions"]) == 4
    assert s3.writes == []
    assert repo.puts == []


def test_create_command_rejects_empty_generated_endpoints_before_aws(tmp_path, monkeypatch):
    c, a, e = generated_config_init_paths(tmp_path, include_sample_endpoints=False)
    constructed = False

    class FailingFactory:
        def __init__(self, stage_config):
            nonlocal constructed
            constructed = True
            raise AssertionError("AWS client factory should not be constructed")

    monkeypatch.setattr(services, "AwsClientFactory", FailingFactory)

    with pytest.raises(EngineError) as exc:
        services.create_command(create_args(c, a, e, dry_run=False))

    assert exc.value.error_type == "CONFIG_VALIDATION_ERROR"
    assert "at least one endpoint" in exc.value.message
    assert constructed is False


def test_validate_command_rejects_empty_generated_endpoints(tmp_path):
    c, a, e = generated_config_init_paths(tmp_path, include_sample_endpoints=False)

    with pytest.raises(EngineError) as exc:
        services.validate_command(create_args(c, a, e, dry_run=True))

    assert exc.value.error_type == "CONFIG_VALIDATION_ERROR"
    assert "at least one endpoint" in exc.value.message


def test_create_command_dry_run_rejects_empty_generated_endpoints_without_aws(
    tmp_path, monkeypatch
):
    c, a, e = generated_config_init_paths(tmp_path, include_sample_endpoints=False)

    class FailingFactory:
        def __init__(self, stage_config):
            raise AssertionError("dry-run must not construct AWS clients")

    monkeypatch.setattr(services, "AwsClientFactory", FailingFactory)

    with pytest.raises(EngineError) as exc:
        services.create_command(create_args(c, a, e, dry_run=True))

    assert exc.value.error_type == "CONFIG_VALIDATION_ERROR"


def test_create_command_valid_sample_generated_config_reaches_create_path(tmp_path, monkeypatch):
    c, a, e = generated_config_init_paths(tmp_path, include_sample_endpoints=True)
    constructed = False
    s3 = FakeS3()
    repo = FakeRepo()

    class FakeFactory:
        def __init__(self, stage_config):
            nonlocal constructed
            constructed = True

        def s3_storage(self):
            return s3

        def audit_metadata_repository(self):
            return repo

    monkeypatch.setattr(services, "AwsClientFactory", FakeFactory)

    result = services.create_command(create_args(c, a, e, dry_run=False))

    assert constructed is True
    assert result.status == "success"
    assert len(s3.writes) == 3
    assert repo.puts[0]["lifecycle_state"] == "DRAFT"


def test_create_command_dry_run_valid_config_reports_without_aws(tmp_path, monkeypatch):
    c, a, e = generated_config_init_paths(tmp_path, include_sample_endpoints=True)

    class FailingFactory:
        def __init__(self, stage_config):
            raise AssertionError("dry-run must not construct AWS clients")

    monkeypatch.setattr(services, "AwsClientFactory", FailingFactory)

    result = services.create_command(create_args(c, a, e, dry_run=True))

    assert result.status == "dry_run"
    assert result.data["planned_actions"]


def test_create_force_allows_draft_and_updates_only_config_keys(tmp_path, stage_config):
    c, a, e = write_configs(tmp_path)
    repo = FakeRepo({"client_id": "client1", "audit_id": "audit1", "lifecycle_state": "DRAFT"})
    s3 = FakeS3({"raw-results/client1/audit1/run.json": {"keep": True}})
    result = AuditCreationService(
        stage_config=stage_config, s3_storage=s3, repository=repo
    ).create_from_files(
        client_config_path=str(c),
        audit_config_path=str(a),
        endpoints_config_path=str(e),
        force=True,
    )
    assert result["force"] is True
    assert len(s3.writes) == 3
    assert all("raw-results" not in key for key, _, _ in s3.writes)
    assert repo.force_updates[0]["force_history_entry"]["reason"] == "force_recreate"


def test_create_metadata_failure_after_s3_writes_leaves_retryable_artifacts(tmp_path, stage_config):
    c, a, e = write_configs(tmp_path)
    s3 = FakeS3()
    repo = FakeRepo(fail_put=True)

    with pytest.raises(EngineError) as exc:
        AuditCreationService(
            stage_config=stage_config, s3_storage=s3, repository=repo
        ).create_from_files(
            client_config_path=str(c),
            audit_config_path=str(a),
            endpoints_config_path=str(e),
        )

    assert exc.value.error_type == "STORAGE_ERROR"
    assert len(s3.writes) == 3
    assert repo.puts == []


def test_create_retry_adopts_matching_s3_artifacts_when_metadata_absent(tmp_path, stage_config):
    c, a, e = write_configs(tmp_path)
    s3 = FakeS3()
    failing_repo = FakeRepo(fail_put=True)
    with pytest.raises(EngineError):
        AuditCreationService(
            stage_config=stage_config, s3_storage=s3, repository=failing_repo
        ).create_from_files(
            client_config_path=str(c),
            audit_config_path=str(a),
            endpoints_config_path=str(e),
        )
    initial_write_count = len(s3.writes)
    retry_repo = FakeRepo()

    result = AuditCreationService(
        stage_config=stage_config, s3_storage=s3, repository=retry_repo
    ).create_from_files(
        client_config_path=str(c),
        audit_config_path=str(a),
        endpoints_config_path=str(e),
    )

    assert result["status"] == "success"
    assert result["lifecycle_state"] == "DRAFT"
    assert len(retry_repo.puts) == 1
    assert len(s3.writes) == initial_write_count


def test_create_partial_existing_s3_artifacts_fail_with_diagnostics(tmp_path, stage_config):
    c, a, e = write_configs(tmp_path)
    client, _, _ = configs()
    s3 = FakeS3({"configs/client1/client_config.json": client})

    with pytest.raises(EngineError) as exc:
        AuditCreationService(
            stage_config=stage_config, s3_storage=s3, repository=FakeRepo()
        ).create_from_files(
            client_config_path=str(c),
            audit_config_path=str(a),
            endpoints_config_path=str(e),
        )

    assert exc.value.error_type == "PARTIAL_AUDIT_CREATE_EXISTS"
    assert "client_config:match:configs/client1/client_config.json" in exc.value.message
    assert (
        "audit_config:missing:configs/client1/audits/audit1/audit_config.json" in exc.value.message
    )
    assert (
        "endpoints_config:missing:configs/client1/audits/audit1/endpoints.json" in exc.value.message
    )
    assert "delete only the exact stale config objects" in exc.value.message


def test_create_mismatched_existing_s3_artifacts_fail_with_diagnostics(tmp_path, stage_config):
    c, a, e = write_configs(tmp_path)
    client, audit, endpoints = configs()
    audit = {**audit, "config_version": "different"}
    s3 = FakeS3(
        {
            "configs/client1/client_config.json": client,
            "configs/client1/audits/audit1/audit_config.json": audit,
            "configs/client1/audits/audit1/endpoints.json": endpoints,
        }
    )

    with pytest.raises(EngineError) as exc:
        AuditCreationService(
            stage_config=stage_config, s3_storage=s3, repository=FakeRepo()
        ).create_from_files(
            client_config_path=str(c),
            audit_config_path=str(a),
            endpoints_config_path=str(e),
        )

    assert exc.value.error_type == "PARTIAL_AUDIT_CREATE_EXISTS"
    assert (
        "audit_config:mismatch:configs/client1/audits/audit1/audit_config.json" in exc.value.message
    )
    assert len(s3.writes) == 0


def test_create_force_without_metadata_does_not_overwrite_mismatched_s3_artifacts(
    tmp_path, stage_config
):
    c, a, e = write_configs(tmp_path)
    client, audit, endpoints = configs()
    s3 = FakeS3(
        {
            "configs/client1/client_config.json": {**client, "config_version": "different"},
            "configs/client1/audits/audit1/audit_config.json": audit,
            "configs/client1/audits/audit1/endpoints.json": endpoints,
        }
    )

    with pytest.raises(EngineError) as exc:
        AuditCreationService(
            stage_config=stage_config, s3_storage=s3, repository=FakeRepo()
        ).create_from_files(
            client_config_path=str(c),
            audit_config_path=str(a),
            endpoints_config_path=str(e),
            force=True,
        )

    assert exc.value.error_type == "FORCE_RECREATE_BLOCKED"
    assert s3.writes == []


def test_config_object_and_partial_state_rendering_include_actionable_next_steps():
    config_exists = render_error(
        "audit create", "dev", "CONFIG_OBJECT_EXISTS", "Config object exists"
    )
    partial = render_error(
        "audit create",
        "dev",
        "PARTIAL_AUDIT_CREATE_EXISTS",
        "Partial audit create state exists; "
        "artifacts=client_config:mismatch:configs/client1/client_config.json",
    )

    assert "next_step:" in config_exists
    assert "Use --force only for existing DRAFT/FAILED metadata" in config_exists
    assert "correct the error and retry" not in config_exists
    assert "partial audit create state detected" in partial
    assert "delete only the exact stale config objects" in partial


def test_create_force_rejects_scheduled_before_mutation(tmp_path, stage_config):
    c, a, e = write_configs(tmp_path)
    repo = FakeRepo({"client_id": "client1", "audit_id": "audit1", "lifecycle_state": "SCHEDULED"})
    s3 = FakeS3()
    with pytest.raises(EngineError):
        AuditCreationService(
            stage_config=stage_config, s3_storage=s3, repository=repo
        ).create_from_files(
            client_config_path=str(c),
            audit_config_path=str(a),
            endpoints_config_path=str(e),
            force=True,
        )
    assert s3.writes == []
    assert repo.force_updates == []


@pytest.mark.parametrize("state", ["DRAFT", "FAILED"])
def test_create_force_succeeds_only_for_draft_or_failed(tmp_path, stage_config, state):
    c, a, e = write_configs(tmp_path)
    repo = FakeRepo({"client_id": "client1", "audit_id": "audit1", "lifecycle_state": state})
    s3 = FakeS3()

    result = AuditCreationService(
        stage_config=stage_config, s3_storage=s3, repository=repo
    ).create_from_files(
        client_config_path=str(c),
        audit_config_path=str(a),
        endpoints_config_path=str(e),
        force=True,
    )

    assert result["status"] == "success"
    assert result["force"] is True
    assert len(repo.force_updates) == 1
    assert all(write[2] is True for write in s3.writes)


@pytest.mark.parametrize("state", ["FINALIZING", "SCHEDULED", "RUNNING", "COMPLETED"])
def test_create_force_blocks_ineligible_lifecycle_states(tmp_path, stage_config, state):
    c, a, e = write_configs(tmp_path)
    repo = FakeRepo({"client_id": "client1", "audit_id": "audit1", "lifecycle_state": state})
    s3 = FakeS3()

    with pytest.raises(EngineError) as exc:
        AuditCreationService(
            stage_config=stage_config, s3_storage=s3, repository=repo
        ).create_from_files(
            client_config_path=str(c),
            audit_config_path=str(a),
            endpoints_config_path=str(e),
            force=True,
        )

    assert exc.value.error_type == "FORCE_RECREATE_BLOCKED"
    assert repo.force_updates == []
    assert s3.writes == []


def test_schedule_non_draft_lifecycle_error_includes_state_context(stage_config):
    _, audit, _ = configs()
    repo = FakeRepo(
        {
            "client_id": "client1",
            "audit_id": "audit1",
            "lifecycle_state": "FAILED",
            "config_s3_keys": {"audit_config": "audit.json"},
        }
    )
    scheduler = FakeScheduler()
    s3 = FakeS3({"audit.json": audit})

    with pytest.raises(EngineError) as exc:
        AuditSchedulingService(
            repository=repo,
            scheduler_client=scheduler,
            stage="dev",
            schedule_name_prefix="rcp-dev",
        ).schedule_from_persisted_audit(
            client_id="client1",
            audit_id="audit1",
            s3_storage=s3,
            dry_run=True,
        )

    assert exc.value.error_type == "INVALID_LIFECYCLE_STATE"
    assert "current_state=FAILED" in exc.value.message
    assert "required_state=DRAFT" in exc.value.message
    assert "client_id=client1" in exc.value.message
    assert "audit_id=audit1" in exc.value.message
    assert scheduler.created == []


def test_invalid_lifecycle_state_next_step_is_actionable():
    rendered = render_error(
        "audit schedule",
        "dev",
        "INVALID_LIFECYCLE_STATE",
        "Audit lifecycle does not allow scheduling "
        "(client_id=client1, audit_id=audit1, current_state=FAILED, required_state=DRAFT)",
    )

    assert "next_step:" in rendered
    assert "scheduling is only valid when audit lifecycle_state is DRAFT" in rendered
    assert "rcp audit list --client-id <client_id> --stage dev --output json" in rendered
    assert "fresh audit ID/config bundle" in rendered
    assert "audit create --force only when existing metadata is DRAFT or FAILED" in rendered
    assert "no active orphaned schedules" in rendered
    assert "Do not manually mutate lifecycle metadata" in rendered
    assert "correct the error and retry" not in rendered


def test_schedule_dry_run_skips_missing_disabled_blocks(stage_config):
    _, audit, _ = configs()
    audit["burst_schedule"] = {
        "enabled": False,
        "windows": [
            {"start_time": "01:00", "duration_minutes": 1, "request_count": 1, "concurrency": 1}
        ],
    }
    item = {
        "client_id": "client1",
        "audit_id": "audit1",
        "lifecycle_state": "DRAFT",
        "config_s3_keys": {"audit_config": "audit.json"},
    }
    repo = FakeRepo(item)
    scheduler = FakeScheduler()
    result = AuditSchedulingService(
        repository=repo, scheduler_client=scheduler, stage="dev", schedule_name_prefix="rcp-dev"
    ).schedule_from_persisted_audit(
        client_id="client1",
        audit_id="audit1",
        s3_storage=FakeS3({"audit.json": audit}),
        dry_run=True,
    )
    names = [s["schedule_type"] for s in result["planned_schedules"]]
    assert names == (["baseline"] * 96) + ["finalization"]
    assert scheduler.created == []


def test_schedule_from_draft_lifecycle_behavior_unchanged(stage_config):
    _, audit, _ = configs()
    item = {
        "client_id": "client1",
        "audit_id": "audit1",
        "lifecycle_state": "DRAFT",
        "config_s3_keys": {"audit_config": "audit.json"},
    }
    repo = FakeRepo(item)
    scheduler = FakeScheduler()

    result = AuditSchedulingService(
        repository=repo,
        scheduler_client=scheduler,
        stage="dev",
        schedule_name_prefix="rcp-dev",
    ).schedule_from_persisted_audit(
        client_id="client1",
        audit_id="audit1",
        s3_storage=FakeS3({"audit.json": audit}),
        dry_run=False,
    )

    assert result["status"] == "success"
    assert result["lifecycle_state"] == "SCHEDULED"
    assert repo.item["lifecycle_state"] == "SCHEDULED"
    assert len(scheduler.created) == 97


def test_schedule_dry_run_includes_finalization_when_key_absent(stage_config):
    """When finalization_schedule is absent from config, a finalization schedule must
    still be built.  _normalize_product_schedule_config previously injected
    {"enabled": False} for absent keys, silently suppressing finalization.  The correct
    behaviour is to let build_all()'s `or {"enabled": True}` fallback take effect."""
    _, audit, _ = configs()
    audit.pop("finalization_schedule")
    repo = FakeRepo(
        {
            "client_id": "client1",
            "audit_id": "audit1",
            "lifecycle_state": "DRAFT",
            "config_s3_keys": {"audit_config": "audit.json"},
        }
    )
    result = AuditSchedulingService(
        repository=repo,
        scheduler_client=FakeScheduler(),
        stage="dev",
        schedule_name_prefix="rcp-dev",
    ).schedule_from_persisted_audit(
        client_id="client1",
        audit_id="audit1",
        s3_storage=FakeS3({"audit.json": audit}),
        dry_run=True,
    )

    planned_types = [s["schedule_type"] for s in result["planned_schedules"]]
    assert "finalization" in planned_types, (
        "finalization schedule must be included even when config omits finalization_schedule key"
    )
    assert planned_types.count("baseline") == 96
    assert len(planned_types) == 97


def test_schedule_prod_requires_allow_production(stage_config):
    _, audit, _ = configs()
    audit["execution_environment"] = {
        "target_environment": "production",
        "allow_production_execution": True,
    }
    repo = FakeRepo(
        {
            "client_id": "client1",
            "audit_id": "audit1",
            "lifecycle_state": "DRAFT",
            "config_s3_keys": {"audit_config": "audit.json"},
        }
    )
    with pytest.raises(EngineError):
        AuditSchedulingService(
            repository=repo,
            scheduler_client=FakeScheduler(),
            stage="prod",
            schedule_name_prefix="rcp-prod",
        ).schedule_from_persisted_audit(
            client_id="client1",
            audit_id="audit1",
            s3_storage=FakeS3({"audit.json": audit}),
            allow_production=False,
        )


def test_run_dry_run_and_invalid_run_id(stage_config):
    lamb = FakeLambda()
    result = ManualRunInvocationService(stage_config=stage_config, lambda_client=lamb).run(
        client_id="client1", audit_id="audit1", scenario_type="baseline_health", dry_run=True
    )
    assert result["payload"]["triggered_by"] == "manual"
    assert result["payload"]["schedule_type"] == "manual"
    assert result["payload"]["stage"] == stage_config.stage
    assert "run_id" not in result["payload"]
    assert lamb.invocations == []
    with pytest.raises(EngineError):
        ManualRunInvocationService(stage_config=stage_config, lambda_client=lamb).run(
            client_id="client1", audit_id="audit1", scenario_type="baseline_health", run_id="../bad"
        )


def test_manual_run_uses_sync_invocation_and_surfaces_handler_status(stage_config):
    class SyncFakeLambda:
        def __init__(self):
            self.invocations = []

        def invoke(self, **kwargs):
            self.invocations.append(kwargs)
            return {
                "status_code": 200,
                "invocation_type": "RequestResponse",
                "handler_status": "COMPLETED",
                "handler_response": {"status": "COMPLETED", "run_id": "safe_run_123"},
            }

    lamb = SyncFakeLambda()
    result = ManualRunInvocationService(stage_config=stage_config, lambda_client=lamb).run(
        client_id="client1", audit_id="audit1", scenario_type="baseline_health"
    )

    assert result["status"] == "completed"
    assert result["payload"]["triggered_by"] == "manual"
    assert result["payload"]["schedule_type"] == "manual"
    assert result["payload"]["stage"] == stage_config.stage
    assert lamb.invocations[0]["invocation_type"] == "RequestResponse"


def test_manual_run_promotes_safe_handler_failure_details(stage_config):
    class SyncFailingLambda:
        def invoke(self, **kwargs):
            return {
                "status_code": 200,
                "invocation_type": "RequestResponse",
                "handler_status": "FAILED",
                "handler_succeeded": False,
                "handler_response": {
                    "status": "FAILED",
                    "run_id": "safe_run_123",
                    "failure_summary": {
                        "error_type": "CONFIG_LOAD_ERROR",
                        "message": "Config object could not be loaded; token=secret",
                    },
                    "headers": {"authorization": "Bearer abc123"},
                },
            }

    result = ManualRunInvocationService(
        stage_config=stage_config, lambda_client=SyncFailingLambda()
    ).run(client_id="client1", audit_id="audit1", scenario_type="repeated_stability")

    assert result["status"] == "failed"
    assert result["handler_status"] == "FAILED"
    assert result["run_id"] == "safe_run_123"
    assert result["scenario_type"] == "repeated_stability"
    assert result["error_code"] == "CONFIG_LOAD_ERROR"
    assert result["failure_type"] == "CONFIG_LOAD_ERROR"
    assert result["failure_message"] == "Config object could not be loaded; token=[REDACTED]"
    assert result["failure_details"]["run_id"] == "safe_run_123"
    assert "token=secret" not in json.dumps(result)
    assert "Bearer abc123" not in json.dumps(result)


def test_cli_run_result_distinguishes_handler_failure_from_invoke_acceptance(
    stage_config, monkeypatch
):
    class FailingHandlerLambda:
        def invoke(self, **kwargs):
            return {
                "status_code": 200,
                "invocation_type": "RequestResponse",
                "accepted_async_invocation": False,
                "handler_status": "failed",
                "handler_succeeded": False,
                "handler_response": {
                    "status": "failed",
                    "run_id": "safe_run_123",
                    "failure_summary": {
                        "error_type": "CONFIG_VALIDATION_ERROR",
                        "message": "Endpoint config must include at least one endpoint",
                    },
                },
            }

    class FakeFactory:
        def __init__(self, config):
            self.config = config

        def lambda_invocation(self):
            return FailingHandlerLambda()

    monkeypatch.setattr(services, "_stage", lambda args: stage_config)
    monkeypatch.setattr(services, "AwsClientFactory", FakeFactory)

    result = services.run_command(
        Namespace(
            stage="dev",
            client_id="client1",
            audit_id="audit1",
            scenario_type="baseline_health",
            run_id=None,
            schedule_type=None,
            dry_run=False,
        )
    )

    assert result.status == "failed"
    assert result.exit_code == 1
    assert result.summary == "orchestrator execution failed"
    assert result.data["invocation"]["accepted_async_invocation"] is False
    assert result.data["run_id"] == "safe_run_123"
    assert result.data["scenario_type"] == "baseline_health"
    assert result.data["error_code"] == "CONFIG_VALIDATION_ERROR"
    assert result.data["failure_message"] == "Endpoint config must include at least one endpoint"


def test_audit_run_failure_text_renders_actionable_handler_details():
    rendered = render(
        services.CommandResult(
            command="audit run",
            stage="dev",
            status="failed",
            summary="orchestrator execution failed",
            exit_code=1,
            data={
                "client_id": "client1",
                "audit_id": "audit1",
                "run_id": "safe_run_123",
                "scenario_type": "repeated_stability",
                "handler_status": "failed",
                "error_code": "CONFIG_LOAD_ERROR",
                "failure_type": "CONFIG_LOAD_ERROR",
                "failure_message": "Config object could not be loaded",
            },
        )
    )

    assert "FAILED: audit run" in rendered
    assert "run_id: safe_run_123" in rendered
    assert "scenario_type: repeated_stability" in rendered
    assert "error_code: CONFIG_LOAD_ERROR" in rendered
    assert "failure_type: CONFIG_LOAD_ERROR" in rendered
    assert "failure_message: Config object could not be loaded" in rendered
    assert "next_step: none" not in rendered
    assert "--output json" in rendered
    assert "CloudWatch" in rendered


def test_audit_run_failure_json_includes_structured_details_without_secret_leak():
    rendered = render(
        services.CommandResult(
            command="audit run",
            stage="dev",
            status="failed",
            summary="orchestrator execution failed",
            exit_code=1,
            data={
                "client_id": "client1",
                "audit_id": "audit1",
                "run_id": "safe_run_123",
                "scenario_type": "repeated_stability",
                "handler_status": "failed",
                "error_code": "ORCHESTRATION_ERROR",
                "failure_type": "ORCHESTRATION_ERROR",
                "failure_message": "Orchestration failed with Bearer abc123",
                "failure_details": {
                    "handler_status": "failed",
                    "run_id": "safe_run_123",
                    "scenario_type": "repeated_stability",
                    "error_code": "ORCHESTRATION_ERROR",
                    "failure_type": "ORCHESTRATION_ERROR",
                    "failure_message": "Orchestration failed with Bearer abc123",
                },
                "invocation": {
                    "handler_response": {
                        "failure_summary": {"message": "Orchestration failed with Bearer abc123"},
                        "headers": {"authorization": "Bearer abc123"},
                    }
                },
            },
        ),
        output="json",
    )
    payload = json.loads(rendered)

    assert payload["run_id"] == "safe_run_123"
    assert payload["scenario_type"] == "repeated_stability"
    assert payload["failure_details"]["error_code"] == "ORCHESTRATION_ERROR"
    assert payload["failure_details"]["failure_message"] == "Orchestration failed with [REDACTED]"
    assert payload["invocation"]["handler_response"]["headers"]["authorization"] == "[REDACTED]"
    assert "Bearer abc123" not in rendered


def test_audit_run_success_text_remains_without_failure_fields(stage_config):
    rendered = render(
        services.CommandResult(
            command="audit run",
            stage="dev",
            status="completed",
            summary="orchestrator execution completed",
            data={"client_id": "client1", "audit_id": "audit1", "run_id": "safe_run_123"},
        )
    )

    assert "SUCCESS: audit run" in rendered
    assert "run_id:" not in rendered
    assert "failure_message:" not in rendered
    assert "next_step: none" in rendered


def test_run_placeholder_orchestrator_fails_before_lambda_invoke(stage_config):
    placeholder_config = StageConfig(
        **{
            **stage_config.to_dict(),
            "orchestrator_function_name": "rcp-dev-orchestrator-placeholder",
        }
    )
    lamb = FakeLambda()

    with pytest.raises(EngineError) as exc:
        ManualRunInvocationService(stage_config=placeholder_config, lambda_client=lamb).run(
            client_id="client1", audit_id="audit1", scenario_type="baseline_health"
        )

    assert exc.value.error_type == "LAMBDA_CONFIG_ERROR"
    assert "orchestrator_function_name is a placeholder" in exc.value.message
    assert lamb.invocations == []


def test_cancel_partial_cleanup_exit_behavior_shape():
    repo = FakeRepo(
        {
            "client_id": "client1",
            "audit_id": "audit1",
            "lifecycle_state": "SCHEDULED",
            "schedules": [
                {"schedule_name": "s1", "schedule_group": "g", "schedule_type": "baseline"}
            ],
        }
    )
    result = AuditCancellationService(
        repository=repo, scheduler_client=FakeScheduler(fail_delete=True)
    ).cancel_for_operator(client_id="client1", audit_id="audit1", reason="operator requested")
    assert result["status"] == "cancelled_with_cleanup_warnings"
    assert repo.item["lifecycle_state"] == "CANCELLED"
    assert repo.cleanup_errors[0]["error_code"] == "SCHEDULE_CLEANUP_FAILED"
