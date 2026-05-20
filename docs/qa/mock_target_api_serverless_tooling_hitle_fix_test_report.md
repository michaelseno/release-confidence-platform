# Test Report

## 1. Execution Summary

- total tests/checks: 8
- passed: 8
- failed: 0
- skipped: 2 deployed HTTP integration test cases inside pytest, expected because `MOCK_TARGET_API_BASE_URL` was not configured
- branch/commit context: `ffc185b fix(backend): add mock target api serverless tooling`

## 2. Detailed Results

| Test ID | Outcome | Evidence |
| --- | --- | --- |
| QA-HITL-001 npm install | Passed | From `apps/mock-target-api`: `npm install` completed: `added 1 package, and audited 567 packages in 2s`; reported `6 vulnerabilities (1 low, 3 moderate, 2 high)`. |
| QA-HITL-002 npm package dev | Passed | From `apps/mock-target-api`: `npm run package -- --stage dev` output included `Packaging mock-target-api for stage dev (us-east-1)` and `✔ Service packaged (3s)`. `.serverless/` contains `mock-target-api.zip`, `serverless-state.json`, and CloudFormation templates. |
| QA-HITL-003 direct serverless after local install | Passed | From `apps/mock-target-api`: `serverless --version` reported `Framework Core: 3.40.0 (local)`. `serverless package --stage dev` output included `Packaging mock-target-api for stage dev (us-east-1)` and `✔ Service packaged (2s)`. Prior blocker `No version found for 3` did not occur. |
| QA-HITL-004 documentation validation | Passed | `apps/mock-target-api/README.md` instructs `npm install`, `npm run package -- --stage dev`, `npm run package:staging`, `npm run package:prod`, and states: `Do not rely on a globally installed serverless/sls binary`. Backend implementation report also records local Serverless v3 tooling and npm-script usage. |
| QA-HITL-005 pytest regression | Passed | `./.venv/bin/python -m pytest apps/mock-target-api/tests/unit apps/mock-target-api/tests/integration` collected 19 items: `17 passed, 2 skipped in 0.06s`. Skips are the optional deployed HTTP tests without `MOCK_TARGET_API_BASE_URL`. |
| QA-HITL-006 compile regression | Passed | `./.venv/bin/python -m compileall apps/mock-target-api` completed successfully. Narrow source-only rerun also completed: listed `handlers`, `services`, `tests`, `tests/integration`, `tests/unit`, and `utils` with no errors. |
| QA-HITL-007 ruff regression | Passed | `./.venv/bin/python -m ruff check apps/mock-target-api` output: `All checks passed!` |
| QA-HITL-008 no scope creep | Passed | `git show --stat ffc185b` shows changes limited to `apps/mock-target-api` Serverless tooling/docs plus backend implementation docs. Source search found no FastAPI/Flask/Django/SQLAlchemy/boto3/auth/JWT/analytics/observability frontend framework additions in Python source. `package.json` adds only dev dependency `serverless: ^3.38.0`. |

Additional generated package evidence:

```text
.serverless/
cloudformation-template-create-stack.json
cloudformation-template-update-stack.json
mock-target-api.zip
serverless-state.json
```

Generated Serverless state evidence includes `runtime: python3.11` and all five functions: `healthFast`, `healthSlow`, `healthFlaky`, `healthInconsistent`, `healthTimeout`.

## 3. Failed Tests

None.

## 4. Failure Classification

No validation failures observed.

Non-blocking findings assessed:

| Finding | Classification | Assessment |
| --- | --- | --- |
| Node `[DEP0040]` `punycode` deprecation warning during Serverless commands | Environment/toolchain warning | Non-blocking. Packaging completes successfully; warning originates from Serverless v3 dependency chain under Node 22. |
| `healthTimeout` timeout warning: Lambda timeout 50s exceeds HTTP API max 30s | Intentional fixture behavior | Non-blocking. `/health/timeout` is designed to exceed runner/API timeout thresholds for timeout validation. |
| `npm audit` reports 6 Serverless v3 transitive vulnerabilities: `aws-sdk`, `file-type`, `tar`; `npm audit fix --force` would install Serverless v4.36.1 | Dependency risk, accepted for internal dev tooling fixture | Non-blocking for this HITL blocker correction because dependency is app-local dev tooling for packaging, not runtime Lambda application code; forced remediation would reintroduce unsupported Serverless v4 behavior. Track separately if repository policy requires zero dev-tool audit findings. |
| Optional deployed HTTP integration tests skipped | Environment-bound skip | Non-blocking. No `MOCK_TARGET_API_BASE_URL` was configured; local handler integration and unit tests passed. |

## 5. Observations

- The exact HITL blocker is fixed: neither npm-script packaging nor direct `serverless package --stage dev` after local install produced `No version found for 3`.
- Direct `serverless` in this environment resolves/delegates to local Serverless Framework Core `3.40.0`; supported documentation still correctly instructs npm scripts as the deterministic path.
- `serverless.yml` uses `frameworkVersion: "^3.38.0"`, preserving the repository-supported Serverless v3 line.
- Existing historical/specification documents may still contain examples of direct `sls` usage, but current operational README/backend implementation documentation for this fixture points to app-local npm scripts and explicitly warns against global CLI reliance.

## 6. Regression Check

- Original mock-target-api unit and integration coverage passed: 17 passed, 2 expected skips.
- Python syntax compilation passed.
- Ruff linting passed.
- Serverless package output still targets Python 3.11 and includes all five fixture functions.
- No frontend/auth/database/analytics/observability/heavy-framework scope expansion was found in the fix.

## 7. QA Decision

Approved. The HITL blocker is resolved with evidence, regressions passed, and remaining warnings are non-blocking for an internal packaging fixture.
