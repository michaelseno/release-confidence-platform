# Technical Design

## 1. Feature Overview

Implement `rcp config init`, an internal operator CLI command that generates a local, schema-aligned starter configuration set for a new audit. The command writes only local JSON files and returns the generated `client_id`, `audit_id`, final root directory, generated file paths, and git safety warning.

Traceability: product spec FR-001 through FR-011, including FR-008A, and AC-001 through AC-012, including AC-001A and AC-006A.

## 2. Product Requirements Summary

- Provide `rcp config init` with required `--client-name`, `--target-environment`, and `--output-dir` arguments.
- Support optional `--timezone`, `--include-sample-endpoints`, `--overwrite`, and `--output json`.
- Generate:
  - `<output-dir>/<client_id>/client_config.json`
  - `<output-dir>/<client_id>/audits/<audit_id>/audit_config.json`
  - `<output-dir>/<client_id>/audits/<audit_id>/endpoints.json`
- Generate safe IDs:
  - `client_<slug>_<shortid>`
  - `audit_<YYYYMMDD>_<shortid>`
- Generated values must be lowercase and filesystem-safe.
- Generated configs must contain safe defaults, no secrets, no AWS resource references, and no AWS calls.
- `--output-dir` is always a parent/workspace directory; the final generated client root is always `<output-dir>/<client_id>/`.
- Existing final generated client root directories must be protected unless `--overwrite` is supplied.
- Default endpoint file must use an empty `endpoints` array; sample mode must include exactly one safe GET endpoint.
- `--target-environment prod` and `--target-environment production` must be accepted as production-oriented local templates that remain non-executable by default.

## 3. Requirement-to-Architecture Mapping

| Requirement | Architecture responsibility |
| --- | --- |
| FR-001 | Extend existing `rcp` argparse tree with `config init`; route through existing dispatch/result patterns. |
| FR-002, AC-003 | Add reusable slug and ID generation helpers under `core`. |
| FR-003, AC-001 | Add local config init service that calculates final root and writes required directory tree. |
| FR-004, AC-008, AC-009 | Perform pre-write conflict detection; write only when no conflict or `--overwrite=true`. |
| FR-005 to FR-007 | Add config generators for client, audit, and endpoints payloads. |
| FR-008, FR-008A, AC-006A, AC-007 | Reuse shared validation while adding explicit local-template validation semantics so empty endpoint arrays and production-oriented templates with `allow_production_execution=false` validate safely without weakening execution-time production controls. |
| FR-009, AC-010 | Keep command independent of `StageConfigLoader`, `AwsClientFactory`, storage clients, and network clients. |
| FR-010, AC-011, AC-012 | Extend CLI result rendering for `config init` text/JSON output. |

## 4. Technical Scope

### Current Technical Scope

- Local-only CLI command: `rcp config init`.
- New generation service and pure generator modules.
- Safe ID/slug utilities.
- Validation adjustment so empty endpoint arrays and production-oriented local templates are valid for starter config validation while execution-time safeguards remain intact.
- Tests for parser, generators, filesystem behavior, validation compatibility, output rendering, and no AWS construction/calls.

### Out of Scope

- Uploading configs to S3 or other storage.
- DynamoDB audit metadata writes or audit registration.
- EventBridge schedules.
- Lambda invocation, smoke runs, audit mutation, dashboards, status/log commands, monitoring, or Secrets Manager access.
- Automatic `.gitignore` mutation.
- Generated production templates are not production execution approval and must not create real production endpoints, credentials, schedules, or AWS resources.

### Future Technical Considerations

- Interactive init mode.
- Template presets for audit types.

## 5. Architecture Overview

The repository uses a src-layout package as the actual installable runtime package. The older `packages/` tree is compatibility/documentation-oriented and should not receive the primary implementation.

Primary implementation should be under `src/release_confidence_platform/`:

```text
rcp CLI parser
  -> operator_cli.services.config_init_command(args)
    -> operator_cli.config_init.ConfigInitService
      -> core.slug_utils.slugify_client_name
      -> core.id_generation.generate_client_id / generate_audit_id
      -> config.generators.*
      -> AuditConfigValidationService.validate_configs(..., stage="dev", template_mode=True)
      -> local filesystem writes
```

Important boundary: unlike existing `config list/download`, `config init` must not call `_stage(args)`, `StageConfigLoader`, or `AwsClientFactory` because the product explicitly forbids AWS credential/resource dependency.

## 6. System Components

### `src/release_confidence_platform/operator_cli/main.py`

Responsibilities:
- Add `config init` subcommand to the existing `config` command group.
- Arguments:
  - `--client-name` required string
  - `--target-environment` required, `choices=("dev", "staging", "prod", "production")`
  - `--output-dir` required path string
  - `--timezone` default `UTC`
  - `--include-sample-endpoints` boolean flag
  - `--overwrite` boolean flag
  - `--output` choices `("text", "json")`, default `text`
- Dispatch `args.config_command == "init"` to `services.config_init_command(args)`.

### `src/release_confidence_platform/operator_cli/services.py`

Responsibilities:
- Add thin adapter `config_init_command(args) -> CommandResult`.
- Must not load stage config or instantiate AWS clients.
- Return `CommandResult(command="config init", stage=None, status="success", ...)`.

### `src/release_confidence_platform/operator_cli/config_init.py`

Recommended new module replacing the product spec's suggested `packages/operator_cli/commands/config_init.py` to match current src-layout conventions.

Responsibilities:
- Validate CLI-level inputs.
- Generate IDs.
- Build generated root as `Path(output_dir) / client_id`; never treat `--output-dir` itself as the final generated client root.
- Build target paths:
  - `root / "client_config.json"`
  - `root / "audits" / audit_id / "audit_config.json"`
  - `root / "audits" / audit_id / "endpoints.json"`
- Run in-memory validation before filesystem writes.
- Detect conflicts before writes. If the final generated client root exists and `--overwrite=false`, fail before modifying anything under it. With `--overwrite=true`, replace only the three expected generated files under that generated client root.
- Write deterministic, pretty JSON with sorted keys or stable insertion ordering and two-space indentation.
- Return structured result data.

### `src/release_confidence_platform/config/generators/`

Create package:

- `client_config_generator.py`
- `audit_config_generator.py`
- `endpoints_generator.py`
- `__init__.py`

Responsibilities:
- Generate plain dictionaries only.
- No filesystem, AWS, environment, or network dependencies.
- Reuse constants from `core.constants.engine` and `audit_scheduling.constants` where possible.
- Preserve the operator-provided target environment metadata, including `prod`/`production`, while keeping generated safety gates disabled by default.

### `src/release_confidence_platform/core/id_generation.py`

Responsibilities:
- Generate safe local IDs.
- Use `secrets.token_hex(4)` or equivalent cryptographically strong random 8-hex short ID.
- Use injectable date/random dependencies in functions to support deterministic unit tests.

Contracts:
- `generate_client_id(client_name: str, *, shortid: str | None = None) -> str`
- `generate_audit_id(*, today: date | None = None, shortid: str | None = None) -> str`

### `src/release_confidence_platform/core/slug_utils.py`

Responsibilities:
- Convert client name into safe slug.
- Reject names that slugify to empty.
- Ensure no whitespace, path separators, traversal sequences, or shell metacharacters.

Contract:
- `slugify_client_name(value: str) -> str`

## 7. Data Models

No database persistence is introduced. Data persistence is local filesystem JSON only.

## Generated Config Set

### Purpose

Starter local configuration files for later validation/onboarding.

### Primary Key

Logical key is `(client_id, audit_id)`.

### Fields

#### `client_config.json`

Minimum generated shape:

```json
{
  "config_version": "v1",
  "client_id": "client_demo_client_ab12cd34",
  "client_name": "Demo Client",
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
  }
}
```

#### `audit_config.json`

Minimum generated shape:

```json
{
  "config_version": "v1",
  "client_id": "client_demo_client_ab12cd34",
  "audit_id": "audit_20260523_ef56ab78",
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

Notes:
- Generated audit config must not include AWS ARNs, bucket names, table names, Lambda names, schedule names, or active runtime timestamps.
- Date use is limited to `audit_id`.
- For `--target-environment prod` / `production`, generated configs must still set `allow_production_execution=false`, `allow_destructive_operation=false`, `max_concurrency=5`, and conservative request caps. They are production-oriented local templates only, not approval to execute against production.

#### `endpoints.json`

Default:

```json
{
  "config_version": "v1",
  "client_id": "client_demo_client_ab12cd34",
  "audit_id": "audit_20260523_ef56ab78",
  "target_environment": "dev",
  "endpoints": []
}
```

With `--include-sample-endpoints`:

```json
{
  "config_version": "v1",
  "client_id": "client_demo_client_ab12cd34",
  "audit_id": "audit_20260523_ef56ab78",
  "target_environment": "dev",
  "endpoints": [
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
  ]
}
```

For production-oriented templates, the sample endpoint remains exactly `https://example.com/health`; the generator must never infer or emit a production hostname, customer endpoint, credential, token, or `auth_ref`.

### Ownership Model

Local files are owned by the operator's filesystem user. No platform ownership is created until later upload/create workflows.

### Lifecycle

- Created by `config init`.
- Replaced only when `--overwrite` is explicitly supplied.
- Not archived, uploaded, or registered by this feature.

## 8. API Contracts

No HTTP APIs are involved.

## CLI Contract: `rcp config init`

### Purpose

Generate local starter config files for a new audit.

### Authentication / Authorization

None. Local operator CLI command only. No AWS credentials required.

### Request Parameters

- `--client-name <name>`: required non-empty string; must slugify to non-empty value.
- `--target-environment <environment>`: required; accepts `dev`, `staging`, `prod`, and `production`. `prod` and `production` create safe production-oriented local templates only and must not make generated configs executable in production.
- `--output-dir <path>`: required local destination parent directory.
- `--timezone <iana-or-utc>`: optional; default `UTC`; validate using `zoneinfo.ZoneInfo` with explicit `UTC` support.
- `--include-sample-endpoints`: optional flag.
- `--overwrite`: optional flag.
- `--output json`: optional machine-readable output.

### Response Body

JSON output shape:

```json
{
  "command": "config init",
  "stage": null,
  "status": "success",
  "summary": "generated local starter config files",
  "client_id": "client_demo_client_ab12cd34",
  "audit_id": "audit_20260523_ef56ab78",
  "output_dir": "/abs-or-user-provided/.local-configs/demo-client/client_demo_client_ab12cd34",
  "generated_files": [
    {"type": "client", "path": ".../client_config.json", "file_name": "client_config.json"},
    {"type": "audit", "path": ".../audits/audit_20260523_ef56ab78/audit_config.json", "file_name": "audit_config.json"},
    {"type": "endpoints", "path": ".../audits/audit_20260523_ef56ab78/endpoints.json", "file_name": "endpoints.json"}
  ],
  "overwritten": false,
  "warning": "local generated configs may contain operational details; keep files under .local-configs/ and add .local-configs/ to .gitignore"
}
```

### Success Status Codes

- Process exit `0` on success.

### Error Status Codes

- Process exit `1` for validation, conflict, or filesystem failure.
- Argparse parse errors continue to exit `2` before dispatch.

Error payloads must use existing `render_error()` behavior and must be JSON-parseable when `--output json` is present.

Recommended error types:
- `INVALID_ARGUMENT`: invalid client name, target environment, timezone, or output path.
- `LOCAL_FILE_EXISTS`: target root/files already exist and `--overwrite` was not supplied.
- `LOCAL_WRITE_FAILED`: directory/file creation failed.
- `CONFIG_VALIDATION_ERROR` or existing validation error codes for generated payload validation failures.

### Validation Rules

- All generated IDs must pass `core.validators.validate_identifier` and stricter local safe-character checks.
- Slug characters: lowercase `a-z`, digits, single underscores between tokens. No dots, slashes, backslashes, whitespace, `..`, shell metacharacters, or path separators.
- `shortid`: lowercase hex recommended; 8 chars minimum.
- Client names that slugify to empty fail before filesystem writes.
- Unsupported target environment fails before filesystem writes; supported values are `dev`, `staging`, `prod`, and `production`.
- Production-oriented templates must validate in local-template mode with `allow_production_execution=false` and must continue to fail execution-time validation unless a later explicit production approval path enables production execution.
- Invalid timezone fails before filesystem writes.
- Generated configs must validate in memory before filesystem writes.

### Side Effects

- Creates local directories and writes three JSON files only.
- Directory writes are constrained to `<output-dir>/<client_id>/` and its fixed generated child paths.
- No AWS client construction, AWS API calls, network calls, secrets lookup, metadata writes, schedules, or Lambda calls.

### Idempotency / Duplicate Handling

- Re-running without `--overwrite` against an existing generated root fails without modifying files.
- Re-running with `--overwrite` may replace the three generated files under the generated root and reports `overwritten=true`.
- IDs are random by default, so repeated commands normally create different client roots unless deterministic IDs are injected in tests.

## 9. Frontend Impact

No customer-facing frontend impact.

## 10. Backend Logic

### Responsibilities

- Parse and validate local CLI inputs.
- Generate safe IDs and JSON payloads.
- Validate generated payloads through shared validators.
- Write local files with overwrite protection.
- Render safe operator output.

### Validation Flow

1. Argparse validates command structure and simple choices.
2. Service validates:
   - non-empty client name
   - slug non-empty and safe
   - supported target environment
   - valid timezone
   - output path is not an existing file
3. Generate `client_id` and `audit_id`.
4. Generate config dictionaries.
5. Validate generated dictionaries with `AuditConfigValidationService.validate_configs(...)` using a non-prod validation stage such as `dev` and an explicit local-template mode that permits safe production-oriented templates while preserving production execution blocks elsewhere.
6. Detect filesystem conflicts.
7. Write files.

### Business Rules

- Production-oriented templates are allowed for `--target-environment prod` and `--target-environment production`, but remain operationally safe by default: `allow_production_execution=false`, `allow_destructive_operation=false`, conservative caps, no real auth references, no production endpoint URLs, and no dangerous schedule defaults.
- Destructive operations are always disabled in generated defaults.
- Sample endpoint is always non-authenticated and non-destructive.
- Sample endpoint URL is always `https://example.com/health`, including for production-oriented templates.
- Empty endpoint array must be validation-safe for starter configs.

### Persistence Flow

- Calculate all paths before writing.
- Final generated client root is always `Path(output_dir) / client_id`.
- If final generated client root exists and `--overwrite=false`, fail before writes.
- If generated root does not exist, create parent directories and write all files.
- If `--overwrite=true`, create directories as needed and replace only the three expected generated files.
- On partial write failure, attempt best-effort cleanup of files written during the failed invocation and return non-zero.

### Error Handling

- Raise `ValidationError`/`ConfigError`/`StorageError` subclasses of `EngineError` so existing CLI error rendering handles them.
- Do not leak secrets in errors. Generated config should have no secrets; existing sanitizer still applies.

## 11. File Structure

Actual implementation paths should follow the src-layout package:

```text
src/release_confidence_platform/operator_cli/main.py              # parser/dispatch update
src/release_confidence_platform/operator_cli/services.py          # thin adapter
src/release_confidence_platform/operator_cli/result.py            # render config init files/warning
src/release_confidence_platform/operator_cli/config_init.py       # new local init service
src/release_confidence_platform/config/generators/__init__.py     # new package
src/release_confidence_platform/config/generators/client_config_generator.py
src/release_confidence_platform/config/generators/audit_config_generator.py
src/release_confidence_platform/config/generators/endpoints_generator.py
src/release_confidence_platform/core/id_generation.py
src/release_confidence_platform/core/slug_utils.py
src/release_confidence_platform/config/validators.py              # allow empty endpoint arrays / template validation support
tests/unit/test_config_init_generation.py
tests/unit/test_config_init_cli.py
tests/security/test_config_init_no_aws.py
```

The product spec's `packages/...` recommendations map to `src/release_confidence_platform/...` because `pyproject.toml` installs from `src` and current CLI tests import `release_confidence_platform.*`.

## 12. Security

- No authentication is required because command is local-only.
- No authorization checks are introduced because no platform state is read or mutated.
- No AWS credentials, environment stage files, Secrets Manager, S3, DynamoDB, EventBridge, or Lambda clients may be imported by the init service.
- Input validation prevents path traversal through generated IDs. `--output-dir` is operator-controlled, but generated child paths must be fixed and safe.
- Generated JSON must not contain literal keys/values for passwords, tokens, cookies, private keys, API keys, Authorization headers, or secret values.
- Sample endpoint uses empty headers and `auth_required=false`.
- CLI output is sanitized through existing result renderer.

## 13. Reliability

- No retries are needed because there are no network calls.
- Filesystem errors fail fast with a clear non-zero result.
- Conflict detection occurs before writes.
- Partial write failures attempt best-effort cleanup of files created during the failed invocation.
- Generated JSON structure is deterministic aside from IDs/date.
- Tests should inject deterministic short IDs/date for repeatability.
- Logging is not required for success path; if logging is added, it must not print full config contents unnecessarily.

## 14. Dependencies

- Existing CLI entry point: `release_confidence_platform.operator_cli.main:main`.
- Existing `CommandResult`, `render`, and `render_error` conventions.
- Existing validators:
  - `core.validators.validate_identifier`
  - `config.audit_validation_service.AuditConfigValidationService`
  - `config.validators.validate_endpoint_config`
  - `data_generation.validators.validate_endpoint_payload_config`
  - audit scheduling caps/window validators
- Python standard library: `pathlib`, `json`, `secrets`, `datetime`, `re`, `zoneinfo`.

## 15. Assumptions

### Confirmed by Current Repository Inspection

- The installable package is `src/release_confidence_platform`, not `packages`.
- Existing CLI already has a `config` group with `list` and `download`; `init` should be added there.
- Existing validation currently rejects empty endpoint arrays; this must be changed to satisfy FR-008/AC-004/AC-007.
- Updated product decisions confirm that `--output-dir` is always a parent directory and the generated root is always `<output-dir>/<client_id>/`.
- Updated product decisions confirm that `prod` and `production` target environments must be accepted for safe local template generation.
- Updated product decisions confirm that `.gitignore` must not be modified automatically; only a warning/recommendation is required.

### Technical Assumptions Requiring Confirmation

- None.

### Implementation Details Requiring Care

- The remaining implementation detail is how to expose local-template validation without weakening execution-time validation. Empty endpoint arrays and production-oriented templates are valid for starter template validation; later execution/scheduling flows may still require at least one executable endpoint and explicit production approval.

## 16. Risks / Open Questions

- **Template validation semantics:** current `AuditConfigValidationService` rejects production configs when `allow_production_execution=false`, and current `extract_endpoints()` rejects empty arrays. Implementation must add explicit local-template validation behavior so generated starter templates pass validation while execution/scheduling flows still enforce non-empty executable endpoint sets and explicit production approval.
- **`.gitignore` automation:** resolved as out of scope by updated product spec; command must only print the recommendation.
- **Output-dir interpretation:** resolved by updated product spec; final generated root is always `<output-dir>/<client_id>/`.
- **Production target handling:** resolved by updated product spec; accept `prod` and `production` as safe local production-oriented templates.
- **Compatibility `packages/` tree:** duplicated package-like files exist under `packages/`, but runtime uses `src`. Implementing only under `packages/` would not affect the installed CLI.

## 17. Implementation Notes

### Generated Files Result Contract

Return data from `ConfigInitService.init(...)`:

```python
{
    "client_id": client_id,
    "audit_id": audit_id,
    "output_dir": str(root),  # always Path(args.output_dir) / client_id
    "generated_files": [
        {"type": "client", "path": str(client_path), "file_name": "client_config.json"},
        {"type": "audit", "path": str(audit_path), "file_name": "audit_config.json"},
        {"type": "endpoints", "path": str(endpoints_path), "file_name": "endpoints.json"},
    ],
    "overwritten": overwrite,
    "warning": "local generated configs may contain operational details; keep files under .local-configs/ and add .local-configs/ to .gitignore",
}
```

### Renderer Update

Extend `operator_cli.result.render()` similarly to existing `config download` handling:
- Include `client_id`, `audit_id`, and `output_dir` using existing key loop.
- For `command == "config init"`, print `generated_files` as a files list with paths or file names.
- Print warning text.
- `next_step`: `run rcp audit validate with the generated file paths before onboarding; keep files under .local-configs/ and do not commit them`.

### Test Plan Summary

- Parser tests:
  - `rcp config init` accepts required/optional flags.
  - `--target-environment prod` and `--target-environment production` are accepted.
  - `--output json` works without `--stage`.
  - Missing required args cause argparse exit `2`.
- ID/slug tests:
  - Spaces, uppercase, punctuation normalize safely.
  - Traversal/path separator input cannot appear in IDs or paths.
  - Empty slug fails.
  - IDs match required regexes.
- Generator tests:
  - Client/audit/endpoints configs include required fields and safe defaults.
  - No generated config contains secret-bearing literal keys/values.
  - Default endpoints array is empty.
  - Sample mode emits exactly one `GET https://example.com/health` endpoint.
  - Production-oriented templates set `allow_production_execution=false`, `allow_destructive_operation=false`, keep `max_concurrency=5`, and never include production endpoint URLs, auth refs, credentials, or aggressive schedule defaults.
- Validation tests:
  - Generated default config set passes `AuditConfigValidationService.validate_configs(..., stage="dev")` without AWS credentials.
  - Generated `prod` and `production` template config sets pass local-template validation without AWS credentials while execution-time validation still blocks production execution by default.
  - Generated sample endpoint config passes payload validation.
  - Empty endpoint array validation is explicitly covered.
- Filesystem tests:
  - Creates `<output-dir>/<client_id>/...` structure; for example `.local-configs/demo-client/client_demo_client_<shortid>/...`.
  - Existing final generated client root fails without `--overwrite` and preserves sentinel file contents.
  - `--overwrite` replaces only expected generated files under the final generated client root.
  - Existing output path that is a file fails.
  - Simulated write failure returns/raises local write error and does not report success.
- Output tests:
  - Text output includes generated IDs, root, files, warning.
  - JSON output parses and contains same fields with no extra warning text outside JSON.
- No AWS tests:
  - Monkeypatch `AwsClientFactory.__init__`, `StageConfigLoader.load`, `boto3.client`, and `boto3.Session` to raise if called; successful and locally failing `config init` paths must not trigger them.
  - Add import-boundary test that `operator_cli.config_init` does not import `storage.aws_client_factory`, `config.stage_config`, `storage.s3_client`, `storage.secrets_client`, `storage.dynamodb_client`, `storage.eventbridge_scheduler_client`, or `storage.lambda_client`.
