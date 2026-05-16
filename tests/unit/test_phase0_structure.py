from pathlib import Path

REQUIRED_PATHS = (
    "apps/backend/orchestrator",
    "apps/backend/runner",
    "apps/backend/aggregator",
    "apps/backend/analytics",
    "apps/backend/reporting",
    "apps/backend/handlers",
    "apps/frontend/README.md",
    "packages/core/models",
    "packages/core/schemas",
    "packages/core/constants",
    "packages/core/exceptions",
    "packages/config/client_config",
    "packages/config/audit_config",
    "packages/config/endpoint_config",
    "packages/data-generation/generator.py",
    "packages/data-generation/duplicate_checker.py",
    "packages/data-generation/templates.py",
    "packages/data-generation/validators.py",
    "packages/sanitization/sanitizer.py",
    "packages/sanitization/rules.py",
    "packages/storage/s3_client.py",
    "packages/storage/dynamodb_client.py",
    "packages/storage/secrets_client.py",
    "packages/report-engine/templates",
    "packages/report-engine/renderer.py",
    "infra/serverless.yml",
    "infra/resources/dynamodb.yml",
    "infra/resources/s3.yml",
    "infra/resources/iam.yml",
    "infra/resources/scheduler.yml",
    "configs/samples/client_config.sample.json",
    "configs/samples/audit_config.sample.json",
    "configs/samples/endpoints.sample.json",
    "tests/unit",
    "tests/integration",
    "tests/mock_api",
    "docs/architecture/architecture_overview.md",
    "docs/architecture/execution_lifecycle.md",
    "docs/audit-methodology/raw_evidence_philosophy.md",
    "docs/operational-safety/operational_philosophy.md",
    "docs/architecture/coding_standards.md",
    "docs/architecture/structured_logging.md",
    "docs/architecture/naming_and_schema_versioning.md",
    "docs/architecture/folder_ownership.md",
    "scripts/run_local_audit.py",
    "scripts/validate_config.py",
    "README.md",
    "pyproject.toml",
)


def test_required_phase0_paths_exist() -> None:
    missing = [path for path in REQUIRED_PATHS if not Path(path).exists()]

    assert missing == []


def test_frontend_placeholder_only() -> None:
    frontend_entries = sorted(path.name for path in Path("apps/frontend").iterdir())

    assert frontend_entries == ["README.md"]
