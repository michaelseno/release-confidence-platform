# Bug Report

## 1. Summary

HITL validation is blocked because Serverless packaging for the mock target API fails immediately with `No version found for 3` when run from `apps/mock-target-api`.

## 2. Investigation Context

- Source of report: Manual HITL validation blocker.
- Branch context: existing branch `feature/layer_1_validation_target_api`; no branch changes made.
- Related feature/workflow: backend-only/internal Layer 1 mock target API packaging and deployment fixture.
- Reproduction command: `serverless package --stage dev` from `apps/mock-target-api`.
- Expected runtime/deployment target: AWS Lambda Python 3.11 via Serverless Framework and API Gateway HTTP API.

## 3. Observed Symptoms

- Failing workflow: Serverless packaging for `apps/mock-target-api`.
- Reproduced command:
  ```bash
  pwd && serverless package --stage dev
  ```
- Reproduced output:
  ```text
  /Users/mjseno/Documents/Development/2026_fortfolio_projects/release-confidence-platform/apps/mock-target-api
  No version found for 3
  ```
- Additional CLI evidence from repository root:
  ```text
  Serverless ϟ Framework 4.36.1
  ```
- Installed executable paths:
  ```text
  /Users/mjseno/.nvm/versions/node/v22.11.0/bin/serverless
  /Users/mjseno/.nvm/versions/node/v22.11.0/bin/sls
  ```
- Observed behavior: packaging exits before producing a package artifact or validating the service.
- Expected behavior: `serverless package --stage dev` should package the Python 3.11 HTTP API Lambda service successfully, or the app should provide a deterministic documented command/tooling path that uses the supported Serverless version.

## 4. Evidence Collected

- `apps/mock-target-api/serverless.yml`:
  - line 1: `service: mock-target-api`
  - line 3: `frameworkVersion: "3"`
  - line 7: `runtime: python3.11`
  - lines 17-52: five HTTP API Lambda functions are configured.
- `apps/mock-target-api/package.json`: not present.
- `infra/package.json`:
  - line 7: repository infrastructure dev dependency pins Serverless with `"serverless": "^3.38.0"`.
  - lines 10-12: package scripts use `serverless package --stage ...` for the infra app only.
- `infra/package-lock.json`: not present.
- `infra/node_modules/.bin/serverless`: not present.
- `apps/mock-target-api/README.md`:
  - lines 31-39 document direct `sls deploy --stage dev|staging|prod` from `apps/mock-target-api`.
  - no local package manager setup or Serverless version bootstrap is documented for this app.
- `docs/architecture/layer_1_validation_target_api_technical_design.md`:
  - line 614 recommends `frameworkVersion` be pinned to the repository-supported Serverless version if a project standard exists.
  - line 632 says deploy from `apps/mock-target-api/` with `sls deploy --stage dev|staging|prod`.

## 5. Execution Path / Failure Trace

1. Validator runs `serverless package --stage dev` inside `apps/mock-target-api`.
2. The shell resolves `serverless` to the globally installed Serverless Framework v4.36.1 executable.
3. Serverless reads `apps/mock-target-api/serverless.yml` and encounters `frameworkVersion: "3"`.
4. The v4 launcher/config version resolver attempts to resolve framework version `3` and fails with `No version found for 3` before normal packaging begins.
5. Because `apps/mock-target-api` has no local `package.json`/local Serverless dev dependency or documented `npx/serverless@3` command, the packaging workflow depends on whichever global Serverless version is installed.

## 6. Failure Classification

- Primary classification: Environment / Configuration Issue.
- Severity: Blocker.
- Severity justification: this prevents HITL validation from packaging/deploying the backend fixture, blocking validation of the implemented mock target API.
- Reproducibility: Always reproducible in the current environment with the provided command.

## 7. Root Cause Analysis

- Confidence label: Most Likely Root Cause.
- Immediate failure point: Serverless CLI version resolution fails on `frameworkVersion: "3"` before package generation.
- Underlying root cause: `apps/mock-target-api` declares a major-only Serverless Framework version (`"3"`) but does not provide local Serverless tooling for that app. In the validation environment, the direct `serverless` command resolves to global Serverless Framework v4.36.1, which fails resolving the configured `3` framework version.
- Supporting evidence:
  - Failure reproduced with exact command from `apps/mock-target-api`: `No version found for 3`.
  - `serverless --version` outside the service reports `Serverless ϟ Framework 4.36.1`.
  - `apps/mock-target-api/serverless.yml` line 3 uses `frameworkVersion: "3"`.
  - `apps/mock-target-api/package.json` is absent, so there is no app-local Serverless dependency or scripts to force Serverless v3.
  - Repository infra app references Serverless v3 via `infra/package.json`, but that dependency is not installed and is scoped to `infra`, not `apps/mock-target-api`.
- Plausible contributing factor: README deployment instructions call `sls deploy` directly, which makes the fixture sensitive to global CLI version differences.

## 8. Confidence Level

High. The failure was reproduced exactly, the installed CLI version was identified as v4.36.1, and the app configuration contains the `frameworkVersion: "3"` value named in the error. Full confirmation would require validating the developer's chosen fix path with a compatible Serverless v3 local install or a corrected version constraint.

## 9. Recommended Fix

- Likely owner: backend / dev-backend.
- Affected file/module:
  - `apps/mock-target-api/serverless.yml`
  - deployment/package tooling and docs for `apps/mock-target-api` (`package.json` if added, README deployment section)
- Recommended correction:
  1. Make the mock target API packaging command deterministic by adding app-local Serverless tooling for the supported framework version, preferably matching the existing repo standard (`serverless` `^3.38.0`) under `apps/mock-target-api`, with package scripts such as `package:dev`, `package:staging`, and `package:prod`.
  2. Update documentation to instruct validators to run the local/scripted command rather than relying on a global `serverless`/`sls` binary.
  3. Consider replacing the major-only `frameworkVersion: "3"` with an explicit repository-supported Serverless v3-compatible constraint if required by the selected tooling path.
- Cautions/constraints:
  - Do not change the Lambda runtime from `python3.11`.
  - Do not introduce unrelated Serverless plugins or infrastructure resources.
  - Avoid making HITL validation dependent on Serverless Framework v4 unless the project intentionally accepts v4 behavior and requirements.

## 10. Suggested Validation Steps

After the fix:

1. From `apps/mock-target-api`, install/use only the project-local documented tooling path.
2. Run the corrected package command for dev, e.g. `npm run package:dev` or the documented equivalent.
3. Verify package generation succeeds and creates a `.serverless/` package artifact for `mock-target-api`.
4. Run stage smoke checks if supported:
   - package dev
   - package staging
   - package prod
5. Re-run existing Python validation:
   - `./.venv/bin/python -m pytest apps/mock-target-api/tests/unit apps/mock-target-api/tests/integration`
   - `./.venv/bin/python -m compileall apps/mock-target-api`
6. Confirm `serverless.yml` still declares `provider.runtime: python3.11` and all five HTTP API GET routes.

## 11. Open Questions / Missing Evidence

- The project-standard Serverless invocation path for app-level fixtures is not fully defined. Existing `infra/package.json` suggests Serverless v3.38.x is used for infra, but `apps/mock-target-api` does not currently inherit that tooling.
- No package lock or installed local Serverless v3 binary was present, so I did not validate a v3 package run locally.

## 12. Final Investigator Decision

Ready for developer fix.
