# Test Plan

## 1. Feature Overview

HITL blocker correction for `apps/mock-target-api` Serverless packaging on branch `feature/layer_1_validation_target_api`. The fix adds app-local Serverless Framework v3 npm tooling and documents npm-script usage so packaging no longer depends on unsupported global Serverless v4 behavior that previously failed with `No version found for 3`.

## 2. Acceptance Criteria Mapping

| ID | Acceptance criterion | Validation approach |
| --- | --- | --- |
| AC-HITL-1 | `npm install` succeeds for `apps/mock-target-api` and installs local Serverless v3 tooling. | Run `npm install` from `apps/mock-target-api`; inspect package metadata and command output. |
| AC-HITL-2 | `npm run package -- --stage dev` succeeds and creates package artifacts. | Run packaging command from `apps/mock-target-api`; verify `.serverless/` outputs. |
| AC-HITL-3 | `serverless package --stage dev` is feasible after local install and does not reproduce `No version found for 3`. | Run direct `serverless --version` and `serverless package --stage dev` from `apps/mock-target-api`. |
| AC-HITL-4 | Supported docs instruct local npm script usage and do not require global Serverless v4 behavior. | Review `apps/mock-target-api/README.md` and implementation docs for local npm commands and global CLI caution. |
| AC-HITL-5 | Original mock-target-api behavior remains intact. | Run unit/integration tests, compileall, and ruff checks using repo virtualenv. |
| AC-HITL-6 | No scope creep into frontend/auth/db/analytics/observability/heavy-framework areas. | Inspect fix commit file scope, package dependencies, and application source references. |

## 3. Test Scenarios

| Test ID | Purpose | Input / command | Expected output | Validation logic |
| --- | --- | --- | --- | --- |
| QA-HITL-001 | Verify npm dependency bootstrap | `npm install` in `apps/mock-target-api` | Install completes; Serverless v3 dependency available; audit findings documented if present | Command exits successfully; no install blocker |
| QA-HITL-002 | Verify supported packaging path | `npm run package -- --stage dev` | `Packaging mock-target-api for stage dev` and `Service packaged` | Command exits successfully and `.serverless/mock-target-api.zip` exists |
| QA-HITL-003 | Verify direct command no longer reproduces HITL failure after local install | `serverless --version && serverless package --stage dev` | Local Framework Core v3 reported; no `No version found for 3`; package succeeds | Command output confirms local v3 delegation and successful package |
| QA-HITL-004 | Verify docs | Static review of README/backend docs | Docs direct users to `npm install` and `npm run package...`; warn not to rely on global `serverless`/`sls` | Content review against acceptance criteria |
| QA-HITL-005 | Regression tests | `./.venv/bin/python -m pytest apps/mock-target-api/tests/unit apps/mock-target-api/tests/integration` | Existing test suite passes; deployed HTTP tests may skip without `MOCK_TARGET_API_BASE_URL` | Pytest summary has no failures/errors |
| QA-HITL-006 | Syntax compilation | `./.venv/bin/python -m compileall ...` | Python files compile | Command exits successfully |
| QA-HITL-007 | Lint regression | `./.venv/bin/python -m ruff check apps/mock-target-api` | Ruff passes | Command exits successfully |
| QA-HITL-008 | Scope creep review | Commit/file/dependency/source inspection | Only mock-target-api tooling/docs changed; no unrelated product surfaces added | Commit file list and source search show no frontend/auth/db/etc. additions |

## 4. Edge Cases

- Environment has global Serverless v4 installed: validate app-local v3 prevents the prior `No version found for 3` failure.
- Lambda timeout warning for `/health/timeout`: expected because endpoint intentionally sleeps beyond HTTP API max timeout for runner timeout validation.
- npm audit findings from Serverless v3 transitive dependencies: document and classify against internal fixture scope.
- Deployed HTTP integration tests without `MOCK_TARGET_API_BASE_URL`: expected skips, not failures.

## 5. Test Types Covered

- Functional packaging validation.
- Documentation validation.
- Regression validation for existing Python handlers/services/tests.
- Static/scope review.
- Dependency/audit risk assessment.

## 6. Coverage Justification

The plan directly validates the reported HITL failure path, the supported deterministic npm-script replacement, direct command feasibility after local install, original mock-target-api regression coverage, and the absence of unrelated architectural additions. Optional deployed HTTP tests are bounded by environment configuration and are acceptable to skip when no deployed base URL is configured.
