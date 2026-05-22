# Implementation Plan

## 1. Feature Overview
Implement and stabilize the internal `rcp` operator CLI for audit validation, creation, scheduling, manual invocation, and cancellation. This update specifically fixes the HITL-blocking installed console-script import path so `rcp` works after editable install without `PYTHONPATH` or shell shims.

## 2. Technical Scope
Add a thin CLI package and script entry point, shared stage configuration loading, shared audit config validation, creation, persisted scheduling, manual run, cancellation orchestration, and mockable AWS wrapper extensions.

HITL defect fix scope:
- Make setuptools package discovery explicit for the repository-root package layout.
- Disable implicit namespace discovery so editable install metadata maps only regular, importable Python packages.
- Add package markers for storage and sanitization helper packages used by the CLI dependency graph.
- Preserve the existing console script target `packages.operator_cli.main:main` and the thin `scripts/rcp.py` shim.

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
- Installed console script `rcp = "packages.operator_cli.main:main"` must import `packages.operator_cli.main` from a clean editable install at the repository root.
- `rcp --help` and `rcp audit --help` must render argparse help without relying on `PYTHONPATH` or `scripts/rcp.py` path bootstrapping.

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
- `packages/storage/__init__.py`
- `packages/sanitization/__init__.py`
- `docs/backend/operator_cli_rcp_implementation_plan.md`
- `docs/backend/operator_cli_rcp_implementation_report.md`

## 7. Security / Authorization Considerations
CLI is trusted-internal and has no RBAC. Implementation must validate identifiers, never store or print literal secrets, sanitize provider failures, enforce production/destructive operation flags, and avoid hardcoded AWS resource names in command handlers.

The installed CLI fix changes only package discovery/importability. It does not alter authentication, authorization, AWS permissions, CLI command semantics, or sensitive output handling.

## 8. Dependencies / Constraints
No new runtime dependencies planned. AWS calls stay behind existing boto3-compatible wrappers and are mocked in tests.

Packaging constraint: the repository currently uses a top-level regular package named `packages`; setuptools discovery must expose that package and its regular subpackages to editable and non-editable installs.

## 9. Assumptions
- Existing config shapes are permissive; validation accepts both Phase 3 existing names and product-spec schedule block aliases where safe.
- Stage config files use non-secret placeholder resource names suitable for tests and local dry-run usage.
- Existing legacy `ScheduleBuilder.build_all` default behavior is left unchanged; Operator CLI persisted-config semantics are enforced in the service normalization adapter by explicitly setting missing `finalization_schedule` to disabled.
- The console script target remains `packages.operator_cli.main:main`; making package discovery explicit is the smallest safe packaging fix and avoids CLI runtime path mutation.

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
