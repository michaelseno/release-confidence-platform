# GitHub Issue

## 1. Feature Name

`rcp config init` local starter runtime configuration generation

## 2. Problem Summary

Operators currently need to hand-author audit runtime configuration files before validation and onboarding. Manual setup increases the risk of invalid schema fields, inconsistent directory structure, unsafe production defaults, embedded secrets, accidental AWS dependencies, and onboarding delays.

This feature adds a local-only operator CLI command, `rcp config init`, that generates a schema-aligned starter config set with safe IDs, conservative defaults, overwrite protection, optional sample endpoints, and text or JSON operator output.

## 3. Linked Planning Documents

- Product Spec: `docs/product/config_init_product_spec.md`
- Technical Design: `docs/architecture/config_init_technical_design.md`
- UI/UX Spec: not applicable
- QA Test Plan: `docs/qa/config_init_test_plan.md`

## 4. Scope Summary

### In scope

- Add `rcp config init` under the existing operator CLI `config` command group.
- Require `--client-name`, `--target-environment`, and `--output-dir`.
- Support optional `--timezone`, `--include-sample-endpoints`, `--overwrite`, and `--output json`.
- Generate local files under `<output-dir>/<client_id>/`:
  - `client_config.json`
  - `audits/<audit_id>/audit_config.json`
  - `audits/<audit_id>/endpoints.json`
- Auto-generate filesystem-safe `client_id` and `audit_id` values.
- Generate safe starter defaults aligned with validation schemas.
- Protect existing generated client roots from overwrite unless `--overwrite` is supplied.
- Include exactly one safe placeholder endpoint when sample endpoints are requested.
- Emit human-readable output by default and parseable JSON for `--output json`.
- Include git safety guidance recommending `.local-configs/` and `.gitignore` exclusion.
- Ensure generated files contain no secrets and the command never contacts AWS.

### Out of scope

- Uploading configs to S3 or other storage.
- Registering audits or writing DynamoDB metadata.
- Creating, updating, or deleting EventBridge schedules.
- Invoking Lambda, audit runners, orchestrators, smoke runs, or audit execution flows.
- Accessing AWS Secrets Manager or resolving secret values.
- Automatically modifying `.gitignore` or unrelated repository files.
- Dashboards, monitoring, status commands, log commands, customer-facing UI, or self-service onboarding.

## 5. Implementation Notes

### Frontend expectations

- No frontend or UI screen is expected.
- Operator interaction is CLI-only.
- CLI output must support readable text and machine-readable JSON.

### Backend expectations

- Implement in the src-layout runtime package under `src/release_confidence_platform/`.
- Add a thin CLI/service adapter for `config init` without requiring `--stage`.
- Keep generation logic pure and reusable where practical:
  - slug utilities
  - ID generation helpers
  - config dictionary generators
  - local config init service
- Validate generated configs in memory before writing files.
- Write stable, pretty JSON only after local validation and conflict checks pass.
- Do not instantiate `StageConfigLoader`, `AwsClientFactory`, boto3 clients, or storage/scheduler/secret clients.
- Preserve execution-time safety controls while allowing local-template validation for empty endpoints and production-oriented templates with production execution disabled.

### Dependencies or blockers

- Existing validation rules may need an explicit local-template mode so default empty endpoint arrays and production-oriented starter templates validate safely without weakening execution-time validation.
- Implementation must follow current `src/release_confidence_platform/` conventions rather than older compatibility-oriented package paths.
- No external service dependencies are expected or permitted.

## 6. QA Section

### Planned test coverage

- CLI parser and command dispatch tests.
- Unit tests for slug and ID generation.
- Filesystem tests for directory structure, overwrite protection, and explicit overwrite behavior.
- Generator content tests for required fields, safe defaults, and absence of secrets/AWS references.
- Validation compatibility tests for default, sample endpoint, prod, and production templates.
- Output rendering tests for text and JSON modes.
- No-AWS side-effect tests using monkeypatch/fail-fast guards.
- Regression tests proving existing stage-required CLI commands and execution-time safety remain unchanged.

### Acceptance criteria mapping

- AC-001 / AC-001A: required arguments create files under `<output-dir>/<client_id>/`.
- AC-002 / AC-003: generated IDs are present, safe, lowercase, and path-safe.
- AC-004 / AC-005: default empty endpoints and optional safe sample endpoint behave as specified.
- AC-006 / AC-006A: safe defaults and production-oriented local templates remain non-executable by default.
- AC-007: generated configs pass project validation in local-template mode.
- AC-008 / AC-009: overwrite protection and explicit overwrite behavior are enforced.
- AC-010: command never touches AWS, stage loaders, or network clients.
- AC-011: JSON output is parseable, complete, and free of stray text/secrets.
- AC-012: git safety warning is emitted without automatic `.gitignore` mutation.

### Key edge cases

- Client names containing unsafe characters, traversal sequences, shell metacharacters, unicode punctuation, or names that slugify to empty.
- Existing final generated client root with and without `--overwrite`.
- `--output-dir` pointing to an existing file.
- Invalid or unsupported target environments and invalid timezones.
- `prod` / `production` target environments with and without sample endpoints.
- Partial local write failures must not report success.
- JSON error output for local failures must remain parseable and sanitized.

### Test types expected

- Unit tests.
- CLI/API contract tests.
- Filesystem integration-style tests using temporary directories.
- Validation contract tests.
- Security/safety boundary tests for no secrets, no AWS calls, and no unexpected repository mutation.
- Regression tests for existing CLI and scheduling/lifecycle behavior.

## 7. Risks / Open Questions

- Validation changes for local-template mode may unintentionally weaken execution-time validation if not isolated carefully.
- Overwrite behavior must be constrained to expected generated files and must not delete or mutate unrelated files.
- ID generation must balance operator-readable slugs with collision resistance and filesystem safety.
- JSON output must remain machine-readable even for local failure paths.
- Open question: exact timezone validation dependency or approach should align with repository standards and supported Python version.

## 8. Definition of Done

- `rcp config init` is available from the operator CLI with documented required and optional arguments.
- Generated directory structure and files match the product spec and technical design.
- Generated `client_id` and `audit_id` are safe, lowercase, and included in output and generated configs.
- Generated configs validate locally by default and contain no secrets or AWS resource references.
- Existing generated roots are protected unless `--overwrite` is supplied.
- Optional sample endpoint mode creates exactly one safe placeholder endpoint.
- Text and JSON outputs include IDs, generated root, generated file paths, overwrite status, and git safety warning.
- No AWS/stage loader/client construction occurs on success or local failure paths.
- Planned QA coverage is implemented and passing.
- Existing CLI, validation, scheduling, and lifecycle behavior are not regressed.
