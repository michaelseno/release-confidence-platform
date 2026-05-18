# Implementation Plan

## 1. Feature Overview
Implement Phase 2 backend payload preparation for static, generated, and data-pool strategies within the existing Phase 1 orchestrator/runner flow.

## 2. Technical Scope
Add deterministic template substitution, S3-backed data-pool loading, sanitized SHA-256 fingerprints, in-run duplicate checking, endpoint safety validation, payload iteration support, and raw result payload metadata.

## 3. Source Inputs
- `docs/architecture/phase_2_payload_data_generation_technical_design.md`
- `docs/product/phase_2_payload_data_generation_product_spec.md`
- `docs/qa/phase_2_payload_data_generation_test_plan.md`
- `docs/release/phase_2_payload_data_generation_issue.md`

## 4. API Contracts Affected
No public API contract changes. Internal runner/orchestrator contracts are extended with run context, S3 storage access, duplicate checker, and payload metadata.

## 5. Data Models / Storage Affected
No new persisted tables. Raw result records keep `raw_result_version = "v1"` and add top-level `payload_strategy`, `response_fingerprint`, and nested `payload_metadata`. Data pools are read from `data-pools/{client_id}/{pool_name}.json`.

## 6. Files Expected to Change
- `apps/backend/orchestrator/service.py`
- `apps/backend/runner/api_runner.py`
- `packages/config/validators.py`
- `packages/data_generation/*`
- `packages/data-generation/*`
- `tests/unit/*phase2*`
- `tests/integration/*phase2*`

## 7. Security / Authorization Considerations
Validate strategy, duplicate policy/scope, pool names, templates, and safety controls. Never persist raw generated payloads or raw data-pool records in metadata; fingerprint only sanitized canonical representations. Block destructive operations unless explicitly allowed.

## 8. Dependencies / Constraints
Use only Python standard library plus existing requests/boto wrappers. No Phase 3 scheduling, auth/RBAC, billing, frontend, analytics, AI, or public API framework.

## 9. Assumptions
- Importable implementation modules are placed under `packages/data_generation` because Python cannot import the existing hyphenated `packages/data-generation` directory as a package.
- The required `packages/data-generation/*.py` paths are retained with compatibility notes for repository structure compliance.
- Static payloads use the existing Phase 1 `payload`/`body` endpoint field.

## 10. Validation Plan
- `.venv/bin/python -m ruff check .`
- `.venv/bin/python -m ruff format --check .`
- `.venv/bin/python -m pytest`
- `.venv/bin/python scripts/validate_config.py --samples-dir configs/samples`
- From `infra/`: `npx serverless package --stage dev`, `staging`, `prod`
- From `infra/`: `npx serverless package --stage qa` expected to fail
