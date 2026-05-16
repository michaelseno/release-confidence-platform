# Test Plan

## 1. Feature Overview

Phase 0 validates the repository, tooling, documentation, local mock API strategy, and Serverless packaging foundation for the Release Confidence Platform on branch `feature/phase_0_project_foundation`.

QA validation is limited to local evidence collection and package validation. No live AWS deployment, cloud resource creation, or runtime audit execution is in scope.

Primary upstream artifacts:

- Product spec: `docs/product/phase_0_project_foundation_product_spec.md`
- Technical design: `docs/architecture/phase_0_project_foundation_technical_design.md`

## 2. Acceptance Criteria Mapping

| Acceptance Criterion | Requirement Coverage | Validation Approach | Evidence Expected |
| --- | --- | --- | --- |
| AC-001 Monorepo Structure Exists | FR-001 | Inspect repository tree for backend, frontend placeholder, infrastructure, scripts or documented commands, tests, and docs. | Directory listing or file inventory showing required locations. |
| AC-002 Phase 0 README Is Complete | FR-002 | Review root `README.md` for purpose, Phase 0 scope, non-goals, setup, validation commands, stages, and no-AWS-deployment constraint. | README checklist result with missing/present items. |
| AC-003 Python 3.11 and `pyproject.toml` Are Defined | FR-003 | Inspect `pyproject.toml` and documented setup for Python 3.11 target. Run `python --version` where environment is available. | `python --version` output and `pyproject.toml` excerpts/check result. |
| AC-004 Required Python Tooling Is Included | FR-003 | Inspect dependency/tooling configuration or documentation for `pytest`, `ruff`, `boto3`, and `requests`. | Dependency checklist result. |
| AC-005 Linting Validation Is Available | FR-004 | Execute documented lint command. Expected command: `python -m ruff check .`. | Full command output and exit code. |
| AC-006 Formatting Validation Is Available | FR-004 | Execute documented formatting check. Expected command: `python -m ruff format --check .`. | Full command output and exit code. |
| AC-007 Unit Test Validation Is Available | FR-004 | Execute documented unit test command. Expected command: `python -m pytest`. | Pytest output and summary. |
| AC-008 Serverless Stages Are Configured | FR-005 | Inspect `infra/serverless.yml` for explicit or constrained support of `dev`, `staging`, and `prod`. | Stage configuration excerpt/check result. |
| AC-009 Local Serverless Packaging Works | FR-006 | Run package validation without deployment. Expected command from `infra/`: `serverless package --stage dev`, or documented root equivalent. | Serverless package output, generated package/template presence, and exit code. |
| AC-010 No Real AWS Deployment Is Required | FR-006 | Confirm validation commands do not run `deploy`, do not require live AWS credentials, and do not create/mutate cloud resources. | Command list review and package logs showing local-only behavior. |
| AC-011 Resource Naming Convention Is Documented | FR-007 | Inspect docs and infrastructure resource files for exact patterns `release-confidence-platform-${stage}-raw-results` and `release-confidence-platform-${stage}-metadata`. | Naming checklist and file references. |
| AC-012 Environment Variable Conventions Are Documented | FR-008 | Review documentation for stage-aware uppercase `SNAKE_CASE` variables across local, `dev`, `staging`, and `prod`. | Documentation checklist result. |
| AC-013 Foundational Documentation Exists | FR-009 | Verify required docs exist and contain architecture, lifecycle, raw evidence, operational philosophy, coding, structured logging, naming, schema versioning, and folder ownership standards. | Documentation inventory and checklist. |
| AC-014 Mandatory Identifiers Are Documented | FR-010 | Inspect standards/docs for `client_id`, `audit_id`, `run_id`, `endpoint_id`, `scenario_id`, and `raw_result_version`. | Identifier checklist result. |
| AC-015 Frontend Is Placeholder Only | FR-011 | Inspect `apps/frontend` and confirm only `README.md` exists and no frontend framework/dashboard/build pipeline is present. | Directory listing and scope review result. |
| AC-016 Phase Boundary Is Maintained | Phase boundary | Search/review for out-of-scope implementation: auth, RBAC, billing, subscriptions, onboarding, AI, advanced observability, load testing, uptime monitoring clone behavior, chaos engineering, heavy API framework, runtime audit execution, or real AWS deployment. | Scope-boundary review notes and any findings. |
| FR-012 Local QA Mock API Expectation | Local QA strategy | Verify documentation or test directory strategy identifies local mock APIs as the expected QA strategy for later validation scaffolding without requiring production mock infrastructure. | Documentation or `tests/mock_api` inventory/check result. |

## 3. Test Scenarios

### Functional Foundation Scenarios

1. **Repository structure validation**
   - Purpose: Confirm Phase 0 monorepo ownership boundaries exist.
   - Input: Repository tree on `feature/phase_0_project_foundation`.
   - Expected output: Required application, package, infra, config, scripts/documented-command, tests, and docs locations are present.
   - Validation logic: Compare actual tree to product spec and technical design required locations.

2. **README and documentation completeness validation**
   - Purpose: Confirm developer/operator onboarding and Phase 0 boundaries are documented.
   - Input: Root `README.md` and required docs under `docs/`.
   - Expected output: All required topics are present and future-only behavior is clearly labeled.
   - Validation logic: Apply documentation checklist in Section 6.

3. **Python tooling validation**
   - Purpose: Confirm Python 3.11, dependency management, linting, formatting, and test standards are operational.
   - Input: `pyproject.toml`, installed local dependencies, source/test files.
   - Expected output: Python target is 3.11; `pytest`, `ruff`, `boto3`, and `requests` are configured or documented; lint, format, and unit tests pass.
   - Validation logic: Inspect configuration and execute required commands.

4. **Serverless packaging validation**
   - Purpose: Confirm infrastructure packages locally without deployment.
   - Input: `infra/serverless.yml` and resource fragments.
   - Expected output: `dev` packaging succeeds without live AWS deployment or credential dependency.
   - Validation logic: Execute package command and review logs/artifacts.

5. **Stage support validation**
   - Purpose: Confirm `dev`, `staging`, and `prod` are supported stages.
   - Input: Serverless configuration and documented stage conventions.
   - Expected output: Stage values resolve deterministically and resource names remain stage-aware for each stage.
   - Validation logic: Inspect config and run/package or print-stage commands where feasible as defined in Section 5.

6. **Local mock API strategy validation**
   - Purpose: Confirm Phase 0 documents local mock APIs as QA strategy without requiring live services.
   - Input: Documentation and `tests/mock_api` location if implemented.
   - Expected output: Local mock API expectation is present and production-grade mock service is not required.
   - Validation logic: Documentation/directory inspection only unless implementation intentionally includes a local fixture.

### Negative and Boundary Scenarios

1. **AWS deployment boundary**: Any required validation that invokes `serverless deploy`, requires AWS credentials, or creates/mutates cloud resources is a blocking failure.
2. **Out-of-scope feature boundary**: Implemented auth, RBAC, billing, AI, frontend UI, advanced observability, runtime audit execution, heavy API frameworks, load testing, chaos engineering, or uptime-monitor clone behavior is a blocking scope violation.
3. **Frontend boundary**: Anything beyond `apps/frontend/README.md` in the frontend area must be escalated unless explicitly justified as documentation-only and accepted by product.
4. **Stage ambiguity**: Implicit-only stage support, missing `staging`/`prod`, or resource names without `${stage}` fails stage validation.
5. **Secret hygiene**: Real credentials, tokens, cookies, authorization headers, or sensitive payloads in docs/config/samples/log examples are blocking security findings.

## 4. Edge Cases

- `serverless package --stage dev` attempts to resolve live AWS account, SSM, Secrets Manager, or other credential-dependent values.
- `staging` or `prod` packages fail while `dev` passes because resource names or variables are hard-coded.
- Resource names omit stage or use inconsistent prefixes/casing.
- Mandatory identifiers are partially listed, renamed, or documented as optional without rationale.
- Documentation describes later-phase behavior without explicitly marking it as future/not implemented.
- Placeholder backend code performs network calls, AWS SDK calls, or audit-like runtime behavior.
- Sample configs/log examples contain plausible real secrets or sensitive customer payloads.
- Hyphenated repository folders are treated as importable Python packages without an import-safe strategy.

## 5. Test Types Covered

### Test Strategy and Test Types

- **Static repository inspection:** Validate structure, naming, phase boundaries, frontend placeholder-only scope, and required docs.
- **Configuration inspection:** Validate `pyproject.toml`, `.gitignore`, Serverless YAML, resource fragments, and environment variable conventions.
- **Command-based local validation:** Execute lint, formatting, unit tests, and Serverless package commands.
- **Serverless package validation:** Generate local package artifacts for `dev`; validate `staging` and `prod` using package or config-resolution commands where feasible without deployment.
- **Security/sanitization review:** Inspect samples, docs, logging standards, and placeholders for secret hygiene and non-sensitive structured logging expectations.
- **Regression protection:** Confirm foundational standards and out-of-scope boundaries remain unchanged while validating Phase 0 deliverables.

### Required Validation Commands

Run from repository root unless otherwise specified. Equivalent documented commands are acceptable if they perform the same validation.

```bash
git branch --show-current
python --version
python -m ruff check .
python -m ruff format --check .
python -m pytest
cd infra && serverless package --stage dev
```

Root-level Serverless equivalent, if documented:

```bash
serverless package --config infra/serverless.yml --stage dev
```

Optional/non-blocking diagnostic commands for stage resolution where supported by the installed Serverless version and repository configuration:

```bash
cd infra && serverless package --stage staging
cd infra && serverless package --stage prod
```

If packaging `staging` or `prod` requires deployment credentials or cloud resource mutation, stop and classify as an application/configuration failure against Phase 0 boundaries.

### Stage Validation Strategy for `dev`, `staging`, and `prod`

- **`dev` stage:** Mandatory package validation. `serverless package --stage dev` must pass locally without AWS deployment or cloud resource creation.
- **`staging` stage:** Validate by configuration inspection and, where feasible, local `serverless package --stage staging`. Confirm stage-aware resource names resolve to staging-specific names and no live AWS dependency is introduced.
- **`prod` stage:** Validate by configuration inspection and, where feasible, local `serverless package --stage prod`. Confirm production stage is supported without requiring actual deployment.
- **All stages:** Confirm exact resource naming patterns remain stage-aware:
  - `release-confidence-platform-${stage}-raw-results`
  - `release-confidence-platform-${stage}-metadata`
- **Failure rule:** Stage validation fails if a stage is undocumented, implicitly unsupported, hard-coded to `dev`, or dependent on deployed AWS resources during packaging.

## 6. Coverage Justification

The plan covers all Phase 0 acceptance criteria and the confirmed QA scope by combining file/system inspection with executable local validation. It intentionally excludes live AWS deployment, frontend functional testing, runtime audit behavior, authentication, billing, AI, performance/load testing, and production readiness certification because those items are explicitly out of scope for Phase 0.

### Documentation Validation Checklist

- Root `README.md` includes:
  - Platform purpose.
  - Phase 0 scope.
  - Explicit non-goals/out-of-scope items.
  - Local setup expectations.
  - Validation commands for lint, format, unit tests, and Serverless packaging.
  - Stage naming expectations for `dev`, `staging`, and `prod`.
  - No-real-AWS-deployment constraint.
- Required documentation exists and is findable for:
  - Architecture overview.
  - Execution lifecycle.
  - Raw evidence handling/model expectations.
  - Operational philosophy.
  - Coding standards.
  - Linting and formatting standards.
  - Unit testing standards.
  - Structured logging standards.
  - Naming standards.
  - Schema versioning standards.
  - Folder ownership standards.
- Mandatory identifiers are documented exactly:
  - `client_id`
  - `audit_id`
  - `run_id`
  - `endpoint_id`
  - `scenario_id`
  - `raw_result_version`
- Local mock API expectation is documented as a QA strategy for later scaffolding.
- Future behavior is clearly labeled as future/not implemented.

### Security, Sanitization, and Logging Checklist

- No real secrets, credentials, access keys, tokens, cookies, authorization headers, or sensitive payloads are committed in docs, samples, config, code, or logs.
- Sample configuration values are fake and safe to commit.
- Structured logging standard requires JSON-compatible fields and stable names such as `level`, `message`, `service`, `stage`, and `event_type`.
- Logging standard prohibits secrets, credentials, tokens, cookies, authorization headers, and sensitive request/response payloads.
- Correlation identifiers align with required identifiers where applicable.
- Domain/application fields use `snake_case`; environment variables use uppercase `SNAKE_CASE`; resource names use lowercase hyphenated stage-aware names.
- Sanitization boundary is documented for future implementation; no claim of full runtime sanitization is made in Phase 0 unless tests/code prove it.
- Placeholder AWS/storage clients do not execute live AWS calls during Phase 0 validation.

### Expected Evidence to Collect in QA Report

- Current branch output from `git branch --show-current`.
- Environment output from `python --version`.
- Full lint command output and exit code.
- Full formatting check output and exit code.
- Full unit test output and exit code.
- Full Serverless package output for `dev` and generated local package artifact location if available.
- Stage validation evidence for `staging` and `prod`: package outputs if feasible, otherwise configuration inspection notes with file references.
- Repository structure inventory showing required directories/files.
- README and documentation checklist results.
- Resource naming and environment variable convention evidence.
- Frontend placeholder-only evidence.
- Local mock API strategy evidence.
- Security/sanitization/logging checklist results.
- Failure classifications for any failed command, missing artifact, scope violation, or environment limitation.

### Sign-Off Criteria

QA sign-off for Phase 0 may be approved only if:

- All critical acceptance criteria AC-001 through AC-016 pass.
- Required local validation commands pass or documented equivalents pass.
- `dev` Serverless package validation succeeds locally without AWS deployment or resource mutation.
- `dev`, `staging`, and `prod` stage support is proven through package validation where feasible and configuration inspection at minimum.
- Documentation foundation is complete and consistent with Phase 0 boundaries.
- Resource naming and mandatory identifiers match the product spec exactly.
- Security, sanitization, and structured logging standards are documented and contain no secret/sensitive-data violations.
- Frontend remains placeholder-only.
- No later-phase functionality or heavy framework scope creep is present.
- All evidence is captured in `docs/qa/phase_0_project_foundation_test_report.md` during execution.

If any blocking defect, unresolved failed command, major regression, AWS deployment dependency, or scope violation is found, QA must not approve and must classify/escalate the failure in the test report.
