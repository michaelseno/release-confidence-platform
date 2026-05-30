# Implementation Plan

## 1. Feature Overview
Fix `rcp audit schedule` scheduler boundary handling so EventBridge Scheduler payloads are valid JSON strings and scheduler/config failures render as structured, actionable errors instead of `UNEXPECTED_ERROR`. HITL correction update: include safe EventBridge Scheduler validation diagnostics for `SCHEDULE_CONFIG_ERROR` without exposing raw target inputs or secrets.

## 2. Technical Scope
- Serialize EventBridge Scheduler `Target.Input` from sanitized schedule payloads.
- Map Scheduler AWS SDK validation, client, and provider errors to sanitized platform errors.
- Reject placeholder scheduler stage configuration before non-dry-run schedule mutation attempts.
- Expose resolved non-secret scheduler fields and override guidance in `rcp config stage-info`.
- Update CLI next-step guidance for scheduler errors.
- For Scheduler validation/config `ClientError`s, include sanitized provider `Error.Message` and a sanitized create request shape with only approved fields.

## 3. Source Inputs
- `docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md`
- `docs/bugs/audit_schedule_unexpected_error_bug_report.md`
- `docs/bugs/audit_schedule_scheduler_validation_diagnostics_bug_report.md`
- Existing operator CLI and storage wrapper patterns.

## 4. API Contracts Affected
No public HTTP API contract changes.

Internal CLI contracts affected:
- `rcp audit schedule --stage <stage>` now validates deployed scheduler config before non-dry-run AWS schedule creation.
- `rcp config stage-info --stage <stage> --output text|json` includes scheduler group, target ARNs, scheduler role ARN, schedule name prefix, and relevant `RCP_*` override guidance.
- Scheduler `SCHEDULE_CONFIG_ERROR` messages for validation/config-style AWS `ClientError`s include `provider_message=<sanitized message>` and `request_shape=<safe JSON object>` when available.

## 5. Data Models / Storage Affected
No data model or storage changes.

## 6. Files Expected to Change
- `src/release_confidence_platform/storage/eventbridge_scheduler_client.py`
- `packages/storage/eventbridge_scheduler_client.py`
- `src/release_confidence_platform/config/stage_config.py`
- `packages/config/stage_config.py`
- `src/release_confidence_platform/operator_cli/services.py`
- `packages/operator_cli/services.py`
- `src/release_confidence_platform/operator_cli/result.py`
- CLI/unit tests under `tests/unit/`

## 7. Security / Authorization Considerations
Scheduler payloads are sanitized before JSON serialization. Validation diagnostics must not expose raw `Target.Input`, payload values, raw AWS exceptions, credentials, tokens, cookies, authorization headers, or raw request dumps. Provider messages are sanitized and auth-like assignments/bearer tokens are redacted. Request-shape diagnostics are restricted to `operation`, schedule/group/expression/time fields, target/role ARNs, and top-level `input_keys` only. ARNs and resource names exposed by stage-info are non-secret operator configuration values.

## 8. Dependencies / Constraints
No new dependencies. Uses existing `botocore` exception classes and standard-library `json`. No AWS deployment or live schedule creation.

## 9. Assumptions
- Placeholder scheduler config is indicated by `placeholder`, empty values, or account `000000000000` in configured scheduler ARNs.
- Dry-run schedule planning may continue without rejecting scheduler resource placeholders because it performs no schedule mutation.
- Existing CLI error rendering exposes only the error message and generic fields, so safe Scheduler diagnostics are included in the sanitized `StorageError.message` instead of adding a new CLI payload contract.
- Malformed or non-object `Target.Input` diagnostics use an empty `input_keys` list.

## 10. Validation Plan
- Run targeted pytest coverage for scheduler client, schedule command validation, and stage-info rendering.
- Run syntax compilation for modified source/package modules.
- Run targeted coverage for sanitized provider messages, exact request-shape allowlist, input-key-only diagnostics, malformed input handling, CLI text/JSON rendering, and src/packages mirror parity where the local environment supports pytest.
