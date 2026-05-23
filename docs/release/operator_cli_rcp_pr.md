# Pull Request

## 1. Feature Name
Operator CLI `rcp`

## 2. Summary
Adds the internal `rcp` operator CLI for Release Confidence Platform audit operations. The CLI supports audit config validation, draft audit creation, persisted audit scheduling, manual smoke-run invocation, and audit cancellation through sanitized command output and shared backend services.

This release is limited to the core Operator CLI. Operational discovery CLI work is intentionally excluded and must be delivered in a separate PR.

## 3. Related Documents
- Product Spec: docs/product/operator_cli_rcp_spec.md
- Technical Design: docs/architecture/operator_cli_rcp_technical_design.md
- UI/UX Spec: docs/uiux/operator_cli_rcp_design_spec.md
- QA Test Plan: docs/qa/operator_cli_rcp_test_plan.md
- QA Report: docs/qa/operator_cli_rcp_test_report.md
- Implementation Plan: docs/backend/operator_cli_rcp_implementation_plan.md
- Implementation Report: docs/backend/operator_cli_rcp_implementation_report.md
- QA Bug Report: docs/bugs/operator_cli_rcp_qa_failures_bug_report.md
- HITL Bug Report: docs/bugs/operator_cli_installed_rcp_import_bug_report.md
- Release Issue: docs/release/operator_cli_rcp_issue.md

## 4. Changes Included
- Added `rcp audit` command group with `validate`, `create`, `schedule`, `run`, and `cancel` subcommands.
- Added packaged console script support through `release_confidence_platform.operator_cli.main:main` and a thin `scripts/rcp.py` shim.
- Added src-layout installable runtime package under `src/release_confidence_platform` for the Operator CLI dependency graph.
- Added shared service coverage for stage config loading, audit config validation, draft creation, persisted scheduling, manual invocation, cancellation, lifecycle handling, dry-run behavior, and sanitized output.
- Added non-secret placeholder stage config files and operator/package documentation.
- Added unit/API contract regression tests for CLI behavior and packaging/importability.
- Added planning, QA, bug, implementation, issue, and release artifacts for traceability.

## 5. QA Status
- Approved: YES
- QA gate: `[QA SIGN-OFF APPROVED]`
- HITL gate: `HITL validation successful`

## 6. Test Coverage
- Targeted Operator CLI unit/API contract run: `14 passed in 0.14s`.
- Relevant unit suite: `60 passed in 0.39s`.
- Installed CLI help checks passed for `.venv/bin/rcp --help` and `.venv/bin/rcp audit --help`.
- Script shim help checks passed for `.venv/bin/python scripts/rcp.py --help` and `.venv/bin/python scripts/rcp.py audit --help`.
- Clean editable and non-editable install smoke checks are documented in the implementation report.

## 7. Risks / Notes
- Stage configs contain non-secret placeholder AWS resource names and must be replaced or overridden before real environment operations.
- Unit coverage uses mocked/faked AWS dependencies only; no real AWS integration validation was performed by design.
- Historical `packages.*` modules remain in-tree for source-tree compatibility, while the installable CLI runs from `src/release_confidence_platform`.
- Local macOS `.venv` hidden file flags caused a HITL environment blocker; this was remediated locally and documented as an environment/configuration issue rather than a source packaging defect.
- Operational discovery CLI work is explicitly out of scope for this PR.

## 8. Linked Issue
- Closes #11
