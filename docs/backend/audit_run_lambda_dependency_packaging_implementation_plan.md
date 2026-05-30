# Implementation Plan

## 1. Feature Overview
Fix the backend Lambda packaging defect that omitted the `requests` runtime dependency from the Serverless deployment artifact used by `rcp audit run`.

## 2. Technical Scope
- Add a backend Lambda dependency manifest for runtime Python dependencies.
- Configure Serverless packaging to install/package backend Python requirements.
- Preserve existing source package patterns for backend handlers and shared packages.
- Add static and artifact-aware regression tests for dependency packaging.
- Improve Lambda invoke diagnostics for detectable synchronous runtime import failures without changing async invocation semantics.

## 3. Source Inputs
- `docs/bugs/audit_run_lambda_dependency_packaging_bug_report.md`
- `docs/backend/audit_run_lambda_diagnostics_implementation_plan.md`
- `docs/backend/audit_run_lambda_diagnostics_implementation_report.md`
- Existing backend Lambda packaging in `infra/serverless.yml`
- Existing Lambda diagnostics implementation in `src/release_confidence_platform/storage/lambda_client.py`

## 4. API Contracts Affected
No HTTP API contract changes. CLI diagnostics may now map synchronous Lambda runtime import failures with `FunctionError` to `LAMBDA_DEPENDENCY_IMPORT_ERROR` and generic synchronous runtime failures to `LAMBDA_RUNTIME_ERROR`.

## 5. Data Models / Storage Affected
No data model or storage changes.

## 6. Files Expected to Change
- `apps/backend/requirements.txt`
- `infra/package.json`
- `infra/serverless.yml`
- `src/release_confidence_platform/storage/lambda_client.py`
- `src/release_confidence_platform/operator_cli/result.py`
- `tests/unit/test_infra_configuration.py`
- `tests/unit/test_operator_cli_rcp.py`
- `docs/backend/audit_run_lambda_dependency_packaging_implementation_report.md`

## 7. Security / Authorization Considerations
- Do not include secrets in dependency manifests or configuration.
- Sanitize Lambda runtime diagnostic payload/log excerpts before displaying them.
- Preserve existing Lambda invocation permission/config guidance.
- Do not deploy or access AWS during this task.

## 8. Dependencies / Constraints
- Add `requests>=2.31,<3` for backend Lambda runtime import path.
- Add `serverless-python-requirements` to the Serverless service dev/deploy dependency set.
- Use `../apps/backend/requirements.txt` because the Serverless service root is `infra/`.
- Keep `dockerizePip: non-linux` and `slim: true` per bug-investigator guidance.

## 9. Assumptions
- `requests` is the only third-party dependency missing from the backend Lambda import path; `boto3` is available in the Lambda Python runtime and was not implicated in the observed failure.
- Async Lambda invocation cannot reliably surface runtime initialization failures to the CLI at invoke time; synchronous invoke diagnostics are improved only when `FunctionError`, payload, or log tail details are present in the invoke response.

## 10. Validation Plan
- Run focused unit tests for infra packaging configuration and Lambda diagnostics.
- Run local `npx serverless package --stage dev` from `infra/` without deployment.
- Inspect `infra/.serverless/release-confidence-platform.zip` for `requests`, transitive dependencies, and the orchestrator handler path.
