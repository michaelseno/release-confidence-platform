# Implementation Plan

## 1. Feature Overview
Improve backend orchestrator observability for HITL `rcp audit run` correction by making INFO structured logs visible in Lambda and adding sanitized milestone/failure logs through the run lifecycle.

## 2. Technical Scope
- Configure handler logging from `LOG_LEVEL` for root and `release-confidence-platform` loggers while preserving the first-line `print()` fallback.
- Add orchestrator milestone logs around validation, duplicate checks, metadata writes, config loading, endpoint execution, raw-result writes, terminal updates, and final return status.
- Ensure orchestrator failure responses emit sanitized ERROR logs with safe correlation fields when available.
- Improve package-level DynamoDB `ClientError` mapping to actionable sanitized `StorageError` messages.
- Add targeted tests for log visibility, milestone ordering/presence, failure logging, and non-leakage.

## 3. Source Inputs
- `docs/bugs/audit_run_orchestrator_no_business_effects_bug_report.md`
- `docs/architecture/structured_logging.md`
- `docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md`
- Existing backend orchestrator, storage, and test patterns.

## 4. API Contracts Affected
No HTTP API contract changes.

Lambda handler response contract remains unchanged: sanitized `COMPLETED`/`FAILED` result payloads are returned by the existing orchestrator path.

## 5. Data Models / Storage Affected
No data model or storage schema changes.

DynamoDB run metadata access keeps existing keys and persistence behavior while mapping live `ClientError` exceptions to sanitized `StorageError` diagnostics.

## 6. Files Expected to Change
- `apps/backend/handlers/orchestrator_handler.py`
- `apps/backend/orchestrator/service.py`
- `packages/storage/dynamodb_client.py`
- `tests/unit/test_phase1_core_engine.py`
- `docs/backend/audit_run_orchestrator_observability_implementation_plan.md`
- `docs/backend/audit_run_orchestrator_observability_implementation_report.md`

## 7. Security / Authorization Considerations
- Logs must not include full Lambda events, endpoint headers, tokens, secrets, raw request/response payloads, or tracebacks.
- Include only safe correlation fields already used by app logs after event validation; pre-validation logs use only input type and scenario type when safely extractable.
- Failure logs include sanitized error type/code/message only.

## 8. Dependencies / Constraints
No new dependencies. No AWS deployment. Current branch remains active; no commit, push, or PR.

## 9. Assumptions
- Existing project logs already permit `client_id`, `audit_id`, and `run_id` as correlation fields after event validation.
- `LOG_LEVEL` defaults to `INFO` when unset or invalid.

## 10. Validation Plan
- Run targeted unit tests for orchestrator and handler logging.
- Run broader regression if time permits with `python -m pytest`.
