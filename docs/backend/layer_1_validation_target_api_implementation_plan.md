# Implementation Plan

## 1. Feature Overview
Implement the Layer 1 Validation Target API as a lightweight backend-only Serverless Framework app under `apps/mock-target-api/` with controlled Lambda health endpoints for validation of audit runner behavior.

## 2. Technical Scope
Create five Python 3.11 Lambda handlers for fast, slow, flaky, inconsistent, and timeout health behavior. Add deterministic SHA-256 hashing, response helpers, endpoint-specific services, sample HTTP API events, tests, deployment config, and fixture documentation.

## 3. Source Inputs
- `docs/architecture/layer_1_validation_target_api_technical_design.md`
- `docs/product/layer_1_validation_target_api.md`
- `docs/qa/layer_1_validation_target_api_test_plan.md`
- `docs/release/layer_1_validation_target_api_issue.md`

## 4. API Contracts Affected
- `GET /health/fast`: 200 JSON `{service, endpoint, status}`.
- `GET /health/slow`: 200 JSON `{service, endpoint, status, delay_ms, delay_source}`; accepts optional `delay_ms` and `seed` query parameters with fallback behavior.
- `GET /health/flaky`: 200 healthy or intentional 500 degraded JSON based on `stable_hash(seed) % 5`; query seed precedes `X-RCP-Seed` header.
- `GET /health/inconsistent`: 200 JSON Variant A or B; forced `variant=A|B` precedes seed-derived variant.
- `GET /health/timeout`: 200 JSON if completed; default 35-45 second sleep, short 2-3 second mode only when `MOCK_TARGET_SHORT_TIMEOUT=true`.

## 5. Data Models / Storage Affected
No data model or storage changes.

## 6. Files Expected to Change
- New `apps/mock-target-api/` handlers, services, utils, tests, sample events, docs, `requirements.txt`, `serverless.yml`, and `README.md`.
- New backend implementation plan/report under `docs/backend/`.

## 7. Security / Authorization Considerations
No application authentication or authorization per design. Inputs are validated/fallback-only. Logs must not include raw headers, raw events, raw seeds, secrets, authorization values, or cookies. Responses avoid echoing seed values.

## 8. Dependencies / Constraints
Runtime uses Python 3.11 standard library only. Test dependency is pytest in `requirements.txt`. No database, Cognito, S3 persistence, frontend, analytics, AI, or heavy framework dependencies.

## 9. Assumptions
- SHA-256 integer hashing is the approved stable interpretation of product references to `hash(seed)`.
- Optional deterministic diagnostic fields from the technical design are included where specified for validation support.
- Integration HTTP tests are skippable unless `MOCK_TARGET_API_BASE_URL` is provided.

## 10. Validation Plan
- Run `python -m pytest apps/mock-target-api/tests/unit apps/mock-target-api/tests/integration`.
- Run `python -m compileall apps/mock-target-api`.
- Inspect git diff/status before committing.
