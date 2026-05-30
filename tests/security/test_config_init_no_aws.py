from __future__ import annotations

import inspect
import sys
import types

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
        client_name="Demo Client", output_dir=tmp_path
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
            client_name="!!!", output_dir=tmp_path
        )


def test_config_init_does_not_call_boto3_on_success_or_local_failures(tmp_path, monkeypatch):
    fake_boto3 = types.SimpleNamespace(
        client=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("boto3 client called")),
        resource=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("boto3 resource called")
        ),
    )
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    service = ConfigInitService(client_shortid="a8f3c2d1", audit_shortid="ef56ab78")
    service.init(client_name="Demo Client", output_dir=tmp_path)
    with pytest.raises(EngineError) as exc:
        service.init(client_name="Demo Client", output_dir=tmp_path)
    assert exc.value.error_type == "LOCAL_FILE_EXISTS"
    with pytest.raises(EngineError) as exc:
        service.init(
            client_name="Demo Client", defaults=str(tmp_path / "missing.json"), output_dir=tmp_path
        )
    assert exc.value.error_type == "CONFIG_LOAD_ERROR"


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
