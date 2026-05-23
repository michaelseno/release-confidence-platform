# Product Specification

## 1. Feature Overview

Implement `rcp config init`, an internal operator CLI command that generates local starter runtime configuration files for a new audit. The command creates a schema-aligned directory structure, generates safe starter JSON files, and returns the generated `client_id` and `audit_id` to the operator.

This is an operator convenience feature only. It must never contact AWS, upload configs, register audits, invoke audit runners, create schedules, write metadata, or access secrets.

Example invocations:

```bash
rcp config init --client-name "Demo Client" --target-environment dev --output-dir .local-configs/demo-client
rcp config init --client-name "Acme Payments" --target-environment staging --timezone UTC --include-sample-endpoints --output-dir .local-configs/acme-payments
```

For every run, generated files must be placed under `<output-dir>/<client_id>/...`. For example, the first command above may create `.local-configs/demo-client/client_demo_client_a8f3c2/`. This avoids collisions, supports multiple generated clients under one operator workspace, aligns with architecture assumptions, and keeps future bulk onboarding/testing organized.

## 2. Problem Statement

Operators currently need to create audit configuration files manually before validation and onboarding. Manual authoring increases the risk of inconsistent directory structure, invalid schema fields, unsafe defaults, embedded secrets, production mistakes, and onboarding delays.

`rcp config init` reduces operator mistakes by generating standardized, validation-safe starter configs with conservative defaults and no AWS side effects.

## 3. User Persona / Target User

- **Technical operator / maintainer:** Creates local starter configs for a new audit before validation and onboarding.
- **Platform engineer:** Maintains config schemas, generators, validation logic, and CLI command behavior.
- **QA engineer:** Verifies generated templates are safe, deterministic in structure, schema-valid, and side-effect free.

## 4. User Stories

- As a technical operator, I want to generate starter audit configs locally so that I do not need to hand-author boilerplate JSON files.
- As a technical operator, I want generated IDs and directory paths so that I can immediately locate and validate the new audit config set.
- As a technical operator, I want safe defaults so that generated configs do not accidentally enable production or destructive behavior.
- As a QA engineer, I want generated configs to pass validation by default so that onboarding can proceed from templates without schema repair.
- As a platform engineer, I want generation logic separated from CLI parsing so that templates remain reusable and testable.

## 5. Goals / Success Criteria

The feature is successful when:

- Operators can run `rcp config init` with required arguments and receive a local config directory containing `client_config.json`, `audit_config.json`, and `endpoints.json`.
- The command auto-generates safe `client_id` and `audit_id` values and prints them in command output.
- Generated configs are valid under the project’s config validation rules without requiring AWS access.
- Generated configs contain no literal secrets, tokens, credentials, or secret values.
- Generated defaults are conservative and do not permit production execution or destructive operations.
- Existing output directories are protected by default and are overwritten only when `--overwrite` is supplied.
- Unit tests verify ID generation, overwrite protection, directory creation, schema validity, optional sample endpoint generation, and absence of AWS calls.

## 6. Feature Scope

### In Scope

- New CLI command: `rcp config init`.
- `--target-environment` values must support non-production environments and must also allow `prod` / `production` for production-oriented templates.
- Required arguments:
  - `--client-name <name>`
  - `--target-environment <environment>`
  - `--output-dir <path>`
- Optional arguments:
  - `--timezone <iana-or-utc>`, default `UTC`
  - `--include-sample-endpoints`
  - `--overwrite`
  - `--output json`
- Generation of:
  - `client_config.json`
  - `audit_config.json`
  - `endpoints.json`
- Auto-generation of `client_id` and `audit_id`.
- Creation of the required local directory structure.
- Safe starter defaults aligned with validation schemas and lifecycle assumptions.
- Human-readable command output and optional machine-readable JSON output.
- Git safety warning recommending `.local-configs/` and recommending that `.local-configs/` be added to `.gitignore`.
- Unit tests for generation and safety behavior.

### Out of Scope

- Uploading configs to S3 or any other storage service.
- Registering audits or writing DynamoDB metadata.
- Creating, updating, or deleting EventBridge schedules.
- Invoking Lambda, audit runners, orchestrators, or smoke runs.
- Accessing AWS Secrets Manager or resolving secret values.
- Mutating existing audits beyond optional local overwrite of generated files.
- Automatically modifying `.gitignore` or other repository files outside the generated config directory.
- Creating dashboards, runtime monitoring, status commands, or log commands.
- Customer-facing UI, API, or self-service onboarding.

### Future Considerations

- Additional template presets for common audit types.
- Interactive prompt mode.
- Config diff or migration helpers.

## 7. Functional Requirements

### FR-001: Command Structure

The system must provide `rcp config init` as an internal operator CLI command. The command must support the required and optional arguments listed in scope.

### FR-002: ID Generation

The command must generate:

- `client_id` format: `client_<slug>_<shortid>`
- `audit_id` format: `audit_<YYYYMMDD>_<shortid>`

IDs must be lowercase and must not contain whitespace, path traversal sequences, path separators, shell metacharacters, or unsafe characters. The slug must be derived from `--client-name` using safe characters only. `shortid` must be sufficient to avoid practical collisions for local template generation.

### FR-003: Directory Structure

The command must always create a generated client root directory under the operator-supplied output directory using the generated `client_id`:

```text
<output-dir>/<client_id>/
```

The command must write files to this structure:

```text
<output-dir>/<client_id>/client_config.json
<output-dir>/<client_id>/audits/<audit_id>/audit_config.json
<output-dir>/<client_id>/audits/<audit_id>/endpoints.json
```

Example generated root directory:

```text
.local-configs/demo-client/client_demo_client_a8f3c2/
```

The command must not treat `--output-dir` as the final generated client root. The final generated root directory is always `<output-dir>/<client_id>/`. The command output must clearly print this final generated root directory.

### FR-004: Overwrite Protection

If the final generated client root directory `<output-dir>/<client_id>/` already exists, the command must fail by default before writing or modifying files. The command may write into that existing generated client root only when `--overwrite` is supplied.

### FR-005: `client_config.json` Generation

`client_config.json` must include, at minimum:

- `client_id`
- `client_name`
- execution environment / target environment fields aligned with validation rules
- request defaults
- payload safety defaults
- allowed HTTP methods
- sanitization settings
- operational caps

Safe defaults must include:

- `allow_production_execution=false`
- `allow_destructive_operation=false`
- `max_concurrency=5`
- `timeout_seconds=10`

The file must not contain literal secrets, auth tokens, passwords, API keys, cookies, private keys, or credentials. Secret-bearing examples must use placeholders or references only.

### FR-006: `audit_config.json` Generation

`audit_config.json` must include, at minimum:

- `audit_id`
- `client_id`
- audit window placeholder with a maximum 48-hour duration
- `timezone`, defaulting to `UTC` when omitted
- `baseline_schedule`
- `burst_schedule`
- `repeated_schedule`
- `finalization_schedule`
- operational caps

Defaults must include:

- baseline schedule enabled
- baseline interval of 15 minutes
- burst schedule present but disabled or minimal by default
- repeated schedule enabled with `runs_per_day=1`
- conservative concurrency and request caps
- no active schedule timestamps tied to current runtime execution
- no AWS resource references

### FR-007: `endpoints.json` Generation

By default, `endpoints.json` must contain an empty `endpoints` array and required identifying metadata needed for validation consistency.

When `--include-sample-endpoints` is supplied, `endpoints.json` must include exactly one safe placeholder endpoint:

- method: `GET`
- URL: `https://example.com/health`
- target environment metadata aligned to `--target-environment`
- static payload strategy
- destructive flag set to `false`
- no authentication secrets

For `prod` / `production` target environments, the sample endpoint must still use only the safe placeholder URL `https://example.com/health`; it must not generate or infer a real production endpoint.

### FR-008: Validation Alignment

Generated files must be schema-valid and pass the project’s config validation rules by default. If current validation rules reject empty endpoint arrays, the implementation must resolve that mismatch explicitly so default generated templates remain validation-safe without requiring sample endpoints. Generated production-oriented templates must pass validation as safe local templates while keeping actual production execution disabled by default.

### FR-008A: Production-Oriented Template Safety

The command must allow `--target-environment prod` and `--target-environment production`. These values create production-oriented local templates only; they must not make generated configs executable against production by default.

For production-oriented templates, generated configs must:

- set `allow_production_execution=false`
- set `allow_destructive_operation=false`
- never generate production endpoint URLs or real production hostnames
- never generate real `auth_ref` values, credentials, tokens, API keys, cookies, passwords, or private keys
- never generate aggressive concurrency or request-volume defaults
- never auto-enable dangerous schedules
- pass validation safely as local templates without AWS access

If validation distinguishes between local template validation and execution approval, `rcp config init` output must satisfy local template validation while preserving later explicit approval controls for actual production execution.

### FR-009: No AWS Access

The command must not construct AWS clients, read AWS stage config for resource resolution, call AWS APIs, depend on AWS credentials, or require network access.

### FR-010: Command Output

Default output must be human-readable and include:

- generated `client_id`
- generated `audit_id`
- generated root directory
- paths of generated files
- git safety warning recommending `.local-configs/` and `.gitignore` exclusion

When `--output json` is supplied, output must be valid JSON containing the same key information and no secrets.

### FR-011: Recommended Internal Structure

Implementation may use the following structure, but exact paths may vary if consistent with existing project conventions:

- `packages/operator_cli/commands/config_init.py`
- `packages/config/generators/client_config_generator.py`
- `packages/config/generators/audit_config_generator.py`
- `packages/config/generators/endpoints_generator.py`
- `packages/core/id_generation.py`
- `packages/core/slug_utils.py`

## 8. Acceptance Criteria

### AC-001: Required Argument Generation

Given no existing final generated client root directory and valid `--client-name`, `--target-environment`, and `--output-dir` arguments
When the operator runs `rcp config init`
Then the command creates the config directory structure and writes `client_config.json`, `audit_config.json`, and `endpoints.json`.

### AC-001A: Output Directory Semantics

Given `--output-dir .local-configs/demo-client` and a generated `client_id` of `client_demo_client_a8f3c2`
When the operator runs `rcp config init`
Then the generated root directory is `.local-configs/demo-client/client_demo_client_a8f3c2/` and all generated files are written under that generated client root.

### AC-002: Generated IDs

Given a successful config init run
When the generated files and CLI output are inspected
Then the same generated `client_id` and `audit_id` appear consistently in applicable files and command output.

### AC-003: ID Safety

Given a client name containing spaces, uppercase letters, punctuation, or unsafe path characters
When the operator runs `rcp config init`
Then the generated `client_id` is lowercase, contains no whitespace or traversal characters, and matches `client_<slug>_<shortid>`.

### AC-004: Default Endpoint Template

Given `--include-sample-endpoints` is not supplied
When `endpoints.json` is generated
Then it contains an empty `endpoints` array and no secrets.

### AC-005: Sample Endpoint Template

Given `--include-sample-endpoints` is supplied
When `endpoints.json` is generated
Then it contains exactly one non-destructive `GET https://example.com/health` placeholder endpoint using static payload strategy and no secrets.

Given `--include-sample-endpoints` is supplied with `--target-environment prod` or `--target-environment production`
When `endpoints.json` is generated
Then the sample endpoint still uses only `https://example.com/health` and does not contain a real production hostname, credential, token, or auth reference.

### AC-006: Safe Defaults

Given a successful config init run
When `client_config.json` and `audit_config.json` are inspected
Then production execution and destructive operations are disabled, concurrency and timeout defaults are conservative, and no AWS resources are referenced.

### AC-006A: Production-Oriented Template Safety

Given `--target-environment prod` or `--target-environment production`
When the operator runs `rcp config init`
Then the command succeeds locally, generated configs set `allow_production_execution=false` and `allow_destructive_operation=false`, no real production endpoint or auth reference is generated, and dangerous schedules or aggressive concurrency defaults are not enabled.

### AC-007: Schema Validity

Given generated config files from a successful run, including a production-oriented template
When the project’s config validation is executed against those files
Then validation succeeds without requiring AWS credentials or network access.

### AC-008: Overwrite Protection

Given the final generated client root directory `<output-dir>/<client_id>/` already exists
When the operator runs `rcp config init` without `--overwrite`
Then the command exits non-zero and does not modify existing files.

### AC-009: Explicit Overwrite

Given the final generated client root directory `<output-dir>/<client_id>/` already exists
When the operator runs `rcp config init --overwrite`
Then the command may replace generated files in the target directory and must report the overwritten target path.

### AC-010: No AWS Calls

Given AWS SDK calls are mocked to fail if invoked
When `rcp config init` runs successfully or fails due to local validation
Then no AWS client construction or AWS API call occurs.

### AC-011: JSON Output

Given `--output json` is supplied
When the command succeeds
Then stdout is valid JSON containing generated IDs, generated root directory, generated file paths, and safety warning text.

### AC-012: Git Safety Warning

Given any successful config init run
When the command output is inspected
Then it warns the operator not to commit local configs and recommends using `.local-configs/` with `.local-configs/` in `.gitignore`.

## 9. Edge Cases

- Client names that slugify to an empty value must fail with a clear validation error.
- Client names with path separators or traversal sequences must not influence filesystem paths beyond the sanitized ID.
- `--target-environment prod` and `--target-environment production` must be accepted and handled as safe local template generation only.
- Unsupported or empty `--target-environment` values must fail before writing files.
- Invalid timezone values must fail before writing files.
- Partial directory creation failures must return a non-zero exit code and must not report success.
- JSON output mode must remain parseable even when warning text is included as JSON fields.
- The command must not write secrets even when sample endpoint generation is requested.

## 10. Constraints

- No AWS access, AWS credential dependency, or network dependency is allowed.
- Generated configs must use safe defaults only.
- Generated JSON must be deterministic in structure and human-readable.
- The command must not use current runtime timestamps to create active schedule times; date use is limited to the `audit_id` format and non-active placeholders.
- Directory writes must be constrained to `<output-dir>/<client_id>/` and generated child paths.
- Production-oriented templates must remain non-executable by default until explicit downstream approval and validation permit production execution.

## 11. Dependencies

- Existing `rcp` operator CLI entry point and command routing.
- Existing shared config validation rules and lifecycle assumptions.
- Existing ID validation rules.
- Existing payload strategy and payload safety validation.
- Local filesystem access.

## 12. Assumptions

- None.

## 13. Open Questions

- None.
