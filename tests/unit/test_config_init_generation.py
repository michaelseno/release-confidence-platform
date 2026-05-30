from __future__ import annotations

import json
import re
from datetime import date

import pytest

from release_confidence_platform.audit_scheduling.safeguards import effective_caps
from release_confidence_platform.config.audit_validation_service import AuditConfigValidationService
from release_confidence_platform.config.generators import (
    generate_audit_config,
    generate_client_config,
    generate_endpoints_config,
)
from release_confidence_platform.core.exceptions import EngineError
from release_confidence_platform.core.id_generation import generate_audit_id, generate_client_id
from release_confidence_platform.core.slug_utils import slugify_client_name
from release_confidence_platform.operator_cli.config_init import ConfigInitService


def _contains_forbidden_secret_material(value) -> bool:
    text = json.dumps(value).lower()
    forbidden = ["auth_ref", "authorization", "api_key", "password", "token", "private_key"]
    return any(item in text for item in forbidden)


def test_generate_client_id_matches_safe_format():
    assert generate_client_id("Demo Client", shortid="a8f3c2d1") == "client_demo_client_a8f3c2d1"
    assert re.fullmatch(
        r"client_[a-z0-9]+(?:_[a-z0-9]+)*_[a-f0-9]{8,}", "client_demo_client_a8f3c2d1"
    )


def test_generate_audit_id_matches_date_format():
    assert (
        generate_audit_id(today=date(2026, 5, 23), shortid="ef56ab78") == "audit_20260523_ef56ab78"
    )


@pytest.mark.parametrize(
    "name",
    ["Acme Payments", "ACME/../Payments; rm -rf", "Client $(oops) & more", "quoted ' client"],
)
def test_slug_generation_removes_unsafe_path_and_shell_chars(name):
    slug = slugify_client_name(name)
    assert re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", slug)
    assert "/" not in slug and "\\" not in slug and ".." not in slug


@pytest.mark.parametrize("name", ["!!!", "   ", "../"])
def test_empty_slug_client_name_fails_before_write(tmp_path, name):
    with pytest.raises(EngineError) as exc:
        ConfigInitService(client_shortid="a8f3c2d1", audit_shortid="ef56ab78").init(
            client_name=name, target_environment="dev", output_dir=tmp_path
        )
    assert exc.value.error_type == "INVALID_ARGUMENT"
    assert list(tmp_path.iterdir()) == []


def test_generators_emit_safe_defaults_and_no_secret_material():
    client = generate_client_config(
        client_id="client_demo_a8f3c2d1", client_name="Demo", target_environment="production"
    )
    audit = generate_audit_config(
        client_id="client_demo_a8f3c2d1",
        audit_id="audit_20260523_ef56ab78",
        target_environment="production",
    )
    endpoints = generate_endpoints_config(
        client_id="client_demo_a8f3c2d1",
        audit_id="audit_20260523_ef56ab78",
        target_environment="production",
        include_sample=True,
    )

    assert client["execution_environment"]["allow_production_execution"] is False
    assert client["execution_environment"]["allow_destructive_operation"] is False
    assert client["request_defaults"]["timeout_seconds"] == 10
    assert client["request_defaults"]["max_concurrency"] == 5
    assert audit["audit_window"]["duration_hours"] == 48
    assert audit["baseline_schedule"]["interval_minutes"] == 15
    assert audit["burst_schedule"] == {
        "enabled": False,
        "windows": [],
        "manual_burst_defaults": {"enabled": True, "request_count": 10, "concurrency": 2},
    }
    assert audit["repeated_schedule"]["runs_per_day"] == 1
    assert endpoints["endpoints"][0]["url"] == "https://example.com/health"
    assert endpoints["endpoints"][0]["auth_required"] is False
    assert endpoints["endpoints"][0]["payload_safety"]["destructive_operation"] is False
    assert not _contains_forbidden_secret_material([client, audit, endpoints])


def test_default_empty_endpoint_template_validates_in_template_mode():
    client = generate_client_config(
        client_id="client_demo_a8f3c2d1", client_name="Demo", target_environment="dev"
    )
    audit = generate_audit_config(
        client_id="client_demo_a8f3c2d1",
        audit_id="audit_20260523_ef56ab78",
        target_environment="dev",
    )
    endpoints = generate_endpoints_config(
        client_id="client_demo_a8f3c2d1",
        audit_id="audit_20260523_ef56ab78",
        target_environment="dev",
    )
    assert endpoints["endpoints"] == []
    result = AuditConfigValidationService().validate_configs(
        client_config=client,
        audit_config=audit,
        endpoints_config=endpoints,
        stage="dev",
        template_mode=True,
    )
    assert result.endpoints == []
    with pytest.raises(EngineError):
        AuditConfigValidationService().validate_configs(
            client_config=client, audit_config=audit, endpoints_config=endpoints, stage="dev"
        )


@pytest.mark.parametrize("target_environment", ["prod", "production"])
def test_production_templates_are_safe_and_validate_in_template_mode(target_environment):
    client = generate_client_config(
        client_id="client_demo_a8f3c2d1", client_name="Demo", target_environment=target_environment
    )
    audit = generate_audit_config(
        client_id="client_demo_a8f3c2d1",
        audit_id="audit_20260523_ef56ab78",
        target_environment=target_environment,
    )
    endpoints = generate_endpoints_config(
        client_id="client_demo_a8f3c2d1",
        audit_id="audit_20260523_ef56ab78",
        target_environment=target_environment,
        include_sample=True,
    )
    AuditConfigValidationService().validate_configs(
        client_config=client,
        audit_config=audit,
        endpoints_config=endpoints,
        stage="dev",
        template_mode=True,
    )
    with pytest.raises(EngineError) as exc:
        AuditConfigValidationService().validate_configs(
            client_config=client, audit_config=audit, endpoints_config=endpoints, stage="dev"
        )
    assert exc.value.error_type == "PRODUCTION_BLOCKED"


def test_config_init_creates_tree_and_overwrite_protection(tmp_path):
    service = ConfigInitService(
        client_shortid="a8f3c2d1", audit_shortid="ef56ab78", today=date(2026, 5, 23)
    )
    result = service.init(
        client_name="Demo Client",
        target_environment="dev",
        output_dir=tmp_path / ".local-configs" / "demo",
    )
    root = tmp_path / ".local-configs" / "demo" / "client_demo_client_a8f3c2d1"
    assert result["output_dir"] == str(root)
    assert (root / "client_config.json").exists()
    assert (root / "audits" / "audit_20260523_ef56ab78" / "audit_config.json").exists()
    assert (root / "audits" / "audit_20260523_ef56ab78" / "endpoints.json").exists()
    sentinel = root / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(EngineError) as exc:
        service.init(
            client_name="Demo Client",
            target_environment="dev",
            output_dir=tmp_path / ".local-configs" / "demo",
        )
    assert exc.value.error_type == "LOCAL_FILE_EXISTS"
    assert sentinel.read_text(encoding="utf-8") == "keep"
    overwrite = service.init(
        client_name="Demo Client",
        target_environment="dev",
        output_dir=tmp_path / ".local-configs" / "demo",
        overwrite=True,
    )
    assert overwrite["overwritten"] is True
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_output_dir_existing_file_fails_before_write(tmp_path):
    file_path = tmp_path / "not-dir"
    file_path.write_text("original", encoding="utf-8")
    with pytest.raises(EngineError) as exc:
        ConfigInitService(client_shortid="a8f3c2d1", audit_shortid="ef56ab78").init(
            client_name="Demo Client", target_environment="dev", output_dir=file_path
        )
    assert exc.value.error_type == "INVALID_ARGUMENT"
    assert file_path.read_text(encoding="utf-8") == "original"


def test_prod_alias_uses_production_execution_caps_when_explicitly_allowed():
    caps = effective_caps({"target_environment": "prod", "allow_production_execution": True})
    assert caps["max_concurrency"] == 2
    assert caps["max_requests_per_run"] == 25
