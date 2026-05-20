# Implementation Plan

## 1. Feature Overview
Fix the mock target API HITL packaging blocker by making Serverless Framework tooling deterministic for `apps/mock-target-api`.

## 2. Technical Scope
Add app-local npm tooling for Serverless Framework v3, expose package/deploy/invoke scripts that use the local binary, and update documentation to avoid reliance on globally installed Serverless v4.

## 3. Source Inputs
- `docs/architecture/layer_1_validation_target_api_technical_design.md`
- `docs/bugs/mock_target_api_serverless_package_bug_report.md`
- Existing repository convention in `infra/package.json`

## 4. API Contracts Affected
No API contract changes.

## 5. Data Models / Storage Affected
No data model or storage changes.

## 6. Files Expected to Change
- `apps/mock-target-api/package.json`
- `apps/mock-target-api/package-lock.json`
- `apps/mock-target-api/serverless.yml`
- `apps/mock-target-api/README.md`
- `docs/backend/mock_target_api_serverless_tooling_implementation_report.md`

## 7. Security / Authorization Considerations
No runtime authentication or authorization changes. The fix only affects local packaging and deployment tooling. Documentation will keep deployment guidance scoped to users with appropriate AWS/environment access.

## 8. Dependencies / Constraints
- Add `serverless` as an app-local dev dependency matching the repository Serverless v3 convention: `^3.38.0`.
- Do not introduce plugins, infrastructure resources, runtime dependencies, or Serverless v4 behavior.
- Preserve Python 3.11 Lambda runtime and existing routes.

## 9. Assumptions
- A local npm package in `apps/mock-target-api` is acceptable because the app previously had no local JavaScript tooling and the repository already uses npm/Serverless v3 for infrastructure packaging.
- `npm run package -- --stage dev` is the supported deterministic replacement for direct global `serverless package --stage dev`.

## 10. Validation Plan
- From `apps/mock-target-api`: `npm install`
- From `apps/mock-target-api`: `npm run package -- --stage dev`
- From repository root: `python -m pytest apps/mock-target-api/tests/unit apps/mock-target-api/tests/integration`
- From repository root: `python -m compileall apps/mock-target-api`
- From `apps/mock-target-api`: direct global `serverless package --stage dev` to confirm whether it remains unsupported in this environment.
