# Test Report

## 1. Execution Summary

- Feature: Phase 1 Core Engine Foundation
- Branch under validation: `feature/phase_1_core_engine_foundation`
- QA scope: Phase 1 backend core engine only; no live AWS deployment required; AWS and HTTP behavior validated through local mocks/fakes.
- Total automated tests in final full suite: 25
- Passed: 25
- Failed: 0
- Skipped/XFailed: 0
- QA-added regression/security tests: `tests/security/test_phase1_qa_contracts.py` (5 tests, all passing)

## 2. Detailed Results

| Validation | Command / Evidence | Outcome |
| --- | --- | --- |
| Python runtime | `.venv/bin/python --version` -> `Python 3.11.11` | Pass |
| Ruff lint | `.venv/bin/python -m ruff check .` -> `All checks passed!` | Pass |
| Ruff format | `.venv/bin/python -m ruff format --check .` -> `39 files already formatted` | Pass |
| Full pytest suite | `.venv/bin/python -m pytest` -> `25 passed in 0.19s` | Pass |
| Config sample validation | `.venv/bin/python scripts/validate_config.py --samples-dir configs/samples` -> validated Phase 0 sample configs | Pass |
| Serverless package dev | `npx serverless package --stage dev` from `infra/` -> service packaged | Pass |
| Serverless package staging | `npx serverless package --stage staging` from `infra/` -> service packaged | Pass |
| Serverless package prod | `npx serverless package --stage prod` from `infra/` -> service packaged | Pass |
| Serverless package qa | `npx serverless package --stage qa` from `infra/` -> failed with `Unsupported Serverless stage 'qa'. Expected one of: dev, staging, prod` | Pass, expected failure |

## 3. Failed Tests

No unresolved failed tests.

During QA test authoring, one assertion was corrected because URL query redaction persists an URL-encoded redaction marker (`%5BREDACTED%5D`) inside a URL string while still removing the raw sensitive values. Final automated suite is passing.

## 4. Failure Classification

No application defects, test bugs, environment issues, or flaky tests remain open.

## 5. Observations

- Orchestrator event contract validates required fields and supports optional/generated `run_id` behavior.
- Supplied `run_id` validation uses exact policy `^[A-Za-z0-9_-]{8,80}$` in `packages/core/validators.py`.
- Invalid supplied `run_id` values are rejected before config loading, metadata persistence, raw result persistence, or outbound HTTP execution; captured QA test verifies raw rejected value is absent from response/log records.
- Valid supplied `run_id` is used unchanged in S3 raw result path, DynamoDB metadata key, raw result records, response, and sanitized log records.
- Duplicate S3 raw result object and duplicate DynamoDB metadata item paths return controlled `DUPLICATE_RUN_ID` failures without overwriting/append/merge behavior.
- `DUPLICATE_RUN_ID` is not present in `ENDPOINT_FAILURE_TYPES` and is handled as a run-level/storage control error.
- S3 config paths match required patterns for client, audit, and endpoints config.
- Secrets Manager reference handling is validated with mocks; resolved secret reaches request execution only and is not persisted in raw results, metadata, or logs.
- Runner uses `requests.Session().request(...)` and `time.monotonic()` around outbound request execution.
- Failure classifications are limited to approved endpoint values. QA regression tests cover `TIMEOUT`, `INVALID_RESPONSE`, connection error, pass path, and payload validation pre-run rejection.
- Raw Result Schema v1 uses `raw_result_version = "v1"` and persists one `results.json` envelope at `raw-results/{client_id}/{audit_id}/{run_id}/results.json`.
- Sanitization is centralized and replaces sensitive key values with `[REDACTED]`; sensitive URL query values are persisted as URL-encoded redaction markers, with raw sensitive values removed.
- Structured logs use approved categories: `internal_operational_logs` and `client_safe_logs`.
- Static scope review found frontend remains a placeholder (`apps/frontend/README.md`) and no dashboard implementation was introduced.

## 6. Regression Check

- Existing Phase 0/unit tests remain passing after Phase 1 validation additions.
- Serverless packaging remains valid for `dev`, `staging`, and `prod`.
- Serverless packaging correctly rejects unsupported `qa` stage.
- No live AWS credentials/resources were required for validation.
- Static review confirmed `requests` usage and monotonic timing source in the backend runner.
- Static review confirmed endpoint failure enum excludes `DUPLICATE_RUN_ID`.
- Static review confirmed no Phase 2/3 dashboard/frontend implementation; report-engine and frontend are placeholders/schema boundaries only.

## 7. QA Decision

QA status: Approved.

Evidence supports that Phase 1 acceptance criteria are satisfied within the requested local/mock validation scope. No blocking defects or major regressions are open.

[QA SIGN-OFF APPROVED]
