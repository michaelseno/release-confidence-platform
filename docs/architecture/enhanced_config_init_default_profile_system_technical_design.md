# Technical Design

## 1. Feature Overview

Enhance `rcp config init` into a local-only, profile-driven configuration initializer. The command will load reusable defaults profiles, resolve generation inputs with deterministic precedence, generate validation-safe starter config files under an isolated client workspace, validate the generated configs, and write them only to the local filesystem.

This design is based on `docs/product/enhanced_config_init_default_profile_system_product_spec.md` and the current repository layout discovered on branch `feature/profile_driven_config_init`.

## 2. Product Requirements Summary

- `--client-name` remains required.
- `--defaults` is optional and defaults to named profile `dev`.
- Named profiles `dev`, `staging`, and `prod` resolve to default JSON files.
- Defaults values containing path separators or ending in `.json` resolve as explicit JSON file paths.
- Explicit CLI arguments override profile values; profile values override hardcoded safe fallbacks.
- Generated output defaults to `.local-configs/<client_id>/` and must contain:
  - `client_config.json`
  - `audits/<audit_id>/audit_config.json`
  - `audits/<audit_id>/endpoints.json`
- Generated IDs must be validation-compatible safe IDs.
- Generated files must contain no secrets and must validate before success is reported.
- Existing output directories are protected unless `--overwrite` is provided.
- The command must never construct AWS clients, require AWS credentials, or call AWS services.
- Production-oriented configs must be non-executable and conservative by default.

## 3. Requirement-to-Architecture Mapping

| Requirement | Architecture Decision |
| --- | --- |
| FR-001 CLI contract | Update `src/release_confidence_platform/operator_cli/main.py` `config init` parser to accept `--defaults`, optional `--output-dir`, optional `--timezone`, `--include-sample-endpoints`, `--overwrite`, and `--output`. Remove the required `--target-environment` CLI dependency for init. |
| FR-002 profile resolution | Add a local defaults profile resolver/loader under `src/release_confidence_platform/operator_cli/` or `src/release_confidence_platform/config/` that maps named profiles to repo-root `config/defaults/*.json` and path-like values to explicit paths. |
| FR-003 profile content | Define and validate a default profile schema including `operator_defaults`, request defaults, rate limits, payload safety, schedules, retention, and production safeguards. |
| FR-004 precedence | Centralize resolution in `ConfigInitService`: early parse values → load profile → merge `operator_defaults` → apply CLI overrides → apply hardcoded safe fallbacks. |
| FR-005 directory structure | Resolve the output parent, then write only beneath `<output_parent>/<client_id>/`; default output parent is `.local-configs`. |
| FR-006 IDs | Continue using `core/id_generation.py` and `core/slug_utils.py`; validate slugs before path construction. |
| FR-007/008/009 generated config shapes | Extend existing generator modules to accept resolved defaults instead of embedding environment defaults. |
| FR-010 production safety | Enforce production-safe values during profile validation and generated config validation. The `prod` profile must set non-executable safeguards. |
| FR-011 validation | Validate profiles before generation and validate generated dictionaries with `AuditConfigValidationService.validate_configs(..., template_mode=True)` before any writes. |
| FR-012 overwrite | Check the client root exists before writes; fail without mutation unless `--overwrite`. |
| FR-013 no AWS | Keep implementation inside `ConfigInitService` and config modules only; do not use `StageConfigLoader` or `AwsClientFactory`. Add tests that monkeypatch AWS construction to fail. |
| FR-014 output | Return non-secret `CommandResult.data` fields and rely on existing `operator_cli.result.render` for text/JSON output. |

## 4. Technical Scope

### Current Technical Scope

- Add default profile JSON files at the repo-visible locations:
  - `config/defaults/dev.json`
  - `config/defaults/staging.json`
  - `config/defaults/prod.json`
- Add profile loading, resolution, and validation for `rcp config init`.
- Update `ConfigInitService` to use profile-driven defaults and optional CLI overrides.
- Extend or adapt existing config generators to accept resolved defaults.
- Preserve local-only generation and validation behavior.
- Update API/contract tests for the new command lifecycle.

### Out of Scope

- Uploading generated files to S3 or any remote storage.
- Creating audit metadata.
- Lambda invocation.
- EventBridge or schedule creation.
- AWS credential loading.
- Interactive profile selection.
- Post-generation editing workflows.

### Future Technical Considerations

- Independent JSON Schema file for defaults profiles.
- Profile schema version migrations.
- Additional named profile discovery beyond `dev`, `staging`, and `prod`.
- Packaging bundled default profiles for installed distributions if this CLI is run outside the repository checkout.

## 5. Architecture Overview

Current repo/package layout relevant to this feature:

- `pyproject.toml`
  - Python package source is `src/`.
  - CLI entry point is `rcp = release_confidence_platform.operator_cli.main:main`.
- `src/release_confidence_platform/operator_cli/main.py`
  - Argparse command tree and dispatch.
- `src/release_confidence_platform/operator_cli/services.py`
  - Thin CLI-to-service adapters.
- `src/release_confidence_platform/operator_cli/config_init.py`
  - Existing local-only config init orchestration; currently hardcodes `target_environment`, requires `output_dir`, and invokes generators/validation/writes.
- `src/release_confidence_platform/config/generators/`
  - Existing generator modules for `client_config`, `audit_config`, and `endpoints`.
- `src/release_confidence_platform/config/audit_validation_service.py`
  - Existing generated-config validation path; supports `template_mode=True` for empty endpoint lists and production template safety.
- `src/release_confidence_platform/config/validators.py`
  - Endpoint/config validation helpers.
- `src/release_confidence_platform/core/id_generation.py` and `src/release_confidence_platform/core/slug_utils.py`
  - Existing safe ID and slug utilities.
- `tests/api/test_config_init_contract.py`
  - Existing API-level tests for local config init.

Implementation should extend these existing modules rather than creating a separate CLI framework. The command should remain a thin CLI adapter over a testable service.

High-level lifecycle:

1. Parse early CLI values in `main.py`.
2. Call `services.config_init_command(args)`.
3. `ConfigInitService.init(...)` resolves and loads defaults profile.
4. Validate profile content and safety rules.
5. Resolve finalized generation inputs using precedence:
   1. Explicit CLI argument values.
   2. Profile `operator_defaults` and profile defaults.
   3. Hardcoded safe fallback values only for missing values.
6. Generate `client_id` and `audit_id`.
7. Generate config dictionaries.
8. Validate generated dictionaries using existing audit validation service in template mode.
9. Check overwrite semantics.
10. Write JSON files to local workspace.
11. Return non-secret summary data for text or JSON rendering.

## 6. System Components

### CLI Command Handling

Module: `src/release_confidence_platform/operator_cli/main.py`

Responsibilities:

- Define `rcp config init` arguments:
  - `--client-name` required.
  - `--defaults` optional, default `dev`.
  - `--output-dir` optional.
  - `--timezone` optional.
  - `--include-sample-endpoints` flag.
  - `--overwrite` flag.
  - `--output` choices `text`, `json`, default `text`.
- Do not require `--target-environment`; it is resolved from the defaults profile.
- Preserve argparse-level invalid output format handling.

Module: `src/release_confidence_platform/operator_cli/services.py`

Responsibilities:

- Keep `config_init_command` as a thin adapter.
- Pass `defaults`, `output_dir`, `timezone`, `include_sample_endpoints`, and `overwrite` to `ConfigInitService`.
- Do not load `StageConfigLoader` or instantiate `AwsClientFactory` in this path.

### Profile Loading and Resolution

Recommended module: `src/release_confidence_platform/operator_cli/default_profiles.py`

Responsibilities:

- Resolve profile references.
- Load JSON from local filesystem.
- Return a typed/default-profile object or normalized dictionary.
- Validate required profile fields and supported named profiles.

Resolution rules:

- Missing `--defaults` or `--defaults dev` → `config/defaults/dev.json`.
- `--defaults staging` → `config/defaults/staging.json`.
- `--defaults prod` → `config/defaults/prod.json`.
- Values containing `/` or `\` → explicit file path.
- Values ending with `.json` → explicit file path, even without separators.
- Other values fail with `INVALID_ARGUMENT` unless they are one of `dev`, `staging`, `prod`.

Exact default profile locations:

- Repo root canonical files:
  - `config/defaults/dev.json`
  - `config/defaults/staging.json`
  - `config/defaults/prod.json`

The current repository has `configs/samples/` for sample generated config files, but the product spec requires externally visible default profiles under `config/defaults/`. Use `config/defaults/` for this feature and do not place defaults under `configs/samples/`. No compatibility mapping is needed for current repo conventions because `configs/samples/` serves a different purpose.

Named profile path lookup should be deterministic:

1. Prefer `<current working directory>/config/defaults/<name>.json` when it exists.
2. If not found, discover the repository root relative to the installed source file by walking parents until `config/defaults/<name>.json` exists.
3. If still not found, fail before generation.

This preserves the externally visible product paths while allowing tests to execute from the repo root.

### Profile Validation

Recommended module: `src/release_confidence_platform/operator_cli/default_profile_validation.py` or same `default_profiles.py` if kept small.

Responsibilities:

- Validate JSON is an object.
- Validate required top-level fields.
- Validate operator defaults and nested default sections.
- Enforce production safety when `target_environment` is `prod` or `production`.
- Reject unsupported/secret-bearing fields in profiles.

### Config Generation

Existing modules:

- `src/release_confidence_platform/config/generators/client_config_generator.py`
- `src/release_confidence_platform/config/generators/audit_config_generator.py`
- `src/release_confidence_platform/config/generators/endpoints_generator.py`

Responsibilities:

- Generate dictionaries only; no filesystem writes.
- Accept resolved profile-derived defaults as inputs.
- Keep hardcoded constants only as safe fallbacks after resolution.
- Continue producing schemas compatible with `AuditConfigValidationService`.

### ID Generation and Slug Utilities

Existing modules:

- `src/release_confidence_platform/core/id_generation.py`
- `src/release_confidence_platform/core/slug_utils.py`

Responsibilities:

- Keep existing `client_<slug>_<shortid>` and `audit_<YYYYMMDD>_<shortid>` formats.
- Reject empty or unsafe client-name slugs before path construction.
- Preserve test injection hooks `client_shortid`, `audit_shortid`, and `today` in `ConfigInitService`.

### Filesystem Output

Module: `src/release_confidence_platform/operator_cli/config_init.py`

Responsibilities:

- Own local path calculation and writes.
- Check target client root before creating directories.
- Write pretty JSON with newline termination.
- Roll back files written during a partial write failure.
- Do not mutate `.gitignore`; return warning guidance only.

### Validation Integration

Existing module: `src/release_confidence_platform/config/audit_validation_service.py`

Responsibilities:

- Validate generated config dictionaries before writes.
- Use `template_mode=True` so empty endpoints are allowed.
- Use validation `stage` derived from target environment, normalized to `dev`, `staging`, or `prod`; production aliases should validate as `prod` when needed.

## 7. Data Models

## Default Profile

### Purpose

Centralized, reusable initialization defaults for `rcp config init`.

### Primary Key

`profile_name` for named profiles. Explicit file path profiles do not require global uniqueness but must still include `profile_name`.

### Fields

Required top-level JSON shape:

```json
{
  "profile_name": "dev",
  "profile_schema_version": "v1",
  "target_environment": "dev",
  "operator_defaults": {
    "output_dir": ".local-configs",
    "timezone": "UTC",
    "output": "text"
  },
  "request_defaults": {
    "timeout_seconds": 10,
    "retries": 0
  },
  "rate_limits": {
    "max_concurrency": 5,
    "max_requests_per_run": 100
  },
  "payload_safety": {
    "allow_generated_payloads": false,
    "allow_data_pool_reuse": false,
    "destructive_operation": false,
    "allow_destructive_operation": false
  },
  "production_safeguards": {
    "allow_production_execution": false,
    "allow_destructive_operation": false
  },
  "schedule_defaults": {
    "audit_window": {
      "duration_hours": 48
    },
    "baseline_schedule": {
      "enabled": true,
      "interval_minutes": 15,
      "scenario_type": "baseline_health",
      "requests_per_run": 1
    },
    "burst_schedule": {
      "enabled": false,
      "windows": []
    },
    "repeated_schedule": {
      "enabled": true,
      "runs_per_day": 1,
      "iteration_count": 1,
      "scenario_type": "repeated_stability"
    },
    "finalization_schedule": {
      "enabled": true
    }
  },
  "retention_defaults": {
    "evidence_retention_days": 30,
    "config_retention_days": 90
  },
  "sample_endpoints": []
}
```

Field rules:

- `profile_name`: non-empty string; named profiles should match `dev`, `staging`, or `prod` for bundled defaults.
- `profile_schema_version`: optional for product acceptance but recommended as `v1`; see assumptions.
- `target_environment`: one of `dev`, `staging`, `prod`, `production`.
- `operator_defaults.output_dir`: optional string; default fallback `.local-configs`.
- `operator_defaults.timezone`: optional IANA timezone string; default fallback `UTC`.
- `operator_defaults.output`: optional `text` or `json`; default fallback `text`.
- `request_defaults.timeout_seconds`: positive number compatible with `config.validators` maximum timeout.
- `request_defaults.retries`: integer from `0` through existing max retry validation.
- `rate_limits.max_concurrency`: positive conservative integer accepted by `audit_scheduling.safeguards.effective_caps`.
- `rate_limits.max_requests_per_run`: positive conservative integer accepted by `effective_caps`.
- `payload_safety`: must default to non-destructive values.
- `production_safeguards.allow_production_execution`: must be `false` for bundled `prod`.
- `production_safeguards.allow_destructive_operation`: must be `false` for all bundled profiles.
- `schedule_defaults`: must include baseline, burst, repeated, and finalization keys in validation-compatible form.
- `retention_defaults`: included to satisfy profile content requirements and future validation; generated configs may include it if current validators accept passthrough fields.
- `sample_endpoints`: optional array of safe mock examples. Bundled `prod` should keep this empty or generate no samples even when requested unless examples are demonstrably safe.

### Ownership Model

Profiles are repository-owned defaults maintained by platform engineers. Explicit profile file paths are operator-provided local files and must not be modified by the command.

### Lifecycle

- Created/updated manually in source control.
- Loaded read-only at command runtime.
- Invalid profiles fail before output directory mutation.

### Extensibility Rules

- Unknown top-level keys may be allowed only if they are JSON-safe, non-secret-bearing, and ignored by current generation.
- Unknown keys inside `operator_defaults`, safety, request, rate, and schedule sections should fail until explicitly supported to avoid silent unsafe behavior.
- Any key containing secret-like names (`password`, `token`, `secret`, `api_key`, `authorization`, `cookie`, `private_key`) must be rejected unless represented only as a non-secret reference and not written as a literal secret.

## Generated `client_config.json`

### Purpose

Local starter client configuration for validation and review.

### Primary Key

`client_id`.

### Fields

Expected generated shape:

```json
{
  "config_version": "v1",
  "client_id": "client_acme_a8f3c2d1",
  "client_name": "Acme",
  "execution_environment": {
    "target_environment": "dev",
    "allow_production_execution": false,
    "allow_destructive_operation": false
  },
  "request_defaults": {
    "timeout_seconds": 10,
    "retries": 0,
    "max_concurrency": 5
  },
  "safety": {
    "allowed_methods": ["GET", "HEAD", "OPTIONS"],
    "allow_destructive_operation": false
  },
  "sanitization": {
    "enabled": true
  },
  "operational_caps": {
    "max_concurrency": 5,
    "max_requests_per_run": 100
  },
  "retention_defaults": {
    "evidence_retention_days": 30,
    "config_retention_days": 90
  }
}
```

No secrets or literal credentials are permitted.

## Generated `audit_config.json`

### Purpose

Local starter audit configuration for validation and review.

### Primary Key

`audit_id` scoped by `client_id`.

### Fields

Expected generated shape:

```json
{
  "config_version": "v1",
  "client_id": "client_acme_a8f3c2d1",
  "audit_id": "audit_20260524_ef56ab78",
  "timezone": "UTC",
  "audit_window": {
    "duration_hours": 48,
    "timezone": "UTC"
  },
  "execution_environment": {
    "target_environment": "dev",
    "allow_production_execution": false,
    "allow_destructive_operation": false,
    "max_concurrency": 5,
    "max_requests_per_run": 100
  },
  "baseline_schedule": {
    "enabled": true,
    "interval_minutes": 15,
    "scenario_type": "baseline_health",
    "requests_per_run": 1
  },
  "burst_schedule": {
    "enabled": false,
    "windows": []
  },
  "repeated_schedule": {
    "enabled": true,
    "runs_per_day": 1,
    "iteration_count": 1,
    "scenario_type": "repeated_stability"
  },
  "finalization_schedule": {
    "enabled": true
  },
  "operational_caps": {
    "max_concurrency": 5,
    "max_requests_per_run": 100
  }
}
```

Schedules are local config data only. They must not imply that runtime schedules have been registered.

## Generated `endpoints.json`

### Purpose

Local endpoint list for validation and review.

### Primary Key

The file is scoped by `client_id` and `audit_id`; individual endpoints use `endpoint_id` when present.

### Fields

Default generated shape:

```json
{
  "config_version": "v1",
  "client_id": "client_acme_a8f3c2d1",
  "audit_id": "audit_20260524_ef56ab78",
  "target_environment": "dev",
  "endpoints": []
}
```

Sample endpoint shape when `--include-sample-endpoints` is supplied:

```json
{
  "endpoint_id": "endpoint_health_check",
  "method": "GET",
  "url": "https://example.com/health",
  "target_environment": "dev",
  "payload_strategy": "static",
  "payload": null,
  "payload_safety": {
    "allow_generated_payloads": false,
    "allow_data_pool_reuse": false,
    "destructive_operation": false,
    "allow_destructive_operation": false
  },
  "auth_required": false,
  "headers": {},
  "timeout_seconds": 10,
  "retries": 0,
  "assertions": {
    "expected_status_codes": [200]
  }
}
```

Samples must use mock/example hosts only, no credentials, no auth refs, and non-destructive methods.

## 8. API Contracts

This feature exposes a CLI contract, not an HTTP API.

## Command: `rcp config init`

### Purpose

Generate a local, validation-safe starter config workspace from a defaults profile.

### Authentication / Authorization

No authentication. No AWS credentials. Local filesystem write permissions to the output path are required.

### Request Parameters

- `--client-name <name>`: required string.
- `--defaults <name-or-path>`: optional, default `dev`.
- `--output-dir <path>`: optional output parent directory.
- `--timezone <iana-timezone>`: optional override.
- `--include-sample-endpoints`: optional flag.
- `--overwrite`: optional flag.
- `--output <text|json>`: optional, default `text` or profile value if omitted and supported by parser/service integration.

### Response Body

In JSON output mode, stdout must be valid JSON with the existing `CommandResult` envelope and non-secret data equivalent to:

```json
{
  "command": "config init",
  "stage": null,
  "status": "success",
  "summary": "generated local starter config files; local only, no upload performed",
  "data": {
    "client_id": "client_acme_a8f3c2d1",
    "audit_id": "audit_20260524_ef56ab78",
    "defaults_profile": "dev",
    "defaults_source": "config/defaults/dev.json",
    "target_environment": "dev",
    "output_dir": ".local-configs/client_acme_a8f3c2d1",
    "generated_files": [
      {"type": "client", "path": ".local-configs/client_acme_a8f3c2d1/client_config.json", "file_name": "client_config.json"},
      {"type": "audit", "path": ".local-configs/client_acme_a8f3c2d1/audits/audit_20260524_ef56ab78/audit_config.json", "file_name": "audit_config.json"},
      {"type": "endpoints", "path": ".local-configs/client_acme_a8f3c2d1/audits/audit_20260524_ef56ab78/endpoints.json", "file_name": "endpoints.json"}
    ],
    "overwritten": false,
    "local_only": true,
    "aws_interaction": false,
    "warning": "local generated configs may contain operational details; keep files under .local-configs/ and add .local-configs/ to .gitignore"
  }
}
```

Text output must include equivalent non-secret fields plus a local-only/no-upload safety message.

### Success Status Codes

- Process exit code `0` on successful validation and write.

### Error Status Codes

- Process exit code `1` for invalid arguments, invalid profile resolution, invalid JSON, validation failure, local write failure, or protected existing directory.

Expected `error_type` values should reuse project exceptions where practical:

- `INVALID_ARGUMENT`: unsupported profile name, invalid timezone, invalid output format, unsafe client name.
- `CONFIG_LOAD_ERROR`: defaults file cannot be read or JSON is invalid.
- `CONFIG_VALIDATION_ERROR`: defaults profile or generated configs are invalid.
- `LOCAL_FILE_EXISTS`: target client root exists without `--overwrite`.
- `LOCAL_WRITE_FAILED`: filesystem write failure.
- `UNEXPECTED_ERROR`: uncaught failures handled by `main.py`.

### Validation Rules

- Profile must resolve and validate before generated files are written.
- Generated configs must pass `AuditConfigValidationService.validate_configs(..., template_mode=True)` before write.
- Timezone must be accepted by `zoneinfo.ZoneInfo`.
- Client slug must be non-empty and path-safe.
- Output JSON mode must write no human-readable text outside the JSON payload.

### Side Effects

- Creates or replaces local files only under the resolved client root.
- No AWS clients, AWS API calls, network calls, schedule creation, uploads, or metadata writes.

### Idempotency / Duplicate Handling

- Repeated calls generate new IDs by default, so they create new client/audit roots unless deterministic test short IDs are injected.
- If the resolved client root exists and `--overwrite` is absent, fail before mutation.
- If `--overwrite` is present, replace generated files and report `overwritten=true` when the client root existed.

## 9. Frontend Impact

No web frontend impact.

### Components Affected

- Operator CLI only.

### API Integration

- Existing CLI rendering path in `operator_cli.result`.

### UI States

- Text mode success with generated IDs, paths, selected profile, and local-only message.
- Text mode error via existing `render_error`.
- JSON mode success/error must be parseable JSON.

## 10. Backend Logic

### Responsibilities

`ConfigInitService` remains the backend orchestration boundary for this local command.

### Validation Flow

1. Validate `client_name` is present and slugifies to a safe non-empty slug.
2. Resolve `defaults` to named profile path or explicit path.
3. Load JSON and fail on missing/unreadable/invalid JSON.
4. Validate default profile required sections.
5. Validate target environment and production safeguards.
6. Resolve timezone and validate with `ZoneInfo`.
7. Resolve output format and output parent.
8. Generate IDs.
9. Generate config dictionaries.
10. Validate generated configs with `AuditConfigValidationService` in template mode.
11. Check overwrite protection.
12. Write files.

### Business Rules

- Resolution hierarchy is always: explicit CLI argument → defaults profile values → hardcoded safe fallback.
- `operator_defaults` may provide `output_dir`, `timezone`, and `output`; CLI explicit values must override them.
- `target_environment` comes from the profile, with only hardcoded safe fallback `dev` if absent in a custom profile and validation rules permit fallback. Bundled profiles must include it.
- Production target environments must always generate:
  - `allow_production_execution=false`
  - `allow_destructive_operation=false`
  - conservative rate limits
  - no real endpoints
- Empty endpoints are the default.
- Sample endpoints must remain safe mock examples and should still be omitted or safe for production profiles.

### Persistence Flow

- Let `output_parent = explicit --output-dir || profile.operator_defaults.output_dir || ".local-configs"`.
- Let `client_root = output_parent / client_id`.
- Let `audit_dir = client_root / "audits" / audit_id`.
- Write:
  - `client_root / "client_config.json"`
  - `audit_dir / "audit_config.json"`
  - `audit_dir / "endpoints.json"`
- Never write `.local-configs/client_config.json`.

### Error Handling

- Any failure before validation/writes must leave no generated files.
- If write failure occurs after some files are written, delete files written during this invocation.
- Do not delete pre-existing unrelated files. With `--overwrite`, only replace the known generated file paths.
- Errors are surfaced as `EngineError` subclasses so `main.py` can render consistently.

## 11. File Structure

Files to add/update:

```text
config/
  defaults/
    dev.json
    staging.json
    prod.json
src/release_confidence_platform/operator_cli/
  main.py                         # update argparse contract for config init
  services.py                     # pass defaults-driven args to ConfigInitService
  config_init.py                  # orchestrate profile-driven lifecycle
  default_profiles.py             # new: resolve/load/validate defaults profiles
src/release_confidence_platform/config/generators/
  client_config_generator.py      # accept resolved defaults
  audit_config_generator.py       # accept resolved defaults/schedules
  endpoints_generator.py          # accept resolved defaults/sample behavior
tests/api/
  test_config_init_contract.py    # update existing contract tests
  test_config_init_profiles.py    # recommended new focused profile tests
docs/architecture/
  enhanced_config_init_default_profile_system_technical_design.md
```

The top-level `packages/operator_cli/` directory appears to duplicate earlier CLI files and is not the package used by `pyproject.toml` entry points. Implement this feature under `src/release_confidence_platform/...` only unless maintainers explicitly require legacy mirror updates.

## 12. Security

- Authentication: none; local command only.
- Authorization: local filesystem permissions only.
- Secrets:
  - Reject literal secrets in defaults profiles.
  - Generated configs must not include credentials, tokens, cookies, passwords, API keys, private keys, or real secret values.
  - Endpoint headers with secret-bearing names must use `secret_ref` if ever allowed; starter sample endpoints should avoid auth entirely.
- Path safety:
  - Use generated `client_id` and `audit_id` for paths, not raw `client_name`.
  - Reject client names that slugify to empty.
  - Explicit profile paths are read only; do not write beside them.
- Production safety:
  - `prod` profile and production custom profiles must produce non-executable configs by default.
  - No destructive methods in samples.
  - Conservative concurrency and request caps.
- Misuse risk:
  - Operators may edit generated files after creation; command output should instruct validation/review before any future upload or schedule operation.

## 13. Reliability

- Retries: no external calls; no retry logic required for local file writes.
- Timeouts: no network operations; not applicable.
- Failure modes:
  - Missing profile → fail before generation.
  - Invalid JSON/profile → fail before generation.
  - Existing output root without overwrite → fail before mutation.
  - Generated config validation failure → fail before write.
  - Local write failure → roll back files written in this invocation.
- Logging/monitoring:
  - No telemetry required.
  - CLI output should include enough paths and IDs for operator troubleshooting.
- Performance:
  - JSON files are small; synchronous filesystem operations are acceptable.
  - Profile loading is single-file local IO.

### No-AWS Guarantee and Enforcement

Implementation rules:

- `config init` must not import or instantiate `AwsClientFactory` through its execution path.
- `services.config_init_command` must not call `_stage(args)`.
- `ConfigInitService` must depend only on local config/profile/generator/validation/id/filesystem modules.
- Validation must use in-memory generated dictionaries with `template_mode=True`; it must not load stage config or AWS-backed repositories.

Test enforcement:

- Add a test that monkeypatches `release_confidence_platform.storage.aws_client_factory.AwsClientFactory.__init__` to raise and verifies `rcp config init` succeeds.
- Add a test that monkeypatches `boto3.client` and `boto3.resource` to raise and verifies `ConfigInitService.init` succeeds/fails locally without triggering them.
- Add failure-path tests for invalid profile and existing output directory with the same AWS monkeypatches active.

## 14. Dependencies

- Existing argparse CLI framework.
- Existing `CommandResult`, `render`, and `render_error` output formatters.
- Existing config validation service and validators.
- Existing ID generation and slug utilities.
- Python standard library:
  - `json`
  - `pathlib`
  - `zoneinfo`
  - `dataclasses` if typed profile objects are used.
- Local filesystem access.

No new third-party dependencies are required.

## 15. Assumptions

### Confirmed by Product Spec

- Default profile location is `config/defaults/` unless technical design confirms an alternate. This design uses `config/defaults/` directly.
- `--output` supports at least `text` and `json`.
- Generated config validation can use existing project validation rules.

### Technical Assumptions Requiring Confirmation

- `profile_schema_version` should be included as `v1` in default profiles for future migrations, even though the product spec lists it as an open question.
- `retention_defaults` can be included in generated configs if current validators tolerate extra fields; if not, keep retention defaults validated at profile level only until runtime schemas require them.
- For profile-provided `operator_defaults.output`, argparse cannot know whether `--output` was omitted if it always sets a default. Implementation should set parser default to `None` for `config init` and let `ConfigInitService` resolve `text` fallback, or use an explicit sentinel.
- Named profile discovery outside a repository checkout is not required for this feature. If it becomes required, package data support should be added later.

## 16. Risks / Open Questions

- Exact independent schema for `operator_defaults` is not defined by product. Mitigation: implement explicit validation in `default_profiles.py` and keep the accepted keys small.
- Existing validation is permissive for some config object fields and strict for endpoint payload safety. Generated shapes must be tested against current validators after generator changes.
- The current `main.py` requires `--target-environment` and `--output-dir`; removing these required args is a user-facing CLI contract change required by the spec.
- Existing tests may assert old required args. Update them to the new product contract.
- If profile `sample_endpoints` becomes customizable, strict validation is needed to prevent real endpoints/secrets. For current scope, prefer generator-owned safe samples instead of arbitrary profile samples.
- `configs/samples/` and `config/defaults/` have similar names but different purposes; documentation/tests should prevent future confusion.
- Python package installation may omit top-level `config/defaults/` because `pyproject.toml` package discovery includes only `src`. This is acceptable for repo-local workflow but should be revisited before distributing the CLI as an installed tool outside the repo.

## 17. Implementation Notes

Recommended dev-backend sequence:

1. Add `config/defaults/dev.json`, `staging.json`, and `prod.json` using conservative values and the profile schema above.
2. Add `default_profiles.py` with pure functions/classes for resolving, loading, and validating profiles.
3. Update `main.py` `config init` parser:
   - add `--defaults` defaulting to `dev` or service-level default;
   - make `--output-dir` and `--timezone` optional;
   - remove required `--target-environment` from this command;
   - set `--output` default carefully so profile `operator_defaults.output` can apply when omitted.
4. Update `services.config_init_command` to pass new args and avoid stage/AWS code.
5. Refactor `ConfigInitService.init` to implement the required lifecycle and precedence.
6. Extend generator functions to accept resolved defaults while preserving current safe fallback constants.
7. Validate generated configs before writes, using `template_mode=True` and a validation stage derived from target environment.
8. Update overwrite logic to check the final client root and report overwritten paths explicitly.
9. Add/adjust tests:
   - default dev profile with minimal args;
   - named staging/prod profiles;
   - explicit defaults file path;
   - CLI override precedence for output-dir/timezone/output;
   - generated directory structure and no `.local-configs/client_config.json`;
   - invalid/missing profile fails before writes;
   - generated configs validate;
   - empty endpoints by default;
   - safe sample endpoints;
   - production profile safeguards;
   - overwrite protection and explicit overwrite;
   - no AWS client construction/API calls in success and local failure paths;
   - JSON output remains parseable.
10. Run focused tests first (`tests/api/test_config_init_contract.py` and new profile tests), then full test suite.
