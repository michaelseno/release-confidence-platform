# Test Report

## 1. Execution Summary
- total validation groups: 8
- passed: 8
- failed: 0
- QA decision: approved; Ruff lint/format gates, focused infra/Lambda tests, artifact inspection, and full regression suite all passed

## 2. Detailed Results
| Test / Validation | Outcome | Evidence |
| --- | --- | --- |
| Active branch check | Passed | `git status --short --branch` returned `## feature/profile_driven_config_init`; no branch was created. |
| Backend requirements manifest | Passed | `apps/backend/requirements.txt` exists with `requests>=2.31,<3`. |
| Serverless dependency packaging config | Passed | `infra/serverless.yml` includes `serverless-python-requirements`; `custom.pythonRequirements.fileName: ../apps/backend/requirements.txt`; `infra/package.json` includes the plugin dependency. |
| Local package artifact freshness | Passed | Existing `infra/.serverless/release-confidence-platform.zip` was present and current versus `infra/serverless.yml`, `infra/package.json`, and `apps/backend/requirements.txt`: `fresh_vs_inputs=True`. No deploy was executed. |
| Direct artifact inspection | Passed | `infra/.serverless/release-confidence-platform.zip`: `entries=178 size=686933`; required dependency and source entries present. |
| Focused tests | Passed | `./.venv/bin/python -m pytest tests/unit/test_infra_configuration.py tests/unit/test_operator_cli_rcp.py`: `45 passed in 0.23s`. |
| Full regression tests | Passed | `./.venv/bin/python -m pytest`: `190 passed in 0.69s`. |
| Ruff lint gate | Passed | `./.venv/bin/python -m ruff check .`: `All checks passed!` |
| Ruff format gate | Passed | `./.venv/bin/python -m ruff format --check .`: `186 files already formatted`. |

Artifact inspection output:

```text
exists=True path=infra/.serverless/release-confidence-platform.zip
size=686933
fresh_vs_inputs=True
entries=178
requests/__init__.py: True
urllib3/__init__.py: True
certifi/__init__.py: True
charset_normalizer/__init__.py: True
idna/__init__.py: True
apps/backend/handlers/orchestrator_handler.py: True
apps/backend/runner/api_runner.py: True
packages/storage/s3_client.py: True
requests/entries=20
urllib3/entries=38
certifi/entries=5
charset_normalizer/entries=15
idna/entries=11
apps/backend/entries=17
packages/storage/entries=9
```

## 3. Failed Tests
No failed tests or quality gates in the rerun.

## 4. Failure Classification
No failures to classify.

## 5. Observations
- The dependency packaging defect is validated in the local package artifact.
- `package.patterns` retained backend source and shared package source in the final zip; direct inspection confirmed handler, runner, and shared storage source entries.
- Runtime compatibility is acceptable for the scoped dependency: Serverless runtime is `python3.11`, project requires `>=3.11,<3.12`, and `requests`/listed transitive dependencies are pure Python in this artifact.
- Synchronous diagnostic tests validate structured `LAMBDA_DEPENDENCY_IMPORT_ERROR` and `LAMBDA_RUNTIME_ERROR` handling with sanitized sensitive values.
- Async invocation limitation is documented in returned metadata and CLI guidance; accepted invoke does not prove handler import success.
- No AWS deploy was executed. Final live validation still requires human/deployment HITL to prove the deployed Lambda package has been refreshed.

## 6. Regression Check
- Focused regression: 45/45 passed.
- Full regression: 190/190 passed.
- Packaging regression: passed by direct zip inspection.
- Quality regression: Ruff lint and format gates passed.

## 7. QA Decision
[QA SIGN-OFF APPROVED]

All rerun criteria passed with evidence: Ruff lint/format, focused infra/Lambda tests, package artifact inspection, and full pytest regression suite.
