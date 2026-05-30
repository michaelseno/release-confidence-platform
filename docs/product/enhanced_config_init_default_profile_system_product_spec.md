# Product Specification

## 1. Feature Overview

Enhance `rcp config init` from a hardcoded starter-config generator into a reusable, profile-driven configuration initialization system.

The command will load environment-specific defaults from default profile JSON files, merge those defaults with operator inputs and explicit CLI overrides, generate safe local configuration workspaces, and produce validation-safe starter configs for a client and audit.

This feature is the final operator bootstrap workflow before full platform testing and Phase 4 validation. It remains a local-only generation workflow and must not contact AWS or perform runtime onboarding actions.

## 2. Problem Statement

`rcp config init` currently depends on CLI-side hardcoded defaults for environment-specific initialization behavior. Hardcoded defaults make operator onboarding less flexible, increase maintenance risk, and make it harder to keep dev, staging, and production starter configs consistent and safe.

Operators need a fast, repeatable way to initialize local configs using centralized defaults while preserving deterministic overrides for workspace path, timezone, and output format. The generated configs must be safe to validate and review before any upload, registration, schedule creation, Lambda invocation, or production execution is possible.

## 3. User Persona / Target User

- **Technical operator:** Initializes local client and audit config workspaces before validation and onboarding.
- **Platform engineer:** Maintains reusable defaults profiles, config schemas, validation behavior, and CLI implementation.
- **QA engineer:** Verifies profile resolution, generated config validity, safety guarantees, and no-AWS side effects.

## 4. User Stories

- As a technical operator, I want to run `rcp config init --client-name "Acme"` so that I can quickly create a safe dev starter workspace with minimal input.
- As a technical operator, I want to select a named defaults profile so that generated configs match the intended target environment.
- As a technical operator, I want to provide a custom defaults JSON file so that specialized onboarding scenarios can reuse the same initialization workflow.
- As a technical operator, I want CLI overrides for output directory, timezone, and output format so that I can control deterministic run behavior without editing profiles.
- As a platform engineer, I want environment defaults centralized in profile files so that defaults can be maintained without changing CLI parsing logic.
- As a QA engineer, I want generated files to be schema-valid, validation-safe, isolated by client workspace, and guaranteed not to call AWS.

## 5. Goals / Success Criteria

- Operators can initialize configs with minimal arguments using the implicit `dev` profile.
- Operators can initialize configs with named profiles `dev`, `staging`, and `prod`.
- Operators can initialize configs with an explicit defaults JSON file path.
- Environment-specific initialization defaults are loaded from reusable profile files instead of being hardcoded in CLI logic.
- Explicit CLI arguments override profile values, and hardcoded safe fallbacks are used only for unresolved required values.
- Generated configs are schema-valid and pass audit validation by default.
- Generated workspaces use the required isolated directory structure under `.local-configs/<client_id>/` by default.
- Generated configs contain no secrets, credentials, tokens, real production endpoints, AWS resource actions, or unsafe execution settings.
- Existing target directories are protected unless `--overwrite` is supplied.
- Tests cover profile resolution/loading, explicit file path defaults, generated config validity, overwrite protection, directory structure, and absence of AWS calls.

## 6. Feature Scope

### In Scope

- Enhance existing `rcp config init` command behavior to use defaults profiles.
- Required CLI argument:
  - `--client-name <name>`
- Optional CLI arguments:
  - `--defaults <name-or-path>`, default `dev`
  - `--output-dir <path>`
  - `--timezone <iana-timezone>`
  - `--include-sample-endpoints`
  - `--overwrite`
  - `--output <format>`
- Add `operator_defaults` support to defaults profiles.
- Support named defaults profile resolution for `dev`, `staging`, and `prod`.
- Support explicit defaults JSON file paths when the `--defaults` value contains path separators or ends with `.json`.
- Generate `client_id` and `audit_id` values using validation-compatible safe formats.
- Generate local files:
  - `.local-configs/<client_id>/client_config.json`
  - `.local-configs/<client_id>/audits/<audit_id>/audit_config.json`
  - `.local-configs/<client_id>/audits/<audit_id>/endpoints.json`
- Create or align default profile files:
  - `config/defaults/dev.json`
  - `config/defaults/staging.json`
  - `config/defaults/prod.json`
- Validate profile existence, JSON syntax, required profile fields, generated config schemas, and audit validation compatibility before reporting success.
- Generate empty endpoint arrays by default.
- Generate only safe mock sample endpoints when `--include-sample-endpoints` is supplied.
- Preserve local-only behavior with no AWS access.

### Out of Scope

- Uploading configs to S3 or any other remote storage.
- Audit registration or metadata creation.
- Lambda invocation.
- Schedule creation, update, deletion, or activation.
- Dashboards, runtime monitoring, status views, or log views.
- Config editing workflows after generation.
- Live AWS integration of any kind.
- Production execution approval workflows.
- Automatic migration of existing hand-authored configs.

### Future Considerations

- Additional named profiles beyond `dev`, `staging`, and `prod`.
- Interactive profile selection.
- Profile schema version migrations.
- Config upload or audit registration commands that consume generated local configs.

## 7. Functional Requirements

### FR-001: CLI Contract

`rcp config init` must require `--client-name` and support optional `--defaults`, `--output-dir`, `--timezone`, `--include-sample-endpoints`, `--overwrite`, and `--output` arguments.

The command must support these user-facing examples:

```bash
rcp config init --client-name "Acme"
rcp config init --client-name "Acme" --defaults staging
rcp config init --client-name "Enterprise Client" --defaults config/defaults/high-volume-staging.json
rcp config init --client-name "Acme" --defaults staging --output-dir ./tmp-configs --timezone Asia/Hong_Kong --output json
```

### FR-002: Defaults Profile Resolution

If `--defaults` is omitted, the command must use the `dev` defaults profile.

If `--defaults` is `dev`, `staging`, or `prod`, the command must load the corresponding default JSON profile.

If the `--defaults` value contains a path separator or ends with `.json`, the command must treat it as an explicit file path.

If the resolved profile file does not exist, is not valid JSON, or does not contain required fields, the command must fail before generating files.

### FR-003: Profile Content

Default profiles must contain, at minimum:

- `profile_name`
- `target_environment`
- `operator_defaults`
- timezone defaults
- request defaults
- rate/concurrency defaults
- payload safety defaults
- schedule defaults for baseline, burst, repeated, and finalization behavior
- retention or lifecycle defaults required by validation

The technical design may place profiles in a repo-appropriate package path only if the logical profile set remains discoverable and equivalent to `config/defaults/dev.json`, `config/defaults/staging.json`, and `config/defaults/prod.json`.

### FR-004: Merge and Precedence Rules

The command must finalize generation inputs using this hierarchy:

1. Explicit CLI argument values.
2. Defaults profile values, including `operator_defaults`.
3. Hardcoded safe fallback values only when values remain unresolved.

The required processing flow is:

1. Load defaults profile.
2. Merge `operator_defaults`.
3. Apply explicit CLI overrides.
4. Apply hardcoded safe fallbacks only for still-missing values.
5. Generate and validate configs.

`--output-dir`, `--timezone`, and `--output` must remain deterministic operator overrides and must not be removed.

### FR-005: Directory Structure

The default generated workspace root must be `.local-configs/<client_id>/` when no output directory is explicitly supplied or provided by profile defaults.

Generated files must use this exact structure under the finalized output root:

```text
.local-configs/<client_id>/client_config.json
.local-configs/<client_id>/audits/<audit_id>/audit_config.json
.local-configs/<client_id>/audits/<audit_id>/endpoints.json
```

The command must not generate `.local-configs/client_config.json`.

### FR-006: Generated IDs

The command must generate IDs in these formats:

- `client_id`: `client_<slug>_<shortid>`
- `audit_id`: `audit_<YYYYMMDD>_<shortid>`

IDs must be lowercase, use safe characters only, contain no whitespace, contain no path separators, and be compatible with existing validation rules.

### FR-007: `client_config.json` Generation

`client_config.json` must merge generated IDs, operator input, and profile defaults.

It must not contain secrets, credentials, API tokens, passwords, cookies, private keys, or real secret values. Secret-bearing fields, if required by schema, must use placeholders or references only.

### FR-008: `audit_config.json` Generation

`audit_config.json` must include the generated `audit_id`, generated `client_id`, audit window placeholder values, timezone, and schedule defaults from the loaded profile.

It must include baseline, burst, repeated, and finalization schedule data in validation-compatible form.

It must not create active runtime schedules or imply that any schedule has been registered in AWS.

### FR-009: `endpoints.json` Generation

By default, `endpoints.json` must contain an empty endpoints array and any required validation metadata.

When `--include-sample-endpoints` is supplied, generated sample endpoints must be safe mock examples only. They must not include real customer endpoints, production hostnames, credentials, tokens, or destructive operations.

### FR-010: Production Handling

The command must allow the `prod` profile and production target environments.

For production-oriented generation, generated configs must:

- set `allow_production_execution=false`
- set `allow_destructive_operation=false`
- avoid real endpoints
- avoid aggressive concurrency
- avoid unsafe schedules

Later production execution must require separate explicit approval and validation outside this command.

### FR-011: Validation

Before reporting success, the command must validate:

- resolved profile exists
- profile JSON is syntactically valid
- profile contains required fields
- generated `client_config.json` is schema-valid
- generated `audit_config.json` is schema-valid
- generated `endpoints.json` is schema-valid
- generated configs pass audit validation rules

The command must not generate invalid starter configs as a successful outcome.

### FR-012: Overwrite Protection

If the target generated directory already exists, the command must fail before modifying files unless `--overwrite` is supplied.

When `--overwrite` is supplied, replacement behavior must be explicit in command output.

### FR-013: No AWS Interaction

The command must never access S3, DynamoDB, Secrets Manager, Lambda, EventBridge, or any AWS service.

The command must not create schedules, upload configs, invoke Lambdas, create metadata, resolve secrets, or require AWS credentials.

### FR-014: Command Output

Human-readable output must include generated IDs, generated workspace path, generated file paths, selected defaults profile, and a local-only safety indication.

When `--output json` is supplied, stdout must be valid JSON containing equivalent non-secret fields.

## 8. Acceptance Criteria

### AC-001: Minimal Dev Initialization

Given no `--defaults` argument and a valid `--client-name "Acme"`
When the operator runs `rcp config init --client-name "Acme"`
Then the command uses the `dev` defaults profile and generates a local workspace containing `client_config.json`, `audit_config.json`, and `endpoints.json`.

### AC-002: Named Profile Initialization

Given a valid named defaults profile `staging`
When the operator runs `rcp config init --client-name "Acme" --defaults staging`
Then the command loads the staging profile and generated configs use staging profile defaults unless explicitly overridden.

### AC-003: Explicit Defaults File Initialization

Given a valid defaults JSON file at `config/defaults/high-volume-staging.json`
When the operator runs `rcp config init --client-name "Enterprise Client" --defaults config/defaults/high-volume-staging.json`
Then the command treats the defaults value as a file path and generates configs using that file's profile values.

### AC-004: CLI Override Precedence

Given the staging defaults profile defines a timezone and output directory
When the operator runs `rcp config init --client-name "Acme" --defaults staging --output-dir ./tmp-configs --timezone Asia/Hong_Kong --output json`
Then the generated workspace uses `./tmp-configs`, generated configs use `Asia/Hong_Kong`, and command output is valid JSON.

### AC-005: Required Directory Structure

Given a generated `client_id` and `audit_id`
When `rcp config init` completes successfully
Then files exist at `.local-configs/<client_id>/client_config.json`, `.local-configs/<client_id>/audits/<audit_id>/audit_config.json`, and `.local-configs/<client_id>/audits/<audit_id>/endpoints.json`.

### AC-006: No Root-Level Client Config

Given a successful run using the default local workspace
When the generated files are inspected
Then `.local-configs/client_config.json` does not exist as an output of the command.

### AC-007: Generated ID Format

Given a valid client name containing spaces or uppercase characters
When `rcp config init` generates IDs
Then `client_id` matches `client_<slug>_<shortid>`, `audit_id` matches `audit_<YYYYMMDD>_<shortid>`, and both IDs are lowercase with safe characters only.

### AC-008: Invalid Profile Fails Safely

Given `--defaults` resolves to a missing file, invalid JSON file, or profile missing required fields
When the operator runs `rcp config init`
Then the command exits non-zero before writing generated config files.

### AC-009: Generated Config Validation

Given a successful `rcp config init` run
When the generated files are validated with project schema and audit validation rules
Then validation succeeds without AWS credentials or network access.

### AC-010: Empty Endpoints By Default

Given `--include-sample-endpoints` is omitted
When `endpoints.json` is generated
Then it contains an empty endpoints array and no secrets or real endpoint URLs.

### AC-011: Safe Sample Endpoints

Given `--include-sample-endpoints` is supplied
When `endpoints.json` is generated
Then it contains only safe mock example endpoints with no credentials, no tokens, no destructive operations, and no real production hostnames.

### AC-012: Production Profile Safety

Given the `prod` profile or a production target environment is used
When configs are generated
Then `allow_production_execution=false`, `allow_destructive_operation=false`, no real endpoints are generated, concurrency remains conservative, and unsafe schedules are not enabled.

### AC-013: Overwrite Protection

Given the target generated directory already exists
When the operator runs `rcp config init` without `--overwrite`
Then the command exits non-zero and does not modify existing files.

### AC-014: Explicit Overwrite

Given the target generated directory already exists
When the operator runs `rcp config init --overwrite`
Then the command may replace generated files and reports the overwritten target path.

### AC-015: No AWS Calls

Given AWS SDK client creation and AWS API methods are instrumented to fail if called
When `rcp config init` succeeds or fails due to local validation
Then no AWS client is constructed and no AWS API method is called.

### AC-016: Output Contains Operator Guidance

Given a successful run
When command output is inspected
Then it includes generated IDs, generated workspace path, generated file paths, selected defaults profile, and a local-only/no-upload safety message.

## 9. Edge Cases

- `--defaults` omitted must resolve to `dev`.
- `--defaults dev`, `--defaults staging`, and `--defaults prod` must resolve as named profiles, not relative paths.
- `--defaults ./dev.json`, `--defaults config/defaults/dev.json`, and other values containing path separators must resolve as explicit file paths.
- A `.json` defaults value without path separators must resolve as an explicit file path.
- Client names that slugify to an empty value must fail before writing files.
- Client names containing path separators or traversal sequences must not affect generated filesystem paths beyond the sanitized `client_id`.
- Invalid timezone overrides must fail before successful generation.
- Invalid output format values must fail before writing files.
- Partial write or validation failures must not report success.
- JSON output mode must remain parseable and must not print human-readable text outside the JSON payload.
- Generated production-oriented configs must remain safe even when sample endpoints are requested.

## 10. Constraints

- The command is local generation only.
- No AWS access, AWS credential dependency, Lambda invocation, schedule creation, metadata creation, or config upload is allowed.
- Defaults must be centralized in reusable profile files rather than hardcoded in CLI logic.
- Hardcoded values are allowed only as safe fallbacks after CLI and profile resolution.
- Generated configs must contain no secrets, credentials, tokens, private keys, or real secret values.
- Generated configs must be validation-safe and operationally conservative.
- Production-oriented generated configs must be non-executable by default.
- `--output-dir`, `--timezone`, and `--output` must remain supported deterministic operator overrides.

## 11. Dependencies

- Existing `rcp` CLI command framework.
- Existing `rcp config init` command behavior and tests.
- Config schema validation rules.
- Audit validation rules.
- ID validation and slug generation conventions.
- Local filesystem access.
- Repo-approved location for bundled default profile JSON files.

## 12. Assumptions

- The repo-approved defaults profile location will be `config/defaults/` unless technical design confirms a package-specific path with equivalent discoverability.
- `--output` supports at least the existing human-readable default and `json` output mode.

## 13. Open Questions

- Should default profile files have an explicit schema version field for future migrations?
- What exact JSON schema will validate `operator_defaults` independently from generated runtime configs?
