from __future__ import annotations

import json
from datetime import date

import pytest

from release_confidence_platform.config.audit_validation_service import AuditConfigValidationService
from release_confidence_platform.core.exceptions import EngineError
from release_confidence_platform.operator_cli.config_init import ConfigInitService
from release_confidence_platform.operator_cli.default_profiles import (
    load_default_profile,
    resolve_default_profile_path,
)


def _profile(tmp_path, **overrides):
    base = json.loads(load_default_profile("dev").source_path.read_text(encoding="utf-8"))
    base.update(overrides)
    path = tmp_path / "custom_profile.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return path


@pytest.mark.parametrize("defaults", [None, "dev", "staging", "prod"])
def test_named_and_omitted_profiles_resolve(defaults):
    profile = load_default_profile(defaults)
    expected = defaults or "dev"
    assert profile.name == expected
    assert profile.source_path.name == f"{expected}.json"


@pytest.mark.parametrize("value", ["./custom.json", "config/defaults/dev.json", "custom.json"])
def test_path_like_profiles_are_explicit_paths(value):
    assert resolve_default_profile_path(value) == __import__("pathlib").Path(value)


def test_unsupported_named_profile_fails():
    with pytest.raises(EngineError) as exc:
        load_default_profile("qa")
    assert exc.value.error_type == "INVALID_ARGUMENT"


def test_missing_invalid_non_object_and_incomplete_profiles_fail_before_writes(tmp_path):
    service = ConfigInitService(client_shortid="a8f3c2d1", audit_shortid="ef56ab78")
    missing = tmp_path / "missing.json"
    with pytest.raises(EngineError) as exc:
        service.init(client_name="Demo", defaults=str(missing), output_dir=tmp_path / "out")
    assert exc.value.error_type == "CONFIG_LOAD_ERROR"
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{", encoding="utf-8")
    with pytest.raises(EngineError):
        service.init(client_name="Demo", defaults=str(bad_json), output_dir=tmp_path / "out")
    non_object = tmp_path / "non_object.json"
    non_object.write_text("[]", encoding="utf-8")
    with pytest.raises(EngineError) as exc:
        service.init(client_name="Demo", defaults=str(non_object), output_dir=tmp_path / "out")
    assert exc.value.error_type == "CONFIG_VALIDATION_ERROR"
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps({"profile_name": "x"}), encoding="utf-8")
    with pytest.raises(EngineError):
        service.init(client_name="Demo", defaults=str(incomplete), output_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_profile_defaults_apply_and_cli_overrides_take_precedence(tmp_path):
    profile_path = _profile(
        tmp_path,
        profile_name="custom",
        target_environment="staging",
        operator_defaults={
            "output_dir": str(tmp_path / "profile-out"),
            "timezone": "UTC",
            "output": "json",
        },
    )
    service = ConfigInitService(
        client_shortid="a8f3c2d1", audit_shortid="ef56ab78", today=date(2026, 5, 24)
    )
    result = service.init(client_name="Enterprise Client", defaults=str(profile_path))
    assert result["output_format"] == "json"
    assert result["output_dir"].startswith(str(tmp_path / "profile-out"))
    audit_path = (
        tmp_path
        / "profile-out"
        / result["client_id"]
        / "audits"
        / result["audit_id"]
        / "audit_config.json"
    )
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["timezone"] == "UTC"

    override = service.init(
        client_name="Enterprise Client",
        defaults=str(profile_path),
        output_dir=tmp_path / "cli-out",
        timezone="Asia/Hong_Kong",
        output="text",
    )
    assert override["output_format"] == "text"
    assert override["output_dir"].startswith(str(tmp_path / "cli-out"))
    override_audit_path = (
        tmp_path
        / "cli-out"
        / override["client_id"]
        / "audits"
        / override["audit_id"]
        / "audit_config.json"
    )
    audit = json.loads(override_audit_path.read_text(encoding="utf-8"))
    assert audit["timezone"] == "Asia/Hong_Kong"


def test_minimal_dev_generation_structure_validation_and_empty_endpoints(tmp_path):
    result = ConfigInitService(
        client_shortid="a8f3c2d1", audit_shortid="ef56ab78", today=date(2026, 5, 24)
    ).init(client_name="Acme", output_dir=tmp_path / ".local-configs")
    root = tmp_path / ".local-configs" / "client_acme_a8f3c2d1"
    assert result["defaults_profile"] == "dev"
    assert (root / "client_config.json").exists()
    assert not (tmp_path / ".local-configs" / "client_config.json").exists()
    client = json.loads((root / "client_config.json").read_text(encoding="utf-8"))
    audit_root = root / "audits" / result["audit_id"]
    audit = json.loads((audit_root / "audit_config.json").read_text(encoding="utf-8"))
    endpoints = json.loads((audit_root / "endpoints.json").read_text(encoding="utf-8"))
    assert endpoints["endpoints"] == []
    assert audit["burst_schedule"]["manual_burst_defaults"] == {
        "enabled": True,
        "request_count": 10,
        "concurrency": 2,
    }
    AuditConfigValidationService().validate_configs(
        client_config=client,
        audit_config=audit,
        endpoints_config=endpoints,
        stage="dev",
        template_mode=True,
    )


def test_sample_endpoints_are_safe_and_prod_remains_non_executable(tmp_path):
    result = ConfigInitService(client_shortid="a8f3c2d1", audit_shortid="ef56ab78").init(
        client_name="Acme", defaults="prod", output_dir=tmp_path, include_sample_endpoints=True
    )
    root = tmp_path / result["client_id"]
    client = json.loads((root / "client_config.json").read_text(encoding="utf-8"))
    audit_root = root / "audits" / result["audit_id"]
    audit = json.loads((audit_root / "audit_config.json").read_text(encoding="utf-8"))
    endpoints = json.loads((audit_root / "endpoints.json").read_text(encoding="utf-8"))
    assert client["execution_environment"]["allow_production_execution"] is False
    assert audit["execution_environment"]["allow_destructive_operation"] is False
    assert audit["operational_caps"]["max_concurrency"] == 2
    assert endpoints["endpoints"][0]["url"] == "https://example.com/health"
    assert endpoints["endpoints"][0]["auth_required"] is False


def test_unsafe_profile_fields_and_invalid_timezone_fail(tmp_path):
    secret_path = _profile(tmp_path, api_key="do-not-echo")
    with pytest.raises(EngineError) as exc:
        ConfigInitService().init(
            client_name="Demo", defaults=str(secret_path), output_dir=tmp_path / "out"
        )
    assert exc.value.error_type == "CONFIG_VALIDATION_ERROR"
    timezone_path = _profile(tmp_path, operator_defaults={"timezone": "Not/AZone"})
    with pytest.raises(EngineError):
        ConfigInitService().init(
            client_name="Demo", defaults=str(timezone_path), output_dir=tmp_path / "out"
        )
