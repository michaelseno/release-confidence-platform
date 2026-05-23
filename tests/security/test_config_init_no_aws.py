from __future__ import annotations

import inspect

import pytest

from release_confidence_platform.core.exceptions import EngineError
from release_confidence_platform.operator_cli import config_init, services
from release_confidence_platform.operator_cli.config_init import ConfigInitService


def test_config_init_success_does_not_touch_aws_or_stage_loader(tmp_path, monkeypatch):
    monkeypatch.setattr(
        services, "_stage", lambda args: (_ for _ in ()).throw(AssertionError("stage loaded"))
    )
    monkeypatch.setattr(
        services.AwsClientFactory,
        "__init__",
        lambda self, stage_config: (_ for _ in ()).throw(AssertionError("aws constructed")),
    )
    ConfigInitService(client_shortid="a8f3c2d1", audit_shortid="ef56ab78").init(
        client_name="Demo Client", target_environment="dev", output_dir=tmp_path
    )


def test_config_init_local_failure_does_not_touch_aws_or_stage_loader(tmp_path, monkeypatch):
    monkeypatch.setattr(
        services, "_stage", lambda args: (_ for _ in ()).throw(AssertionError("stage loaded"))
    )
    monkeypatch.setattr(
        services.AwsClientFactory,
        "__init__",
        lambda self, stage_config: (_ for _ in ()).throw(AssertionError("aws constructed")),
    )
    with pytest.raises(EngineError):
        ConfigInitService(client_shortid="a8f3c2d1", audit_shortid="ef56ab78").init(
            client_name="!!!", target_environment="dev", output_dir=tmp_path
        )


def test_config_init_import_boundary_excludes_aws_modules():
    source = inspect.getsource(config_init)
    forbidden = [
        "stage_config",
        "aws_client_factory",
        "s3_client",
        "secrets_client",
        "dynamodb_client",
        "eventbridge_scheduler_client",
        "lambda_client",
        "boto3",
    ]
    assert all(item not in source for item in forbidden)
