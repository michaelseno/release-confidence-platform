# Test Plan

## 1. Feature Overview
Validate the backend fix for the `rcp audit run` Lambda runtime import failure:
`Runtime.ImportModuleError: No module named 'requests'`.

Scope covers local dependency packaging, Serverless configuration, artifact contents, runtime compatibility assumptions, synchronous Lambda diagnostic mapping, async invocation limitation documentation, and regression gates. No AWS deployment is in scope.

## 2. Acceptance Criteria Mapping
| ID | Acceptance Criterion | Validation Method |
| --- | --- | --- |
| AC1 | Backend dependency manifest exists and safely constrains `requests`. | Inspect `apps/backend/requirements.txt`; run static test. |
| AC2 | Serverless uses `serverless-python-requirements` and points to backend requirements. | Inspect `infra/serverless.yml`, `infra/package.json`; run static test. |
| AC3 | Local packaging succeeds without deployment. | Run `npm install && npx serverless package --stage dev` from `infra/`. |
| AC4 | Final zip contains `requests`, transitive dependencies, and handler/source files. | Inspect `infra/.serverless/release-confidence-platform.zip` directly via `zipfile`. |
| AC5 | Package patterns do not remove source/dependencies. | Inspect package patterns and packaged artifact entries. |
| AC6 | Runtime/package compatibility assumptions are acceptable. | Inspect Python runtime and project Python version; verify dependency is pure Python. |
| AC7 | Detectable synchronous Lambda dependency/runtime failures are structured and sanitized. | Run focused unit tests for `LambdaInvocationClient`/CLI rendering. |
| AC8 | Async invocation limitation is documented. | Inspect implementation and run async acceptance unit test. |
| AC9 | Focused and full regressions pass. | Run focused pytest subset and full pytest suite. |
| AC10 | Ruff lint/format quality gates pass if required by repo. | Run `ruff check .` and `ruff format --check .`. |

## 3. Test Scenarios
1. Manifest validation: confirm `apps/backend/requirements.txt` contains `requests>=2.31,<3`.
2. Serverless plugin validation: confirm `serverless-python-requirements` is configured with `fileName: ../apps/backend/requirements.txt` and package dependency is present.
3. Safe local package build: run Serverless package from `infra/` with no deploy command.
4. Artifact content verification: assert the generated zip contains:
   - `requests/__init__.py`
   - `urllib3/__init__.py`
   - `certifi/__init__.py`
   - `charset_normalizer/__init__.py`
   - `idna/__init__.py`
   - `apps/backend/handlers/orchestrator_handler.py`
5. Source retention verification: assert backend runner and shared package source remain in the zip.
6. Diagnostic verification: simulate synchronous Lambda `FunctionError` payloads for import and generic runtime failures, and verify structured sanitized errors.
7. Async limitation verification: verify accepted async invoke metadata states acceptance does not guarantee handler success.
8. Regression verification: run focused tests and full pytest suite.
9. Quality gate verification: run Ruff lint and format checks.

## 4. Edge Cases
- Stale artifact after config changes is skipped by unit test but direct packaging generates fresh artifact.
- Synchronous import failure payload includes sensitive assignment (`token=secret`) and must be redacted.
- Generic runtime failure includes bearer token and must be redacted.
- Async `InvocationType=Event` returns 202 while handler import may still fail later in CloudWatch.
- Non-Linux dependency packaging is configured with `dockerizePip: non-linux` for future compatibility.

## 5. Test Types Covered
- Functional: manifest/config/artifact validation.
- Negative: Lambda runtime/import failure mapping.
- Security: diagnostic sanitization/redaction.
- Integration: Serverless local package generation and zip inspection.
- Regression: focused unit subset and full pytest suite.
- Quality: Ruff lint and format checks.

## 6. Coverage Justification
The plan directly validates the previously missing dependency in the actual packaged Lambda zip, not only static configuration. It also protects the operator experience by validating structured diagnostics for detectable synchronous failures while preserving the documented async limitation. Full regression and Ruff gates provide broad confidence that the packaging/diagnostic changes did not break existing behavior or repository quality standards.
