from __future__ import annotations

import json
import sys
import types

import pytest

from release_confidence_platform.operator_cli import config_init, services
from release_confidence_platform.operator_cli.main import build_parser, main

STAGE_ENV_VARS = (
    "RCP_CONFIG_BUCKET",
    "RCP_AUDIT_METADATA_TABLE",
    "RCP_AWS_PROFILE",
    "RCP_AWS_REGION",
    "RCP_SCHEDULER_GROUP_NAME",
    "RCP_SCHEDULER_EXECUTION_TARGET_ARN",
    "RCP_SCHEDULER_FINALIZATION_TARGET_ARN",
    "RCP_SCHEDULER_ROLE_ARN",
    "RCP_SCHEDULE_NAME_PREFIX",
    "RCP_ORCHESTRATOR_FUNCTION_NAME",
)


def test_config_init_parser_accepts_required_and_optional_args(tmp_path):
    parser = build_parser()
    args = parser.parse_args(
        [
            "config",
            "init",
            "--client-name",
            "Demo Client",
            "--defaults",
            "prod",
            "--output-dir",
            str(tmp_path),
            "--timezone",
            "America/New_York",
            "--include-sample-endpoints",
            "--overwrite",
            "--output",
            "json",
        ]
    )
    assert args.config_command == "init"
    assert args.defaults == "prod"
    assert args.output == "json"
    assert args.stage if hasattr(args, "stage") else True


def test_config_init_parser_rejects_missing_required_args(tmp_path):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["config", "init", "--defaults", "dev", "--output-dir", str(tmp_path)])
    assert exc.value.code == 2


def test_config_stage_info_text_shows_placeholders_without_exported_overrides(monkeypatch, capsys):
    for name in STAGE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    assert main(["config", "stage-info", "--stage", "dev"]) == 0

    out = capsys.readouterr().out
    assert "SUCCESS: config stage-info" in out
    assert "stage: dev" in out
    assert "region: us-east-1" in out
    assert "aws_profile: rcp-dev" in out
    assert "config_bucket: rcp-dev-config-placeholder" in out
    assert "audit_metadata_table: rcp-dev-audit-metadata-placeholder" in out
    assert "orchestrator_function_name: rcp-dev-orchestrator-placeholder" in out
    assert "scheduler_group: rcp-dev-schedules-placeholder" in out
    assert "scheduler_group_name: rcp-dev-schedules-placeholder" in out
    assert "schedule_name_prefix: rcp-dev" in out
    assert (
        "scheduler_execution_target_arn: arn:aws:lambda:us-east-1:000000000000:"
        "function:release-confidence-platform-dev-scheduledExecution"
    ) in out
    assert (
        "scheduler_finalization_target_arn: arn:aws:lambda:us-east-1:000000000000:"
        "function:release-confidence-platform-dev-auditFinalization"
    ) in out
    assert (
        "scheduler_role_arn: arn:aws:iam::000000000000:role/"
        "release-confidence-platform-dev-scheduler-invoke"
    ) in out
    assert "live_aws_check: false" in out
    assert "export RCP_CONFIG_BUCKET=..." in out
    assert "export RCP_AUDIT_METADATA_TABLE=..." in out
    assert "export RCP_AWS_PROFILE=..." in out
    assert "export RCP_AWS_REGION=..." in out
    assert "export RCP_ORCHESTRATOR_FUNCTION_NAME=<deployed-function-name>" in out
    assert "export RCP_SCHEDULER_GROUP_NAME=<deployed-scheduler-group>" in out
    assert "export RCP_SCHEDULER_EXECUTION_TARGET_ARN=<scheduled-execution-lambda-arn>" in out
    assert "export RCP_SCHEDULER_FINALIZATION_TARGET_ARN=<audit-finalization-lambda-arn>" in out
    assert "export RCP_SCHEDULER_ROLE_ARN=<scheduler-invocation-role-arn>" in out
    assert "export RCP_SCHEDULE_NAME_PREFIX=<schedule-name-prefix>" in out
    assert "not exported do not affect child rcp processes" in out


def test_config_stage_info_text_shows_exported_env_overrides(monkeypatch, capsys):
    monkeypatch.setenv("RCP_CONFIG_BUCKET", "release-confidence-platform-dev-raw-results")
    monkeypatch.setenv("RCP_AUDIT_METADATA_TABLE", "release-confidence-platform-dev-metadata")
    monkeypatch.setenv("RCP_AWS_PROFILE", "rk-reliability")
    monkeypatch.setenv("RCP_AWS_REGION", "us-east-1")
    monkeypatch.setenv("RCP_SCHEDULER_GROUP_NAME", "release-confidence-platform-dev-schedules")
    monkeypatch.setenv("RCP_SCHEDULE_NAME_PREFIX", "rcp-dev")
    monkeypatch.setenv(
        "RCP_SCHEDULER_EXECUTION_TARGET_ARN",
        "arn:aws:lambda:us-east-1:123456789012:function:scheduledExecution",
    )
    monkeypatch.setenv(
        "RCP_SCHEDULER_FINALIZATION_TARGET_ARN",
        "arn:aws:lambda:us-east-1:123456789012:function:auditFinalization",
    )
    monkeypatch.setenv(
        "RCP_SCHEDULER_ROLE_ARN",
        "arn:aws:iam::123456789012:role/scheduler-invocation",
    )
    monkeypatch.setenv(
        "RCP_ORCHESTRATOR_FUNCTION_NAME",
        "release-confidence-platform-dev-coreEngineOrchestrator",
    )

    assert main(["config", "stage-info", "--stage", "dev"]) == 0

    out = capsys.readouterr().out
    assert "config_bucket: release-confidence-platform-dev-raw-results" in out
    assert "audit_metadata_table: release-confidence-platform-dev-metadata" in out
    assert "aws_profile: rk-reliability" in out
    assert "region: us-east-1" in out
    assert (
        "orchestrator_function_name: release-confidence-platform-dev-coreEngineOrchestrator" in out
    )
    assert "scheduler_group: release-confidence-platform-dev-schedules" in out
    assert "scheduler_group_name: release-confidence-platform-dev-schedules" in out
    assert (
        "scheduler_execution_target_arn: "
        "arn:aws:lambda:us-east-1:123456789012:function:scheduledExecution"
    ) in out
    assert (
        "scheduler_finalization_target_arn: "
        "arn:aws:lambda:us-east-1:123456789012:function:auditFinalization"
    ) in out
    assert "scheduler_role_arn: arn:aws:iam::123456789012:role/scheduler-invocation" in out


def test_config_stage_info_json_output_is_valid_and_contains_expected_fields(monkeypatch, capsys):
    monkeypatch.setenv("RCP_CONFIG_BUCKET", "bucket-from-env")
    monkeypatch.setenv("RCP_AUDIT_METADATA_TABLE", "table-from-env")
    monkeypatch.setenv("RCP_AWS_PROFILE", "profile-from-env")
    monkeypatch.setenv("RCP_AWS_REGION", "us-west-2")
    monkeypatch.setenv("RCP_ORCHESTRATOR_FUNCTION_NAME", "fn-from-env")
    monkeypatch.setenv("RCP_SCHEDULER_GROUP_NAME", "scheduler-group-from-env")
    monkeypatch.setenv("RCP_SCHEDULE_NAME_PREFIX", "prefix-from-env")
    monkeypatch.setenv(
        "RCP_SCHEDULER_EXECUTION_TARGET_ARN",
        "arn:aws:lambda:us-west-2:123456789012:function:execution",
    )
    monkeypatch.setenv(
        "RCP_SCHEDULER_FINALIZATION_TARGET_ARN",
        "arn:aws:lambda:us-west-2:123456789012:function:finalization",
    )
    monkeypatch.setenv(
        "RCP_SCHEDULER_ROLE_ARN",
        "arn:aws:iam::123456789012:role/scheduler",
    )

    assert main(["config", "stage-info", "--stage", "dev", "--output", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "config stage-info"
    assert payload["status"] == "success"
    assert payload["stage"] == "dev"
    assert payload["region"] == "us-west-2"
    assert payload["aws_profile"] == "profile-from-env"
    assert payload["config_bucket"] == "bucket-from-env"
    assert payload["audit_metadata_table"] == "table-from-env"
    assert payload["orchestrator_function_name"] == "fn-from-env"
    assert payload["scheduler_group"] == "scheduler-group-from-env"
    assert payload["scheduler_group_name"] == "scheduler-group-from-env"
    assert payload["schedule_name_prefix"] == "prefix-from-env"
    assert payload["scheduler_execution_target_arn"].endswith(":function:execution")
    assert payload["scheduler_finalization_target_arn"].endswith(":function:finalization")
    assert payload["scheduler_role_arn"].endswith(":role/scheduler")
    assert payload["live_aws_check"] is False
    guidance = "\n".join(payload["source_guidance"])
    assert "export RCP_CONFIG_BUCKET=..." in guidance
    assert "export RCP_AUDIT_METADATA_TABLE=..." in guidance
    assert "export RCP_AWS_PROFILE=..." in guidance
    assert "export RCP_AWS_REGION=..." in guidance
    assert "export RCP_ORCHESTRATOR_FUNCTION_NAME=<deployed-function-name>" in guidance
    assert "export RCP_SCHEDULER_GROUP_NAME=<deployed-scheduler-group>" in guidance
    assert "export RCP_SCHEDULER_EXECUTION_TARGET_ARN=<scheduled-execution-lambda-arn>" in guidance
    assert (
        "export RCP_SCHEDULER_FINALIZATION_TARGET_ARN=<audit-finalization-lambda-arn>" in guidance
    )
    assert "export RCP_SCHEDULER_ROLE_ARN=<scheduler-invocation-role-arn>" in guidance


def test_config_stage_info_is_local_only_and_does_not_call_aws(monkeypatch, capsys):
    fake_boto3 = types.SimpleNamespace(
        client=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("boto3 client called")),
        resource=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("boto3 resource called")
        ),
    )
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setattr(
        services.AwsClientFactory,
        "__init__",
        lambda self, stage_config: (_ for _ in ()).throw(AssertionError("aws constructed")),
    )

    assert main(["config", "stage-info", "--stage", "dev"]) == 0

    out = capsys.readouterr().out
    assert "live_aws_check: false" in out
    assert "no AWS calls performed" in out


@pytest.mark.parametrize("defaults", ["dev", "staging", "prod", "config/defaults/dev.json"])
def test_config_init_parser_defaults_values(tmp_path, defaults):
    args = build_parser().parse_args(
        [
            "config",
            "init",
            "--client-name",
            "Demo",
            "--defaults",
            defaults,
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert args.defaults == defaults


def test_config_init_text_output_includes_required_information(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        config_init, "generate_client_id", lambda client_name, shortid=None: "client_demo_a8f3c2d1"
    )
    monkeypatch.setattr(
        config_init, "generate_audit_id", lambda today=None, shortid=None: "audit_20260523_ef56ab78"
    )
    assert (
        main(
            [
                "config",
                "init",
                "--client-name",
                "Demo",
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "client_demo_a8f3c2d1" in out
    assert "audit_20260523_ef56ab78" in out
    assert "client_config.json" in out and "audit_config.json" in out and "endpoints.json" in out
    assert ".local-configs/" in out and ".gitignore" in out
    assert "Resolution order" in out
    assert "Safety" in out
    assert "Next steps" in out
    assert "Use rcp audit create --dry-run for local create planning without AWS mutation." in out
    assert "config/stages/<stage>.json aws_profile or RCP_AWS_PROFILE" in out


def test_config_init_prod_text_output_includes_production_warning_block(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        config_init, "generate_client_id", lambda client_name, shortid=None: "client_demo_a8f3c2d1"
    )
    monkeypatch.setattr(
        config_init, "generate_audit_id", lambda today=None, shortid=None: "audit_20260523_ef56ab78"
    )
    assert (
        main(
            [
                "config",
                "init",
                "--client-name",
                "Demo",
                "--defaults",
                "prod",
                "--output-dir",
                str(tmp_path),
                "--include-sample-endpoints",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "WARNING: Production target defaults selected." in out
    assert "allow_production_execution=false" in out
    assert "allow_destructive_operation=false" in out
    production_approval_message = (
        "Separate approval and validation are required before any production execution workflow."
    )
    assert production_approval_message in out


def test_config_init_json_output_is_parseable_and_complete(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        config_init, "generate_client_id", lambda client_name, shortid=None: "client_demo_a8f3c2d1"
    )
    monkeypatch.setattr(
        config_init, "generate_audit_id", lambda today=None, shortid=None: "audit_20260523_ef56ab78"
    )
    assert (
        main(
            [
                "config",
                "init",
                "--client-name",
                "Demo",
                "--defaults",
                "prod",
                "--output-dir",
                str(tmp_path),
                "--include-sample-endpoints",
                "--output",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert sorted(payload) == [
        "audit_id",
        "client_id",
        "command",
        "effective_settings",
        "generated_files",
        "next_steps",
        "profile",
        "resolution_order",
        "safety",
        "status",
        "warnings",
    ]
    assert payload["command"] == "config init"
    assert payload["client_id"] == "client_demo_a8f3c2d1"
    assert payload["audit_id"] == "audit_20260523_ef56ab78"
    assert payload["profile"]["name"] == "prod"
    assert payload["profile"]["target_environment"] == "prod"
    assert payload["effective_settings"]["workspace_root"] == str(tmp_path / "client_demo_a8f3c2d1")
    assert payload["effective_settings"]["include_sample_endpoints"] is True
    assert payload["effective_settings"]["sample_endpoint_safety"] == "mock_only"
    assert payload["resolution_order"] == [
        "explicit_cli_argument",
        "profile_operator_defaults",
        "safe_fallback",
    ]
    assert sorted(payload["generated_files"]) == ["audit_config", "client_config", "endpoints"]
    assert payload["safety"] == {
        "local_only": True,
        "aws_calls_made": False,
        "configs_uploaded": False,
        "schedules_created": False,
        "allow_production_execution": False,
        "allow_destructive_operation": False,
    }
    assert payload["warnings"] == [
        {
            "code": "PRODUCTION_TARGET_SAFE_LOCAL_ONLY",
            "message": (
                "Production target defaults selected; generated configs remain local "
                "and non-executable by default."
            ),
        }
    ]
    assert payload["next_steps"] == [
        "Review generated JSON files.",
        "Add real endpoints only after review; do not store secrets in generated config files.",
        "Run rcp audit validate after endpoints.json contains at least one real endpoint.",
        "Use rcp audit create --dry-run for local create planning without AWS mutation.",
        (
            "Run non-dry-run rcp audit create or rcp audit run only after endpoints are edited, "
            "local validation passes, deployed stage resources exist, and "
            "config/stages/<stage>.json "
            "aws_profile or RCP_AWS_PROFILE points to loadable AWS credentials."
        ),
    ]


def test_config_init_json_error_output_is_parseable(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        config_init, "generate_client_id", lambda client_name, shortid=None: "client_demo_a8f3c2d1"
    )
    monkeypatch.setattr(
        config_init, "generate_audit_id", lambda today=None, shortid=None: "audit_20260523_ef56ab78"
    )
    root = tmp_path / "client_demo_a8f3c2d1"
    root.mkdir()
    assert (
        main(
            [
                "config",
                "init",
                "--client-name",
                "Demo",
                "--output-dir",
                str(tmp_path),
                "--output",
                "json",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["code"] == "LOCAL_FILE_EXISTS"
