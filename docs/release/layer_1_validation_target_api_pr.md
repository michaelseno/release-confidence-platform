# Pull Request

## 1. Feature Name
Layer 1 Validation Target API

## 2. Summary
Adds a backend-only/internal mock target API fixture for validating release-confidence audit behavior against known deterministic endpoint outcomes. The service is implemented under `apps/mock-target-api/` using Python 3.11 AWS Lambda handlers behind Serverless Framework HTTP API routes.

The fixture provides controlled healthy, slow, flaky, inconsistent, and timeout behaviors so audit runner execution, raw evidence capture, failure classification, lifecycle handling, and future deterministic analytics inputs can be validated without relying on external systems.

## 3. Related Documents
- Product Spec: docs/product/layer_1_validation_target_api.md
- Technical Design: docs/architecture/layer_1_validation_target_api_technical_design.md
- UI/UX Spec: N/A — backend-only/internal infrastructure fixture
- QA Test Plan: docs/qa/layer_1_validation_target_api_test_plan.md
- QA Report: docs/qa/layer_1_validation_target_api_qa_report.md
- HITL Fix Test Plan: docs/qa/mock_target_api_serverless_tooling_hitle_fix_test_plan.md
- HITL Fix Test Report: docs/qa/mock_target_api_serverless_tooling_hitle_fix_test_report.md
- HITL Bug Report: docs/bugs/mock_target_api_serverless_package_bug_report.md
- Release Issue: docs/release/layer_1_validation_target_api_issue.md

## 4. Changes Included
- Implemented `apps/mock-target-api/` as a lightweight Serverless Framework app.
- Added endpoint handlers for:
  - `GET /health/fast`
  - `GET /health/slow`
  - `GET /health/flaky`
  - `GET /health/inconsistent`
  - `GET /health/timeout`
- Added deterministic service/util modules for response construction, stable SHA-256 hashing, slow delay resolution, flaky decisioning, inconsistent variant selection, and timeout mode selection.
- Added unit and integration coverage for handler/service behavior and optional deployed HTTP validation.
- Added sample API Gateway HTTP API events and fixture documentation.
- Added app-local Serverless v3 tooling and npm scripts so packaging does not depend on globally installed Serverless Framework v4.
- Updated README/backend implementation guidance to prefer local npm-script packaging/deployment commands.
- Added release/planning/QA/bug artifacts for feature traceability and HITL blocker correction.

## 5. QA Status
- Approved: YES
- QA gate: `[QA SIGN-OFF APPROVED]`
- HITL gate: `HITL validation successful`

## 6. Test Coverage
- Original feature QA: `17 passed, 2 skipped` from `./.venv/bin/python -m pytest apps/mock-target-api/tests/unit apps/mock-target-api/tests/integration`.
- Regression checks: Python `compileall` passed for `apps/mock-target-api`.
- Lint checks: `./.venv/bin/python -m ruff check apps/mock-target-api` passed.
- HITL packaging validation: `npm install`, `npm run package -- --stage dev`, and direct local `serverless package --stage dev` completed successfully after the packaging/tooling fix.
- Expected skips: 2 optional deployed HTTP integration tests skipped because `MOCK_TARGET_API_BASE_URL` was not configured.

## 7. Risks / Notes
- `/health/timeout` intentionally exceeds the platform runner/API timeout threshold by default; Lambda/API Gateway/client timeout behavior may prevent a completed JSON response, which is expected for timeout validation.
- `MOCK_TARGET_SHORT_TIMEOUT=true` must not be accidentally enabled for deployed stage validation where production-like timeout behavior is required.
- Time-window fallback exists for manual exploration only; automated tests should continue to use explicit seeds/variants for reproducibility.
- Serverless v3 dev-tooling transitive `npm audit` findings remain a non-blocking tooling risk for this internal fixture; forced upgrade to Serverless v4 would reintroduce the HITL packaging blocker class.
- Optional deployed HTTP tests require `MOCK_TARGET_API_BASE_URL` and were not executed against a live deployed endpoint in local QA.

## 8. Linked Issue
- Closes #9
