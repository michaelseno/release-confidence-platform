# Implementation Plan

## 1. Feature Overview
Improve `rcp audit run` Lambda invocation diagnostics for HITL validation when the configured orchestrator Lambda target is missing, placeholder-based, or inaccessible.

## 2. Technical Scope
- Preserve sanitized AWS Lambda `ClientError` diagnostics in storage-layer errors.
- Add actionable CLI next-step guidance for Lambda config and permission failures.
- Validate placeholder `orchestrator_function_name` values before non-dry-run Lambda invocation.
- Expose the effective orchestrator Lambda target in `rcp config stage-info`.
- Document that async Lambda invoke acceptance does not guarantee handler success.

## 3. Source Inputs
- `docs/bugs/audit_run_lambda_invocation_failed_diagnostics_bug_report.md`
- `docs/architecture/operator_cli_rcp_technical_design.md`
- Existing CLI/storage patterns in `src/release_confidence_platform/operator_cli/` and `src/release_confidence_platform/storage/`
- Existing S3/DynamoDB diagnostic tests and error mapping conventions.

## 4. API Contracts Affected
CLI contract changes only:
- `rcp audit run`: same inputs; non-dry-run fails before AWS invoke when `orchestrator_function_name` is a placeholder, returning a structured config error.
- `rcp config stage-info`: output includes `orchestrator_function_name` and guidance for `RCP_ORCHESTRATOR_FUNCTION_NAME`.
- Error rendering: Lambda config/permission/invocation errors include Lambda-specific next steps.

## 5. Data Models / Storage Affected
No data model or storage schema changes. Lambda invocation wrapper error mapping is updated only.

## 6. Files Expected to Change
- `src/release_confidence_platform/config/stage_config.py`
- `src/release_confidence_platform/core/manual_run_service.py`
- `src/release_confidence_platform/operator_cli/services.py`
- `src/release_confidence_platform/operator_cli/result.py`
- `src/release_confidence_platform/storage/lambda_client.py`
- Focused unit/API tests under `tests/`
- Backend implementation report under `docs/backend/`

## 7. Security / Authorization Considerations
- Do not log or expose Lambda payloads.
- Sanitize AWS error messages before surfacing them to CLI output.
- Preserve function target context in a sanitized/truncated form only.
- Distinguish missing target/config errors from IAM permission errors without leaking secrets.

## 8. Dependencies / Constraints
- Uses existing `botocore.exceptions.ClientError` dependency already present in the project.
- No live Lambda calls in tests.
- No changes to `config init` resource generation, AWS credentials, or remote infrastructure.
- Active branch remains `feature/profile_driven_config_init`; no commit/push/PR.

## 9. Assumptions
- Placeholder resource names are identified by the substring `placeholder`, matching committed stage config conventions.
- Lambda `ResourceNotFoundException` is a configuration-target error; `AccessDeniedException` is a permission error.
- Generic Lambda `ClientError` should keep the existing `LAMBDA_INVOCATION_FAILED` platform error semantic while adding sanitized context.

## 10. Validation Plan
- Run focused tests for Lambda diagnostics and config stage-info.
- Run prior related regression tests for config init/no-AWS and operator CLI where feasible.
