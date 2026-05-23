# Technical Design

## 1. Feature Overview

The internal Operator CLI `rcp` provides trusted operators with a safe command-line entry point for Phase 3 audit operations: local validation, audit metadata creation, schedule creation, manual smoke invocation, and cancellation.

This design is based on `docs/product/operator_cli_rcp_spec.md` for branch `feature/operator_cli_rcp`. The CLI must remain thin: command handlers parse arguments, format output, map controlled errors to exit codes, and delegate validation, lifecycle, storage, scheduling, naming, production safety, and invocation behavior to shared modules that future APIs or dashboards can reuse.

## 2. Product Requirements Summary

- Provide `python scripts/rcp.py audit ...` with subcommands `validate`, `create`, `schedule`, `run`, and `cancel`.
- Require `--stage <dev|staging|prod>` on every command.
- Resolve AWS resources from `config/stages/{stage}.json` with confirmed environment variable overrides; environment values take precedence over stage config file values and CLI command logic must not hardcode resource names.
- Reuse existing shared validators where present: config validation, run ID validation, lifecycle state/transition rules, scheduling rules, schedule naming, production safeguards, and sanitization.
- Add missing or incomplete behavior in shared packages, not in CLI-only code.
- Persist created configs to deterministic S3 config keys and audit metadata to DynamoDB using `PK=CLIENT#{client_id}`, `SK=AUDIT#{audit_id}`; `audit create --force` may only replace draft/failed audit configuration metadata and config objects under the confirmed lifecycle guardrails.
- Schedule only from persisted `audit_config.json` schedule blocks; skip missing or disabled blocks; rollback partial schedule creation and transition to `FAILED`.
- Invoke the orchestrator Lambda manually with `triggered_by=manual`; omit `run_id` when not supplied and validate supplied run IDs with the shared run ID policy.
- Cancel audits by cleaning up EventBridge schedules, retaining schedule metadata, transitioning to `CANCELLED` when operator intent is recorded, recording sanitized cleanup errors, and returning exit code `3` for partial cleanup failures requiring follow-up.
- Provide dry-run behavior for mutating commands and mock all AWS interactions in unit tests.
- Never store or print secrets, raw tokens, authorization headers, cookies, raw payloads, or unsanitized provider exceptions.

## 3. Requirement-to-Architecture Mapping

| Product Requirement / Acceptance Criteria | Technical Design Response |
| --- | --- |
| FR-001, AC-001 through AC-014 | Add `packages/operator_cli` with argument parsing and command dispatch only. Each command calls a shared service module and returns a structured command result. |
| FR-002, AC-015 | Add a shared `StageConfigLoader` under `packages/config/stage_config.py` to load `config/stages/{stage}.json`, apply confirmed env overrides with environment values taking precedence over file values, validate required fields, and fail before AWS client creation. |
| FR-003 | Add/reuse shared services under `packages/core`, `packages/config`, `packages/storage`, `packages/audit_scheduling`, and `packages/audit_lifecycle`; keep domain rules out of CLI command handlers. |
| FR-004, AC-001, AC-002 | Add `AuditConfigValidationService` in `packages/config/audit_validation_service.py` to validate JSON syntax, schemas/required fields, ID consistency, audit window, endpoint methods, payload strategy/safety, production restrictions, and auth references. |
| FR-005, AC-003 through AC-005 | Add `AuditCreationService` in `packages/core/audit_creation_service.py` to run shared validation, check S3 and DynamoDB conflicts, upload three config files to S3, and write or force-update `DRAFT` audit metadata only when lifecycle guardrails allow. |
| FR-006, AC-006 through AC-010 | Adapt `packages/audit_scheduling` with a reusable schedule-from-persisted-config orchestration method. It loads S3 config and DynamoDB metadata, validates lifecycle/production rules, builds definitions only from enabled schedule blocks, creates schedules, persists metadata, transitions to `SCHEDULED`, and handles rollback to `FAILED`. |
| FR-007, AC-011, AC-012 | Add `ManualRunInvocationService` in `packages/core/manual_run_service.py` to validate IDs and scenario type, validate optional run ID via `packages.core.validators.validate_run_id`, and call a mockable Lambda client wrapper. |
| FR-008, AC-013, AC-014 | Reuse/adapt `packages.audit_lifecycle.cancellation.AuditCancellationService`; add a CLI-facing shared orchestration method for dry-run and controlled cleanup-failure status mapping. |
| FR-009 | Reuse `packages.audit_scheduling.safeguards.effective_caps`, `validate_audit_window`, Phase 2 payload validators, and shared endpoint validation; add missing destructive-operation/auth-ref checks in shared config validation. |
| FR-010 | Every mutating service accepts `dry_run: bool`; dry-runs perform all validation and return intended mutations without calling mutating AWS methods. |
| FR-011, AC-016 | CLI output is produced from sanitized command result objects. Exceptions crossing the CLI boundary are controlled `EngineError` subclasses or are mapped to generic sanitized failures. |

## 4. Technical Scope

### Current Technical Scope

- CLI package and script entry point for `rcp audit` commands.
- Shared stage configuration loading and AWS client factory boundaries.
- Shared audit config validation service combining existing Phase 1/2/3 validators and new missing checks required by the product spec.
- Shared audit creation, scheduling, manual run, and cancellation orchestration services.
- Shared S3 config write support, DynamoDB audit metadata creation/update support, EventBridge schedule create/delete/disable support, and Lambda invocation wrapper.
- Dry-run support in service layer for create, schedule, run, and cancel.
- Sanitized human-readable output and optional simple `--output json`.
- Unit tests with mocked AWS clients and command parser tests.

### Out of Scope

- Customer-facing APIs, UI, dashboards, RBAC, billing, tenant onboarding, and customer documentation.
- New audit authoring UI or complex schedule inference.
- Real AWS calls in unit tests.
- Replacing Phase 1 orchestrator behavior or Phase 2 payload/safety behavior.
- Analytics, scoring, reporting, and automatic completion workflows.

### Future Technical Considerations

- Admin API/dashboard can call the same shared services behind authentication and RBAC.
- Rich machine-readable JSON output for all commands.
- Integration tests against ephemeral AWS resources.
- Status/repair/reconciliation operator commands.

## 5. Architecture Overview

### Layering

1. **Entry point:** `scripts/rcp.py` imports `packages.operator_cli.main:main` and exits with its returned status code.
2. **CLI layer:** `packages/operator_cli` owns `argparse` command definitions, command modules, output rendering, and exception-to-exit-code mapping.
3. **Shared service layer:** `packages/core`, `packages/config`, `packages/audit_scheduling`, and `packages/audit_lifecycle` own business behavior.
4. **Infrastructure boundary:** `packages/storage` wrappers own mockable S3, DynamoDB, EventBridge Scheduler, Secrets, and Lambda interactions.
5. **AWS SDK construction:** a shared client factory constructs boto3 clients only after stage config validation succeeds. Tests inject mocks and must not construct real clients.

### Validate Flow

1. CLI parses `audit validate` args and loads stage config to validate stage availability.
2. `AuditConfigValidationService.validate_files(...)` reads local JSON files.
3. Service validates syntax, required fields, cross-file IDs, window duration, endpoint methods, payload strategy/safety, auth references, and production safety.
4. CLI prints a sanitized success or validation error and returns `0` or non-zero. No AWS mutation or invocation occurs.

### Create Flow

1. CLI parses args and creates service dependencies from stage config unless dry-run can run without clients; command behavior should still validate stage config.
2. `AuditCreationService.create_from_files(...)` runs the same validation as `validate`.
3. Service computes deterministic S3 keys and config hashes.
4. Service checks both DynamoDB audit metadata and all deterministic S3 config object keys before mutation.
5. Without `--force`, service fails before any S3 upload or metadata write if any target S3 config object already exists or DynamoDB audit metadata already exists.
6. With `--force`, service first loads existing DynamoDB audit metadata and allows replacement only when existing `lifecycle_state` is `DRAFT` or `FAILED`.
7. With `--force`, service fails before mutation when existing `lifecycle_state` is `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, or `CANCELLED`.
8. `--force` does not bypass config validation, production/destructive-operation safety checks, identifier validation, or storage safety checks.
9. `--force` overwrites only the three deterministic config S3 objects and updates only audit metadata fields owned by audit creation; it must not overwrite/delete run evidence or modify existing `raw-results/*` artifacts.
10. `--force` appends a sanitized `lifecycle_history` entry with `reason=force_recreate`.
11. Dry-run returns intended S3/DynamoDB actions only.
12. Non-dry-run uploads configs and writes audit metadata with `DRAFT`.

### Schedule Flow

1. CLI parses `client_id`, `audit_id`, `stage`, `dry_run`, and `allow_production`.
2. Shared schedule service loads persisted `audit_config.json` from S3 and audit metadata from DynamoDB.
3. It validates lifecycle eligibility, audit window, production rules, and explicit `--allow-production` for `stage=prod` or production targets.
4. It normalizes product-spec schedule fields to existing Phase 3 builder inputs in a shared adapter, then builds schedule definitions only from enabled blocks.
5. Dry-run returns planned schedules and metadata updates only.
6. Non-dry-run creates schedules, stores schedule metadata, and transitions to `SCHEDULED`.
7. On partial create failure, service attempts rollback for already-created schedules, records sanitized failure/cleanup metadata, transitions to `FAILED`, and returns a controlled failure.

### Manual Run Flow

1. CLI parses IDs, scenario type, optional run ID, optional schedule type, and dry-run.
2. `ManualRunInvocationService` validates identifiers, scenario type allowlist from product spec, and supplied run ID via existing shared policy.
3. Service builds Lambda payload with `client_id`, `audit_id`, `scenario_type`, `triggered_by=manual`, optional `run_id`, and optional `schedule_type`.
4. Dry-run returns sanitized intended invocation. Non-dry-run invokes stage-configured orchestrator Lambda.

### Cancel Flow

1. CLI parses IDs, reason, dry-run, and stage.
2. Shared cancellation service loads audit metadata and validates lifecycle transition to `CANCELLED` via existing state machine.
3. Non-dry-run service records operator cancellation intent in DynamoDB using sanitized reason/history and a conditional lifecycle guard before performing cleanup. It must not claim success if this intent write fails.
4. Service deletes schedules; if delete fails, attempts disable.
5. If operator intent was successfully recorded, service transitions the audit to `CANCELLED` even when one or more schedule cleanup actions fail.
6. It retains schedule metadata, persists sanitized `cleanup_errors`, and returns a `cancelled_with_cleanup_warnings` result.
7. CLI prints a warning summary and exits with code `3` for partial cleanup failure to indicate operator follow-up is required.

## 6. System Components

### `scripts/rcp.py`

- Thin executable shim.
- Ensures repository root is importable when invoked as `python scripts/rcp.py`.
- Calls `packages.operator_cli.main.main()`.
- Does not contain command behavior or business rules.

### `packages/operator_cli/main.py`

- Builds the top-level parser: `audit validate|create|schedule|run|cancel`.
- Adds shared `--stage` and optional simple `--output {text,json}`.
- Dispatches to command modules.
- Converts command result status into process exit code.
- Catches controlled errors, sanitizes output, and avoids tracebacks unless a future debug flag is explicitly added.

### Command Modules

Suggested files:

- `packages/operator_cli/commands/audit_validate.py`
- `packages/operator_cli/commands/audit_create.py`
- `packages/operator_cli/commands/audit_schedule.py`
- `packages/operator_cli/commands/audit_run.py`
- `packages/operator_cli/commands/audit_cancel.py`

Responsibilities:

- Define command-specific arguments exactly as specified.
- Convert `argparse.Namespace` to service request objects.
- Call shared services.
- Return a sanitized `CommandResult`.
- Must not directly call boto3, S3, DynamoDB, EventBridge, Lambda, lifecycle transition code, schedule builders, or config validators except through shared service APIs.

### `packages/config/stage_config.py`

New shared module.

Responsibilities:

- Validate `stage in {dev,staging,prod}`.
- Load `config/stages/{stage}.json`.
- Apply environment overrides after loading the JSON file; non-empty environment values override stage config file values.
- Validate required fields before client construction:
  - `region`
  - `aws_profile`
  - `config_bucket`
  - `audit_metadata_table`
  - `orchestrator_function_name`
  - `scheduler_group_name`
  - `schedule_name_prefix`
- Return an immutable/typed stage config object including resolved values and optional provenance metadata useful for diagnostics (`file` vs `environment`) without printing sensitive data.

Confirmed environment variable names:

| Field | Override |
| --- | --- |
| `region` | `RCP_AWS_REGION` |
| `aws_profile` | `RCP_AWS_PROFILE` |
| `config_bucket` | `RCP_CONFIG_BUCKET` |
| `audit_metadata_table` | `RCP_AUDIT_METADATA_TABLE` |
| `orchestrator_function_name` | `RCP_ORCHESTRATOR_FUNCTION_NAME` |
| `scheduler_group_name` | `RCP_SCHEDULER_GROUP_NAME` |
| `schedule_name_prefix` | `RCP_SCHEDULE_NAME_PREFIX` |

Resolution precedence is: command `--stage` selects the stage file, `config/stages/{stage}.json` supplies defaults, and non-empty confirmed environment variables override matching file values. Empty override values are invalid and must not mask JSON config values; treat an explicitly set empty string as a configuration error rather than falling back silently.

### `packages/config/audit_validation_service.py`

New shared module.

Responsibilities:

- Load local JSON files for validate/create.
- Validate JSON syntax and object/list top-level shapes.
- Reuse existing `packages.config.validators.validate_audit_config` and `validate_endpoint_config`.
- Reuse Phase 2 payload validation through existing endpoint validator.
- Reuse `packages.audit_scheduling.safeguards.validate_audit_window` and `effective_caps`.
- Validate `client_id` and `audit_id` consistency across files.
- Validate `auth_ref` presence when endpoint/config declares authentication required.
- Validate production restrictions including 48-hour max, production allow flag, destructive operation allow flag, allowed endpoint methods, payload safety, concurrency, and request caps.
- Return normalized configs plus derived IDs and config hashes.

### `packages/core/audit_creation_service.py`

New shared service.

Responsibilities:

- Run `AuditConfigValidationService`.
- Check for existing audit metadata and deterministic S3 config objects before mutation.
- Enforce exact create conflict behavior:
  - `force=false`: fail if any target S3 config object exists or audit metadata exists.
  - `force=true`: require existing metadata state to be `DRAFT` or `FAILED`; fail for `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, or `CANCELLED`.
- Upload configs to deterministic keys; overwrite these config keys only when `force=true` and lifecycle guardrails pass.
- Write audit metadata item with `DRAFT` lifecycle state, config hashes, config version when available, created/updated timestamps, and empty schedule metadata for first create.
- For force recreate, update creation-owned metadata fields, set `lifecycle_state` to `DRAFT`, and append a `lifecycle_history` entry with `reason=force_recreate`.
- Never delete or overwrite run evidence and never modify existing `raw-results/*` artifacts.
- Support dry-run without S3/DynamoDB mutation.

### `packages/audit_scheduling` Adaptations

Existing modules already provide lifecycle-aware scheduling, schedule naming, rollback, audit-window validation, scenario taxonomy, production caps, and EventBridge schedule construction. Adaptations must be shared and not CLI-specific:

- Add `schedule_from_persisted_audit(client_id, audit_id, stage_config, allow_production, dry_run)` orchestration or equivalent service method.
- Add a shared normalization adapter for product-spec schedule blocks:
  - `audit_window.start_at` / `audit_window.end_at` map to existing `start_time` / `end_time` validator inputs.
  - `baseline_schedule` maps to existing baseline builder input.
  - `repeated_schedule` maps to existing repeated builder input.
  - `burst_schedule` remains compatible where possible.
  - `finalization_schedule` controls whether finalization is built; existing Phase 3 always builds finalization, so the builder must be adapted to skip when missing or disabled for CLI scheduling to satisfy AC-008-like schedule block behavior.
- Use existing `schedule_name` convention and deterministic truncation; incorporate `stage_config.schedule_name_prefix` only in the shared naming helper if product confirmation requires replacing the hardcoded `rcp` prefix.
- Ensure scheduler group name from stage config is included in EventBridge calls and persisted schedule metadata.

### `packages/core/manual_run_service.py`

New shared service.

Responsibilities:

- Validate `client_id`, `audit_id`, `scenario_type`, optional `schedule_type`, and optional `run_id`.
- Build sanitized Lambda payload.
- Invoke a mockable Lambda wrapper unless dry-run.
- Return sanitized invocation status and request summary.

### `packages/storage` Adaptations

Required additions/adaptations:

- `S3StorageClient.write_json(key, payload, overwrite=False)` for config upload.
- `S3StorageClient.exists(key)` or equivalent object-head helper for preflight conflict checks on deterministic config objects.
- `S3StorageClient.read_json(key)` already exists and should be reused.
- `AuditMetadataRepository.put_audit_metadata_once(...)` already exists and should be reused for create.
- Add `AuditMetadataRepository.update_for_force_recreate(...)` or equivalent conditional update helper that only succeeds when existing `lifecycle_state IN (DRAFT, FAILED)` and appends `lifecycle_history.reason=force_recreate` atomically.
- `EventBridgeSchedulerClient` must pass `GroupName=stage_config.scheduler_group_name` on create/delete/disable when configured.
- Add `LambdaInvocationClient.invoke(function_name, payload, invocation_type)` wrapper.
- Add `AwsClientFactory` or equivalent shared factory that uses stage config and supports dependency injection for tests.

## 7. Data Models

## Audit Metadata

### Purpose

Tracks audit-level lifecycle state, persisted config metadata, schedule metadata, cleanup errors, and transition history.

### Primary Key

- `PK = CLIENT#{client_id}`
- `SK = AUDIT#{audit_id}`

### Fields

| Field | Type | Description |
| --- | --- | --- |
| `client_id` | string | Validated client identifier. |
| `audit_id` | string | Validated audit identifier. |
| `lifecycle_state` | string | Existing lifecycle state; create writes `DRAFT`. |
| `lifecycle_history` | list | Append-only sanitized transition entries. Force recreate appends an entry with `reason=force_recreate`. |
| `config_hash` | string/object | Hash of persisted configs when available. |
| `config_version` | string | Version from config when available. |
| `config_s3_keys` | object | Deterministic S3 paths for client, audit, and endpoints configs. |
| `audit_window` | object | Normalized audit window. |
| `schedules` | list | Sanitized EventBridge schedule metadata retained through cancellation. |
| `cleanup_errors` | list | Sanitized cleanup/rollback failure records. |
| `created_at` | string | UTC ISO timestamp. |
| `updated_at` | string | UTC ISO timestamp. |
| `cancel_reason` | string | Optional sanitized cancellation reason. |

### Ownership Model

All audit metadata is scoped by `client_id` and `audit_id`. CLI operators are trusted internal users; application-level RBAC is out of scope.

### Lifecycle

- Created by `audit create` as `DRAFT`.
- Force-updated by `audit create --force` only when current state is `DRAFT` or `FAILED`; force recreate must not be allowed from `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, or `CANCELLED`.
- Updated by `audit schedule` to `SCHEDULED` or `FAILED`.
- Updated by `audit cancel` to `CANCELLED` when transition is valid.
- Terminal states remain terminal per existing state machine.

## Config Objects in S3

### Purpose

Persist the audit source of truth used by scheduling and orchestrator execution.

### Primary Key

S3 object keys:

- `configs/{client_id}/client_config.json`
- `configs/{client_id}/audits/{audit_id}/audit_config.json`
- `configs/{client_id}/audits/{audit_id}/endpoints.json`

### Fields

JSON payloads are the validated source files. Secrets must be references only.

### Lifecycle

Written by `audit create`. Without `--force`, existing target config objects fail the command before mutation. With `--force`, only these deterministic config objects may be overwritten after DynamoDB lifecycle guardrails pass:

- `configs/{client_id}/client_config.json`
- `configs/{client_id}/audits/{audit_id}/audit_config.json`
- `configs/{client_id}/audits/{audit_id}/endpoints.json`

`audit create --force` must not delete, overwrite, or otherwise modify run evidence, generated reports, schedule execution artifacts, or any `raw-results/*` objects.

## Stage Config

### Purpose

Resolve AWS resources and stage-specific settings without hardcoding names in CLI command logic.

### Primary Key

Local file path: `config/stages/{stage}.json`.

### Fields

See `packages/config/stage_config.py` component above.

### Lifecycle

Maintained as repository configuration. Missing/malformed values fail commands before AWS client construction.

## 8. API Contracts

No public HTTP API is introduced. The implementation should define stable internal service contracts that future APIs/dashboards can call.

## Internal Contract: `StageConfigLoader.load`

### Purpose

Resolve the effective stage configuration before AWS client construction.

### Request Parameters

- `stage: dev|staging|prod`
- `env: Mapping[str, str]` defaults to process environment.

### Response Body

```json
{
  "stage": "dev",
  "region": "us-east-1",
  "aws_profile": "rcp-dev",
  "config_bucket": "rcp-dev-config",
  "audit_metadata_table": "rcp-dev-audit-metadata",
  "orchestrator_function_name": "rcp-dev-orchestrator",
  "scheduler_group_name": "rcp-dev-schedules",
  "schedule_name_prefix": "rcp-dev"
}
```

### Validation Rules

- Load defaults from `config/stages/{stage}.json`.
- Apply confirmed overrides after file load: `RCP_AWS_REGION`, `RCP_AWS_PROFILE`, `RCP_CONFIG_BUCKET`, `RCP_AUDIT_METADATA_TABLE`, `RCP_ORCHESTRATOR_FUNCTION_NAME`, `RCP_SCHEDULER_GROUP_NAME`, and `RCP_SCHEDULE_NAME_PREFIX`.
- Environment values override stage config file values.
- Missing required resolved fields fail before AWS client construction.
- Empty environment override values fail as configuration errors and must not silently fall back to file values.

### Side Effects

Reads local config and environment only; constructs no AWS clients.

## Internal Contract: `AuditConfigValidationService.validate_files`

### Purpose

Validate local config files without side effects.

### Authentication / Authorization

Internal process only; no auth/RBAC in scope.

### Request Parameters

- `client_config_path: str`
- `audit_config_path: str`
- `endpoints_config_path: str`
- `stage_config: StageConfig`

### Response Body

```json
{
  "client_id": "client-a",
  "audit_id": "audit-2026-01",
  "client_config": {},
  "audit_config": {},
  "endpoints_config": {},
  "config_hash": "sha256:...",
  "config_version": "optional"
}
```

### Error Status Codes

Not HTTP. Raise controlled `ConfigError` or `ValidationError` with sanitized messages.

### Side Effects

None.

### Idempotency / Duplicate Handling

Pure validation; repeat calls are deterministic for identical inputs.

## Internal Contract: `AuditCreationService.create_from_files`

### Purpose

Validate and persist an audit draft.

### Request Parameters

- Validation file paths.
- `stage_config: StageConfig`
- `dry_run: bool`
- `force: bool = false`

### Response Body

```json
{
  "status": "created|force_recreated|dry_run",
  "client_id": "client-a",
  "audit_id": "audit-2026-01",
  "lifecycle_state": "DRAFT",
  "s3_keys": {
    "client_config": "configs/client-a/client_config.json",
    "audit_config": "configs/client-a/audits/audit-2026-01/audit_config.json",
    "endpoints": "configs/client-a/audits/audit-2026-01/endpoints.json"
  }
}
```

### Side Effects

Writes S3 config objects and DynamoDB metadata unless dry-run. Non-force create performs conditional writes only. Force recreate overwrites only deterministic config S3 objects and conditionally updates DynamoDB metadata when the existing lifecycle state is `DRAFT` or `FAILED`.

### Validation Rules

- Always execute full config validation and safety validation before mutation, regardless of `force`.
- Check all deterministic config S3 object keys and DynamoDB audit metadata before mutation.
- `force=false`: fail if any target S3 config object exists or DynamoDB audit metadata exists.
- `force=true`: require existing DynamoDB audit metadata and require `lifecycle_state` to be `DRAFT` or `FAILED`.
- `force=true`: fail if `lifecycle_state` is `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, or `CANCELLED`.
- `force=true`: do not bypass production safety, destructive operation safety, auth reference validation, identifier validation, S3 key allowlist checks, or DynamoDB conditional update checks.

### Idempotency / Duplicate Handling

Without `--force`, existing S3 config objects or existing audit metadata fail before overwrites. With `--force`, repeated requests are permitted only while the existing audit remains `DRAFT` or `FAILED`; each successful force recreate overwrites the deterministic config objects, updates audit metadata, and appends a new sanitized `lifecycle_history` entry with `reason=force_recreate`.

### Storage Guardrails

- The service may write only these config keys: `configs/{client_id}/client_config.json`, `configs/{client_id}/audits/{audit_id}/audit_config.json`, and `configs/{client_id}/audits/{audit_id}/endpoints.json`.
- The service must not list-and-delete prefixes as part of create or force recreate.
- The service must not overwrite or delete existing run evidence, generated reports, scheduler execution artifacts, or `raw-results/*` artifacts.
- S3 writes should use explicit key allowlisting rather than broad prefix operations.
- DynamoDB updates for force recreate must be conditional on the allowed lifecycle states to protect against races.

## Internal Contract: `AuditSchedulingService.schedule_from_persisted_audit`

### Purpose

Create EventBridge schedules from persisted audit config and transition audit lifecycle.

### Request Parameters

- `client_id: str`
- `audit_id: str`
- `stage_config: StageConfig`
- `allow_production: bool`
- `dry_run: bool`

### Response Body

```json
{
  "status": "scheduled|dry_run",
  "client_id": "client-a",
  "audit_id": "audit-2026-01",
  "lifecycle_state": "SCHEDULED",
  "schedules": [
    {
      "schedule_name": "rcp-dev-client-a-audit-2026-01-baseline-baseline_health",
      "schedule_type": "baseline",
      "status": "created|planned"
    }
  ]
}
```

### Side Effects

Creates EventBridge schedules and updates DynamoDB unless dry-run. On partial failure, attempts rollback and transitions to `FAILED`.

### Idempotency / Duplicate Handling

Repeated scheduling should fail if lifecycle state is not eligible or if schedule names already exist, returning a controlled sanitized error.

## Internal Contract: `ManualRunInvocationService.invoke_manual_run`

### Purpose

Invoke the orchestrator Lambda for smoke testing.

### Request Parameters

- `client_id: str`
- `audit_id: str`
- `scenario_type: baseline_health|burst_stability|repeated_stability|response_consistency`
- `stage_config: StageConfig`
- `run_id: str | None`
- `schedule_type: manual|baseline|burst|repeated | None`
- `dry_run: bool`

### Response Body

```json
{
  "status": "invoked|dry_run",
  "client_id": "client-a",
  "audit_id": "audit-2026-01",
  "scenario_type": "baseline_health",
  "triggered_by": "manual",
  "run_id_supplied": false
}
```

### Side Effects

Invokes Lambda unless dry-run. The CLI performs no direct audit metadata mutation.

### Idempotency / Duplicate Handling

The orchestrator owns duplicate run ID behavior. The service validates supplied run IDs before invocation.

## Internal Contract: `AuditCancellationService.cancel`

### Purpose

Clean up schedules and transition an audit to `CANCELLED`.

### Request Parameters

- `client_id: str`
- `audit_id: str`
- `stage_config: StageConfig`
- `reason: str | None`
- `dry_run: bool`

### Response Body

```json
{
  "status": "cancelled|cancelled_with_cleanup_warnings|dry_run",
  "client_id": "client-a",
  "audit_id": "audit-2026-01",
  "lifecycle_state": "CANCELLED",
  "cleanup_errors": []
}
```

### Side Effects

Deletes/disables schedules and updates DynamoDB unless dry-run. If operator intent is recorded and schedule cleanup partially fails, the service still persists `lifecycle_state=CANCELLED`, retains schedule metadata, and persists sanitized `cleanup_errors`.

### Error / Warning Mapping

- Full success: return `status=cancelled`; CLI exits `0`.
- Dry-run success: return `status=dry_run`; CLI exits `0`.
- Partial cleanup failure after operator intent was successfully recorded: return `status=cancelled_with_cleanup_warnings`; CLI prints a warning summary and exits `3`.
- Validation, lifecycle, metadata load, or failure to record operator intent: return/raise a controlled failure; CLI exits `1` and must not claim cancellation succeeded.

### Idempotency / Duplicate Handling

Terminal audits must follow existing lifecycle transition rules; repeated cancellation of an already-cancelled audit returns controlled failure unless product later requests idempotent success.

## 9. Frontend Impact

No customer-facing frontend work is in scope.

### Components Affected

- None under `apps/frontend`.

### API Integration

- None.

### UI States

- Not applicable.

## 10. Backend Logic

### Responsibilities

- Validate and normalize local/persisted configs.
- Resolve stage resources before constructing AWS clients.
- Persist config and metadata safely.
- Enforce lifecycle transitions and production safety.
- Create, rollback, delete, and disable schedules through mockable wrappers.
- Invoke the orchestrator Lambda through a mockable wrapper.
- Sanitize all outputs, logs, and persisted failure metadata.

### Validation Flow

1. Validate CLI arguments with `argparse` choices and required flags.
2. Validate stage and resolve effective stage config from `config/stages/{stage}.json` plus confirmed environment overrides; environment values take precedence and empty override values are errors.
3. Validate identifiers using shared `validate_identifier`.
4. Validate config syntax and semantic requirements using shared config validation service.
5. Validate audit window with 48-hour max.
6. Validate lifecycle eligibility using `LifecycleStateMachine`.
7. Validate run ID using `validate_run_id` only when supplied.
8. Validate production scheduling guard with both config-level allow and CLI `--allow-production`.

### Business Rules

- `audit validate` has no AWS mutation/invocation side effects.
- `audit create` always runs validation first and writes `DRAFT`; it never schedules or starts execution.
- `audit create` without `--force` fails on any existing target S3 config object or existing DynamoDB audit metadata.
- `audit create --force` is allowed only from existing `DRAFT` or `FAILED`, overwrites only deterministic config S3 objects, updates audit metadata, appends `lifecycle_history.reason=force_recreate`, and must not modify run evidence or `raw-results/*` artifacts.
- `audit schedule` loads schedule definitions only from persisted `audit_config.json`; missing/disabled blocks are skipped and no replacement schedules are inferred.
- `audit run` always sets `triggered_by=manual`; omitted `run_id` stays omitted.
- `audit cancel` retains schedule metadata even after cleanup; if cleanup partially fails after operator intent is recorded, it persists `CANCELLED`, stores `cleanup_errors`, prints warnings, and exits `3`.
- `SCHEDULED_WITH_ERRORS` must never be persisted.

### Persistence Flow

- Config upload uses S3 JSON writes to deterministic keys.
- Audit metadata writes use DynamoDB conditional puts/updates.
- Non-force create uses conditional S3/DynamoDB conflict checks before mutation and must fail if existing config objects or metadata are present.
- Force recreate uses an explicit S3 config-key allowlist and a DynamoDB conditional update on `lifecycle_state IN (DRAFT, FAILED)`.
- Lifecycle updates append sanitized history entries atomically.
- Schedule metadata is sanitized before storage.
- Cleanup and rollback errors store controlled error codes, schedule name/type, action, and timestamp only.

### Error Handling

CLI exit code mapping:

| Code | Meaning |
| --- | --- |
| `0` | Success, including dry-run success. |
| `1` | Controlled validation/config/lifecycle/storage/invocation failure. |
| `2` | Argument parsing error from `argparse`. |
| `3` | Partial cleanup failure for `audit cancel` where operator intent was recorded, `CANCELLED` was persisted, sanitized `cleanup_errors` were stored in DynamoDB, and operator follow-up is required. |

All provider exceptions must be wrapped in controlled `EngineError` subclasses with sanitized messages before reaching CLI output.

## 11. File Structure

Recommended implementation layout:

```text
scripts/
  rcp.py

packages/
  operator_cli/
    __init__.py
    main.py
    output.py
    results.py
    commands/
      __init__.py
      audit_validate.py
      audit_create.py
      audit_schedule.py
      audit_run.py
      audit_cancel.py

  config/
    stage_config.py
    audit_validation_service.py
    loaders.py
    validators.py

  core/
    audit_creation_service.py
    manual_run_service.py
    aws_client_factory.py
    exceptions.py
    validators.py

  storage/
    s3_client.py
    audit_metadata_client.py
    eventbridge_scheduler_client.py
    lambda_client.py

  audit_scheduling/
    service.py
    builders.py
    product_config_adapter.py
    safeguards.py
    validators.py

  audit_lifecycle/
    cancellation.py
    service.py
    state_machine.py

config/
  stages/
    dev.json
    staging.json
    prod.json

docs/
  operator-cli/README.md
```

Existing `packages/storage/eventbridge_scheduler_client.py` currently lives under storage, not `packages/scheduler`; keep it there to align with repository convention unless a broader refactor is explicitly approved.

## 12. Security

- The CLI is internal/operator-only; no new auth/RBAC is introduced.
- Stage config may contain resource names and profile names only; it must not contain secrets.
- Config files must not contain literal secrets. Existing secret-ref validation must be reused and expanded for `auth_ref` requirements.
- CLI output and logs must pass through `packages.sanitization.sanitizer.sanitize`.
- Do not print raw AWS exception messages, request payloads, headers, cookies, tokens, or credentials.
- Manual run payloads must contain only identifiers and control metadata.
- EventBridge target payloads must remain secret-free and omit `run_id` for scheduled executions.
- Production scheduling requires both config-level production allow and CLI `--allow-production`.

## 13. Reliability

- Stage config validation is fail-fast before AWS client construction.
- Dry-runs validate as much as real runs and perform no mutations.
- DynamoDB writes that create metadata should be conditional to prevent accidental overwrite.
- Force recreate must use a DynamoDB conditional update to prevent races if audit lifecycle advances after preflight checks.
- Force recreate must use explicit S3 key writes only; do not use broad prefix deletes/copies or operations that could affect run evidence.
- Lifecycle transitions should use conditional updates to avoid races.
- Schedule creation is all-or-fail; rollback attempts delete first, then disable.
- Cancellation delete failures should attempt disable before recording cleanup error; if cleanup still partially fails after operator intent was recorded, persist `CANCELLED`, persist sanitized `cleanup_errors`, and surface exit code `3`.
- No retry loops are required in CLI service code for MVP; rely on AWS SDK defaults unless product later requires explicit retry policy.
- Logs should include sanitized command name, stage, client ID, audit ID, action status, and controlled error code.
- Unit tests must inject fake clients and assert no real boto3 clients are constructed in service tests.

## 14. Dependencies

- Python 3.11 project conventions from `pyproject.toml`.
- Existing `boto3`/`botocore` dependency.
- Existing Phase 1 orchestrator event/run ID validation and Lambda handler behavior.
- Existing Phase 2 payload strategy and payload safety validators.
- Existing Phase 3 lifecycle, schedule builder, scheduler client, metadata repository, cancellation service, safeguards, and taxonomy.
- New local stage config files under `config/stages/`.

## 15. Assumptions

### Confirmed Requirements and Decisions

- The CLI is internal only.
- Every command requires `--stage`.
- `--allow-production` is mandatory for production scheduling even when config has production allow.
- Dry-runs validate inputs and lifecycle before reporting intended mutations.
- `--output json` is optional and should be simple if implemented.
- Environment overrides are `RCP_AWS_REGION`, `RCP_AWS_PROFILE`, `RCP_CONFIG_BUCKET`, `RCP_AUDIT_METADATA_TABLE`, `RCP_ORCHESTRATOR_FUNCTION_NAME`, `RCP_SCHEDULER_GROUP_NAME`, and `RCP_SCHEDULE_NAME_PREFIX`; environment values override stage config file values.
- `audit create --force` may overwrite deterministic config S3 objects and update DynamoDB audit metadata only when existing `lifecycle_state` is `DRAFT` or `FAILED`; it must append `lifecycle_history.reason=force_recreate` and must not modify run evidence or `raw-results/*` artifacts.
- Partial cancellation cleanup failure after operator intent is recorded persists `CANCELLED`, stores sanitized `cleanup_errors`, prints warnings, and exits `3`.

### Technical Assumptions Requiring Confirmation

- Manual `audit run --stage prod` does not require a CLI `--allow-production` flag because the product spec only mandates it for scheduling; production execution is still constrained by persisted config/orchestrator safeguards.
- Existing Phase 3 config field names (`start_time`, `baseline`, `repeated`) and product-spec names (`start_at`, `baseline_schedule`, `repeated_schedule`, `finalization_schedule`) must be reconciled in a shared adapter rather than in CLI code.
- `schedule_name_prefix` from stage config may need to replace or parameterize the existing hardcoded `rcp` schedule prefix.

## 16. Risks / Open Questions

- Existing scheduling code always creates finalization and uses some field names that differ from the Operator CLI spec; implementation must adapt shared scheduling logic carefully to avoid breaking Phase 3 tests.
- Existing `EventBridgeSchedulerClient.create_schedule` does not currently pass scheduler group name; required for stage-aware scheduling.
- Existing `S3StorageClient` lacks JSON config write support.
- Existing `pyproject.toml` only includes `packages*`; console script support would require packaging changes and is optional.

## 17. Implementation Notes

- Prefer `argparse` from the standard library to keep dependencies minimal.
- Add tests under `tests/operator_cli/` for parser behavior, output behavior, and command-service dispatch.
- Add service tests with fake S3, DynamoDB, Scheduler, and Lambda clients; assert dry-runs perform no mutating calls.
- Add validation tests for invalid JSON, mismatched IDs, audit window exactly 48h, audit window >48h, malformed/disabled schedule blocks, invalid run ID, missing stage config field, confirmed environment override precedence, empty environment override rejection, force recreate lifecycle guards, force recreate storage allowlist behavior, cancellation cleanup warning persistence, exit code `3`, and sanitized provider errors.
- Use `packages.sanitization.sanitizer.sanitize` at service boundaries before persistence/output.
- Keep command modules thin enough that future API handlers can import the same shared service methods without importing CLI modules.
- Do not add real AWS integration tests as part of this feature.
