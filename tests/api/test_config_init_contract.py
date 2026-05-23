from __future__ import annotations

import json
from datetime import date

import pytest

from release_confidence_platform.config.audit_validation_service import AuditConfigValidationService
from release_confidence_platform.operator_cli.config_init import ConfigInitService


@pytest.mark.parametrize("target_environment", ["dev", "staging", "prod", "production"])
def test_generated_config_set_contract_validates_without_aws(tmp_path, target_environment):
    result = ConfigInitService(
        client_shortid="a8f3c2d1", audit_shortid="ef56ab78", today=date(2026, 5, 23)
    ).init(
        client_name="Demo Client",
        target_environment=target_environment,
        output_dir=tmp_path,
        include_sample_endpoints=target_environment in {"prod", "production"},
    )
    root = tmp_path / "client_demo_client_a8f3c2d1"
    client = json.loads((root / "client_config.json").read_text(encoding="utf-8"))
    audit = json.loads(
        (root / "audits" / result["audit_id"] / "audit_config.json").read_text(encoding="utf-8")
    )
    endpoints = json.loads(
        (root / "audits" / result["audit_id"] / "endpoints.json").read_text(encoding="utf-8")
    )
    validated = AuditConfigValidationService().validate_configs(
        client_config=client,
        audit_config=audit,
        endpoints_config=endpoints,
        stage="dev",
        template_mode=True,
    )
    assert validated.client_id == result["client_id"]
    assert validated.audit_id == result["audit_id"]
    assert result["output_dir"] == str(root)
    assert all(str(root) in item["path"] for item in result["generated_files"])


def test_gitignore_is_not_modified(tmp_path):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("existing\n", encoding="utf-8")
    result = ConfigInitService(client_shortid="a8f3c2d1", audit_shortid="ef56ab78").init(
        client_name="Demo Client", target_environment="dev", output_dir=tmp_path / ".local-configs"
    )
    assert gitignore.read_text(encoding="utf-8") == "existing\n"
    assert ".local-configs/" in result["warning"] and ".gitignore" in result["warning"]
