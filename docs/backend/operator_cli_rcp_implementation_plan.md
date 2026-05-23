# Implementation Plan

## 1. Feature Overview
Implement and stabilize the internal `rcp` operator CLI for audit validation, creation, scheduling, manual invocation, and cancellation. This remediation converts the installable application code to a conventional `src/release_confidence_platform` package so `rcp` works after editable install without `PYTHONPATH`, top-level `packages` imports, or runtime `sys.path` mutation.

## 2. Technical Scope
Add a thin CLI package and script entry point, shared stage configuration loading, shared audit config validation, creation, persisted scheduling, manual run, cancellation orchestration, and mockable AWS wrapper extensions.

Repeated HITL defect fix scope:
- Use `src` layout for the installable package: `src/release_confidence_platform/...`.
- Move/copy the Operator CLI runtime dependency graph into the project namespace and replace `packages.*` imports with `release_confidence_platform.*` imports.
- Configure setuptools to discover only `release_confidence_platform*` packages from `src`.
- Keep the local `scripts/rcp.py` shim as a simple import of the packaged entry point with no path mutation.

## 3. Source Inputs
- `docs/architecture/operator_cli_rcp_technical_design.md`
- `docs/product/operator_cli_rcp_spec.md`
- `docs/uiux/operator_cli_rcp_design_spec.md`
- `docs/qa/operator_cli_rcp_test_plan.md`
- `docs/qa/operator_cli_rcp_test_report.md`
- `docs/bugs/operator_cli_rcp_qa_failures_bug_report.md`
- `docs/bugs/operator_cli_installed_rcp_import_bug_report.md`
- `docs/release/operator_cli_rcp_issue.md`
- `tests/api/test_operator_cli_rcp_contract.py`
- Existing Phase 1/2/3 validators, lifecycle, scheduling, storage, and sanitization modules.

## 4. API Contracts Affected
No public HTTP API contract changes. Internal CLI commands affected:
- `rcp audit validate --client-config --audit-config --endpoints-config --stage [--output]`
- `rcp audit create --client-config --audit-config --endpoints-config --stage [--dry-run] [--force] [--output]`
- `rcp audit schedule --client-id --audit-id --stage [--dry-run] [--allow-production] [--output]`
- `rcp audit run --client-id --audit-id --scenario-type --stage [--run-id] [--schedule-type] [--dry-run] [--output]`
- `rcp audit cancel --client-id --audit-id --stage [--reason] [--dry-run] [--output]`

Packaging contract correction:
- Installed console script `rcp = "release_confidence_platform.operator_cli.main:main"` must import a conventional package namespace from editable and non-editable installs.
- `rcp --help` and `rcp audit --help` must render argparse help without relying on `PYTHONPATH` or `scripts/rcp.py` path bootstrapping.
- Installed CLI runtime imports must resolve under `release_confidence_platform.*`, not top-level `packages.*`.

## 5. Data Models / Storage Affected
- S3 config objects at deterministic keys under `configs/{client_id}/...`.
- DynamoDB audit metadata item `PK=CLIENT#{client_id}`, `SK=AUDIT#{audit_id}` with lifecycle, config hashes, config keys, schedules, cleanup errors, and history.
- EventBridge Scheduler schedule metadata retained in DynamoDB.
- No new data model or storage changes for the installed console-script import fix.

## 6. Files Expected to Change
- `scripts/rcp.py`
- `packages/operator_cli/*`
- `packages/config/stage_config.py`, `packages/config/audit_validation_service.py`
- `packages/core/audit_creation_service.py`, `packages/core/manual_run_service.py`
- `packages/audit_scheduling/service.py`, `packages/audit_scheduling/builders.py`
- `packages/audit_lifecycle/cancellation.py`
- `packages/storage/*`
- `config/stages/*.json`
- `tests/unit/test_operator_cli_rcp.py`
- `docs/operator-cli/README.md`, `packages/operator_cli/README.md`

QA defect fix files:
- `packages/config/stage_config.py`
- `packages/audit_scheduling/service.py`
- `tests/unit/test_operator_cli_rcp.py`
- `docs/backend/operator_cli_rcp_implementation_plan.md`
- `docs/backend/operator_cli_rcp_implementation_report.md`

HITL installed CLI fix files:
- `pyproject.toml`
- `src/release_confidence_platform/**`
- `scripts/rcp.py`
- `tests/unit/test_operator_cli_rcp.py`
- `tests/api/test_operator_cli_rcp_contract.py`
- `docs/backend/operator_cli_rcp_implementation_plan.md`
- `docs/backend/operator_cli_rcp_implementation_report.md`

## 7. Security / Authorization Considerations
CLI is trusted-internal and has no RBAC. Implementation must validate identifiers, never store or print literal secrets, sanitize provider failures, enforce production/destructive operation flags, and avoid hardcoded AWS resource names in command handlers.

The installed CLI fix changes package discovery/importability and import namespaces only. It does not alter authentication, authorization, AWS permissions, CLI command semantics, or sensitive output handling.

## 8. Dependencies / Constraints
No new runtime dependencies planned. AWS calls stay behind existing boto3-compatible wrappers and are mocked in tests.

Packaging constraint: the repository still contains historical top-level `packages` modules for existing source-tree tests, but the installable application package must not discover or depend on that namespace. Setuptools must use `package-dir = {"" = "src"}` and discover only `release_confidence_platform*` from `src`.

## 9. Assumptions
- Existing config shapes are permissive; validation accepts both Phase 3 existing names and product-spec schedule block aliases where safe.
- Stage config files use non-secret placeholder resource names suitable for tests and local dry-run usage.
- Existing legacy `ScheduleBuilder.build_all` default behavior is left unchanged; Operator CLI persisted-config semantics are enforced in the service normalization adapter by explicitly setting missing `finalization_schedule` to disabled.
- The CLI behavior remains unchanged while the installable runtime code now lives under `src/release_confidence_platform`.
- Historical `packages.*` modules are left in the repository for existing tests/backward compatibility, but they are not included in the installable distribution.

## 10. Validation Plan
- `python -m pytest tests/unit/test_operator_cli_rcp.py`
- Targeted existing Phase 3 tests where relevant if time permits.
- `/var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode/rcp-venv311/bin/python -m pytest tests/api/test_operator_cli_rcp_contract.py`
- `/var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode/rcp-venv311/bin/python -m pytest tests/unit/test_operator_cli_rcp.py`
- `/var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode/rcp-venv311/bin/python -m pytest tests/unit`
- `python3.11 -m venv /var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode/rcp-install-smoke`
- `/var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode/rcp-install-smoke/bin/python -m pip install --upgrade pip`
- `/var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode/rcp-install-smoke/bin/python -m pip install -e .`
- `/var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode/rcp-install-smoke/bin/python -c "import packages.operator_cli.main as m; print(m.build_parser().prog)"`
- `/var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode/rcp-install-smoke/bin/rcp --help`
- `/var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode/rcp-install-smoke/bin/rcp audit --help`
- Active repo `.venv` uninstall/reinstall and installed `rcp --help` / `rcp audit --help` validation.
- Active repo `.venv` script shim validation: `.venv/bin/python scripts/rcp.py --help` and `.venv/bin/python scripts/rcp.py audit --help`.
- Outside-repo cwd validation using the active repo `.venv` installed `rcp`.
- Clean Python 3.11 editable-install `rcp --help` / `rcp audit --help` validation.
- Clean Python 3.11 non-editable-install `rcp --help` / `rcp audit --help` validation.
- Targeted/unit pytest and ruff if available.
