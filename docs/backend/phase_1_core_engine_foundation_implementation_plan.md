# Implementation Plan

## 1. Feature Overview
Implement the Phase 1 backend core execution engine: Lambda orchestration, config loading, deterministic HTTP execution, Raw Result Schema v1 evidence, sanitization, and run metadata persistence.

## 2. Technical Scope
Backend-only implementation of the approved Phase 1 core engine foundation. Scope includes event validation, safe `run_id` generation/validation, duplicate protection, S3 config/result storage clients, DynamoDB metadata client, Secrets Manager resolver, runner/assertion logic, structured logging, and tests with fake clients.

## 3. Source Inputs
- `docs/architecture/phase_1_core_engine_foundation_technical_design.md`
- `docs/product/phase_1_core_engine_foundation_product_spec.md`
- `docs/qa/phase_1_core_engine_foundation_test_plan.md`
- `docs/release/phase_1_core_engine_foundation_issue.md`
- Existing Phase 0 package/test/serverless conventions

## 4. API Contracts Affected
No public HTTP API contract changes. The Lambda invocation event contract is implemented with required `client_id`, `audit_id`, `scenario_type`, `triggered_by`, and optional validated `run_id`. Structured sanitized success/failure dictionaries are returned.

## 5. Data Models / Storage Affected
- S3 config reads from `configs/{client_id}/client_config.json`, `configs/{client_id}/audits/{audit_id}/audit_config.json`, and `configs/{client_id}/audits/{audit_id}/endpoints.json`.
- S3 raw result write once to `raw-results/{client_id}/{audit_id}/{run_id}/results.json`.
- DynamoDB run metadata keys `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#RUN#{run_id}` with statuses `STARTED`, `COMPLETED`, `FAILED`.
- Raw Result Schema v1 endpoint records.

## 6. Files Expected to Change
- `apps/backend/handlers/`, `apps/backend/orchestrator/`, `apps/backend/runner/`
- `packages/config/`, `packages/core/`, `packages/sanitization/`, `packages/storage/`
- Phase 1 unit/integration tests under `tests/`
- `docs/backend/phase_1_core_engine_foundation_implementation_*`

## 7. Security / Authorization Considerations
Phase 1 has no auth/RBAC. Security controls are validation before use, strict run id allowlist, no logging of rejected run ids, Secrets Manager-only secret resolution, centralized redaction before logs/storage, and duplicate protection for immutable evidence.

## 8. Dependencies / Constraints
Uses existing `boto3` and `requests` dependencies only. AWS clients remain injectable/fakeable. No live AWS credentials are required for tests.

## 9. Assumptions
- Endpoint configs may be either a top-level list or an object containing `endpoints` to preserve Phase 0 sample compatibility.
- Existing Phase 0 samples are allowed to omit Phase 1-only endpoint fields because `scripts/validate_config.py` is a Phase 0 sample validator; runtime Phase 1 validation enforces executable endpoint requirements.

## 10. Validation Plan
- `.venv/bin/python -m ruff check .`
- `.venv/bin/python -m ruff format --check .`
- `.venv/bin/python -m pytest`
- `.venv/bin/python scripts/validate_config.py --samples-dir configs/samples`
- From `infra/`: `npx serverless package --stage dev`, `staging`, `prod`
- From `infra/`: `npx serverless package --stage qa` expected to fail
