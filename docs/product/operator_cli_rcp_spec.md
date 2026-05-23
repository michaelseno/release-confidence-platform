# Product Specification

## 1. Feature Overview

The internal Operator CLI `rcp` is a thin command-line tool for Phase 3 audit operations. It enables trusted platform operators to validate audit configuration files, create draft audit metadata, schedule audits, manually invoke audit runs for smoke testing, and cancel audits.

The CLI must delegate business rules to shared modules and schemas. It must not become the source of truth for config validation, lifecycle transitions, run ID validation, AWS naming conventions, production safety rules, or schedule generation rules.

Minimum invocation must support:

```bash
python scripts/rcp.py ...
```

Preferred invocation may additionally support a console script:

```bash
rcp ...
```

This feature is an internal operator tool only and is not customer-facing.

## 2. Problem Statement

Phase 3 requires repeatable, safe operational workflows for audit validation, audit creation, scheduling, manual smoke execution, and cancellation. Without a dedicated operator CLI, operators must directly manipulate S3 objects, DynamoDB records, EventBridge schedules, and Lambda invocations, which increases risk of invalid metadata, unsafe production execution, inconsistent lifecycle transitions, and unreproducible validation.

The `rcp` CLI solves this by providing a controlled operator entry point that uses the same shared validation and service modules future admin APIs or dashboards can reuse.

## 3. User Persona / Target User

- **Technical operator / maintainer:** Runs approved Phase 3 operational commands against dev, staging, or production environments.
- **Platform engineer:** Implements and maintains shared validation, storage, scheduling, and invocation services consumed by the CLI.
- **QA engineer:** Validates CLI behavior with mocked AWS dependencies and confirms no real AWS calls occur in unit tests.

## 4. User Stories

- As a technical operator, I want to validate audit configuration files locally before upload so that invalid audits are rejected before they affect shared runtime resources.
- As a technical operator, I want to create a draft audit from approved config files so that runtime configuration and metadata are persisted consistently.
- As a technical operator, I want to schedule an audit from persisted configuration so that EventBridge schedules are created only from the audit source of truth.
- As a technical operator, I want to manually invoke an audit scenario so that I can smoke test orchestration without creating schedules.
- As a technical operator, I want to cancel an audit so that active schedules are disabled or deleted while audit traceability remains intact.
- As a platform engineer, I want CLI business behavior to be implemented in shared modules so that future admin APIs and dashboards do not duplicate CLI-only logic.
- As a QA engineer, I want each CLI command to have deterministic dry-run and failure behavior so that validation can be automated with mocks.

## 5. Goals / Success Criteria

The feature is successful when:

- Operators can execute `validate`, `create`, `schedule`, `run`, and `cancel` audit commands using a consistent `--stage` argument.
- Validation failures return a non-zero exit code and do not upload configs, write DynamoDB records, create schedules, or invoke Lambda.
- Audit creation persists configs to deterministic S3 paths and writes audit metadata with lifecycle state `DRAFT`.
- Audit scheduling uses only persisted `audit_config.json` schedule definitions and transitions eligible audits to `SCHEDULED`.
- Partial schedule creation failure attempts rollback, records sanitized failure metadata, transitions the audit to `FAILED`, and never persists `SCHEDULED_WITH_ERRORS`.
- Manual run invocation calls the existing orchestrator path with `triggered_by=manual` and respects the existing run ID policy when a run ID is supplied.
- Audit cancellation attempts schedule cleanup, retains schedule metadata, transitions the audit to `CANCELLED` when operator intent is recorded, records sanitized `cleanup_errors` when cleanup fails, and exits with status `3` for partial cleanup failure.
- AWS resources are resolved from stage config files with explicitly named environment variable overrides allowed.
- Unit tests cover argument parsing, validation command behavior, create/schedule/cancel dry-runs, and AWS interactions using mocks only.

## 6. Feature Scope

### In Scope

- Internal CLI command group: `rcp audit`.
- Commands:
  - `rcp audit validate`
  - `rcp audit create`
  - `rcp audit schedule`
  - `rcp audit run`
  - `rcp audit cancel`
- Required and optional command arguments listed in this specification.
- Stage-aware AWS resource resolution from:
  - `config/stages/dev.json`
  - `config/stages/staging.json`
  - `config/stages/prod.json`
- Environment variable overrides for stage config values.
- Shared config schema loading and validation.
- Shared lifecycle state and transition enforcement.
- Shared run ID validation policy.
- Shared production safety checks.
- S3 config upload for audit creation.
- DynamoDB audit metadata writes and updates.
- EventBridge Scheduler schedule creation and cleanup.
- Manual Lambda orchestrator invocation.
- Dry-run behavior for create, schedule, run, and cancel.
- Human-readable CLI output.
- `--output json` support if simple to implement without expanding scope.
- Documentation in:
  - `docs/operator-cli/README.md`
  - `packages/operator_cli/README.md`
- Unit tests with mocked AWS dependencies.

### Out of Scope

- Customer-facing UI, API, or self-service workflow.
- Customer-facing documentation.
- Authentication, RBAC, billing, subscriptions, or tenant onboarding.
- New audit authoring UI.
- Complex schedule inference beyond schedule blocks explicitly present in `audit_config.json`.
- Direct storage of secrets in CLI arguments, config files, logs, or command output.
- Real AWS calls in unit tests.
- Replacing existing Phase 1 orchestrator behavior.
- Replacing existing Phase 2 payload strategy, payload safety, endpoint safety, or data generation behavior.
- Analytics, scoring, reporting, or automatic completion workflows.
- Root README changes except adding links to operator CLI docs if the README is otherwise touched.

### Future Considerations

- Admin API or dashboard that reuses the same shared service modules.
- Rich structured JSON output for every command.
- Integration test suite against ephemeral AWS resources.
- Operator command for audit status inspection.

## 7. Functional Requirements

### FR-001: CLI Entry Point and Command Structure

The system must provide an internal CLI with command group `audit` and subcommands `validate`, `create`, `schedule`, `run`, and `cancel`.

The minimum supported invocation must be `python scripts/rcp.py ...`. A console script named `rcp` may be added if it is low effort.

### FR-002: Stage Resolution

Every command must require `--stage <dev|staging|prod>`.

Stage resource resolution must primarily read `config/stages/{stage}.json`. Each stage config must define:

- `region`
- `aws_profile`
- `config_bucket`
- `audit_metadata_table`
- `orchestrator_function_name`
- `scheduler_group_name`
- `schedule_name_prefix`

Environment variable overrides replace individual stage config values. Missing required stage values must fail fast before AWS client construction.

Supported environment variable overrides are:

| Stage config field | Environment override |
| --- | --- |
| `region` | `RCP_AWS_REGION` |
| `aws_profile` | `RCP_AWS_PROFILE` |
| `config_bucket` | `RCP_CONFIG_BUCKET` |
| `audit_metadata_table` | `RCP_AUDIT_METADATA_TABLE` |
| `orchestrator_function_name` | `RCP_ORCHESTRATOR_FUNCTION_NAME` |
| `scheduler_group_name` | `RCP_SCHEDULER_GROUP_NAME` |
| `schedule_name_prefix` | `RCP_SCHEDULE_NAME_PREFIX` |

When both a stage config file value and the corresponding environment variable are present, the environment variable value must be used.

### FR-003: Thin CLI and Shared Source of Truth

The CLI must call shared modules for config validation, lifecycle state validation, lifecycle transition validation, run ID validation, AWS naming conventions, production restriction checks, and schedule construction.

CLI argument parsing may live in the CLI package, but domain rules must not be implemented only in CLI command handlers.

Recommended shared module structure includes:

- `packages/config/{validators.py,loaders.py,schemas/}`
- `packages/storage/{s3_client.py,dynamodb_client.py,secrets_client.py}`
- `packages/scheduler/eventbridge_scheduler_client.py`
- `packages/core/{models,constants,exceptions}`
- `packages/operator_cli/...`
- `scripts/rcp.py`

### FR-004: `rcp audit validate`

Command arguments:

- Required: `--client-config <path>`
- Required: `--audit-config <path>`
- Required: `--endpoints-config <path>`
- Required: `--stage <dev|staging|prod>`

The command must validate JSON syntax, schema, required fields, `client_id` and `audit_id` consistency across provided files, audit window duration less than or equal to 48 hours, endpoint methods, payload strategy, payload safety, production restrictions, and `auth_ref` presence when authentication is required.

The command must not upload files, write DynamoDB records, create schedules, or invoke Lambda.

The command must exit non-zero on validation failure.

### FR-005: `rcp audit create`

Command arguments:

- Required: `--client-config <path>`
- Required: `--audit-config <path>`
- Required: `--endpoints-config <path>`
- Required: `--stage <dev|staging|prod>`
- Optional: `--dry-run`
- Optional: `--force`, default `false`

The command must run the same validation as `rcp audit validate` before persistence.

On non-dry-run success, it must upload configs to:

- `configs/{client_id}/client_config.json`
- `configs/{client_id}/audits/{audit_id}/audit_config.json`
- `configs/{client_id}/audits/{audit_id}/endpoints.json`

It must write DynamoDB audit metadata with:

- `PK=CLIENT#{client_id}`
- `SK=AUDIT#{audit_id}`
- `lifecycle_state=DRAFT`
- `config_hash` when available
- `config_version` when available

It must not create EventBridge schedules or start execution.

If any target S3 config object already exists and `--force` is not supplied, the command must fail without overwriting existing persisted resources.

If audit metadata already exists and `--force` is not supplied, the command must fail without overwriting existing persisted resources.

When `--force` is supplied, the command may recreate an existing audit only when the existing DynamoDB audit metadata has `lifecycle_state=DRAFT` or `lifecycle_state=FAILED`.

When `--force` is supplied and the existing audit is eligible for recreation, the command must:

- run the same validation and safety checks as normal create before persistence
- overwrite the three S3 config objects listed in this requirement
- update DynamoDB audit metadata for the audit with `lifecycle_state=DRAFT`
- append a `lifecycle_history` entry with `reason=force_recreate`
- preserve existing run evidence
- preserve existing `raw-results/*` artifacts

When `--force` is supplied, the command must not bypass validation or safety checks.

When `--force` is supplied, the command must fail without overwriting S3 config objects or updating DynamoDB metadata if existing audit metadata is missing, has no lifecycle state, or has lifecycle state `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, or `CANCELLED`.

### FR-006: `rcp audit schedule`

Command arguments:

- Required: `--client-id <client_id>`
- Required: `--audit-id <audit_id>`
- Required: `--stage <dev|staging|prod>`
- Optional: `--dry-run`
- Optional: `--allow-production`

The command must load `audit_config.json` from S3 and audit metadata from DynamoDB.

It must validate that the current lifecycle state allows scheduling, the audit window is valid, production restrictions are satisfied, and production scheduling includes explicit `--allow-production` when the stage or audit target is production.

It must create schedules only from `audit_config.json` fields:

- `audit_window.start_at`
- `audit_window.end_at`
- `timezone`
- `baseline_schedule`
- `burst_schedule`
- `repeated_schedule`
- `finalization_schedule`

If a schedule block is missing or disabled, the command must not create that schedule type.

On success, it must store schedule metadata in DynamoDB and transition the audit lifecycle state to `SCHEDULED`.

On partial schedule creation failure, it must attempt rollback for created schedules, record sanitized failure metadata, transition the audit lifecycle state to `FAILED`, and return a non-zero exit code.

### FR-007: `rcp audit run`

Command arguments:

- Required: `--client-id <client_id>`
- Required: `--audit-id <audit_id>`
- Required: `--scenario-type <baseline_health|burst_stability|repeated_stability|response_consistency>`
- Required: `--stage <dev|staging|prod>`
- Optional: `--run-id <safe_run_id>`
- Optional: `--schedule-type <manual|baseline|burst|repeated>`
- Optional: `--dry-run`

The command must manually invoke the Lambda orchestrator for smoke testing.

The invocation payload must include `triggered_by=manual`.

If `--run-id` is omitted, run ID generation must be left to the orchestrator. If `--run-id` is supplied, it must be validated using the existing shared run ID policy before invocation.

### FR-008: `rcp audit cancel`

Command arguments:

- Required: `--client-id <client_id>`
- Required: `--audit-id <audit_id>`
- Required: `--stage <dev|staging|prod>`
- Optional: `--reason <text>`
- Optional: `--dry-run`

The command must load audit metadata, delete or disable associated EventBridge schedules, retain schedule metadata in DynamoDB, and transition the audit lifecycle state to `CANCELLED`.

If one or more cleanup operations fail after operator cancellation intent is successfully recorded, the command must still transition the audit to `CANCELLED`, persist sanitized `cleanup_errors` in DynamoDB, print an operator-visible warning summary, and exit with status code `3` to indicate operator follow-up is required.

Exit code `3` is reserved for partial cleanup failure during cancellation.

### FR-009: Production Safety Rules

Production restrictions must enforce:

- Maximum audit duration is 48 hours.
- Production execution is blocked unless `allow_production_execution=true` in approved config.
- Destructive operations are blocked unless `allow_destructive_operation=true` in approved config.
- Endpoint method must be allowed by client safety config.
- Payload safety must be valid.
- Concurrency and request caps must respect production-safe limits.
- Production scheduling requires CLI flag `--allow-production`.

### FR-010: Dry-Run Behavior

For commands that support `--dry-run`, the CLI must perform validation and display the intended actions without mutating S3, DynamoDB, EventBridge Scheduler, or Lambda.

Dry-run output must clearly identify that no mutation was performed.

### FR-011: Output and Error Handling

The CLI must fail fast with clear, sanitized error messages.

The CLI must not print secrets, raw tokens, credentials, authorization headers, cookies, raw payloads, or unsanitized AWS provider exceptions.

Human-readable output is required. `--output json` may be supported if it can be implemented simply and consistently.

### Behavior Matrix

| Command | Mutates S3 | Mutates DynamoDB | Mutates EventBridge | Invokes Lambda | Lifecycle Effect |
| --- | --- | --- | --- | --- | --- |
| `audit validate` | No | No | No | No | None |
| `audit create` | Yes, unless dry-run | Yes, unless dry-run | No | No | Creates audit metadata as `DRAFT`; with eligible `--force`, updates existing `DRAFT` or `FAILED` metadata and appends `force_recreate` history |
| `audit schedule` | No | Yes, unless dry-run | Yes, unless dry-run | No | `DRAFT -> SCHEDULED` on success; `FAILED` on partial creation failure |
| `audit run` | No | No direct metadata mutation by CLI | No | Yes, unless dry-run | No direct lifecycle transition by CLI |
| `audit cancel` | No | Yes, unless dry-run | Yes, unless dry-run | No | Eligible state -> `CANCELLED` |

## 8. Acceptance Criteria

### AC-001: Validate Command Success

Given valid client, audit, and endpoints config files and a valid stage config
When an operator runs `rcp audit validate --client-config <path> --audit-config <path> --endpoints-config <path> --stage dev`
Then the CLI exits with status `0`, reports validation success, and performs no S3, DynamoDB, EventBridge, or Lambda calls.

### AC-002: Validate Command Failure

Given an audit config with an audit window longer than 48 hours
When an operator runs `rcp audit validate` with the required config paths and stage
Then the CLI exits non-zero, reports the audit window validation failure, and performs no mutation or invocation.

### AC-003: Create Dry-Run

Given valid config files and no existing S3 config object or audit metadata conflict
When an operator runs `rcp audit create ... --dry-run`
Then the CLI reports the S3 uploads and DynamoDB write that would occur and performs no S3, DynamoDB, EventBridge, or Lambda mutation.

### AC-004: Create Success

Given valid config files, no existing target S3 config objects, and an available audit ID
When an operator runs `rcp audit create` without `--dry-run`
Then the CLI uploads the three config files to the required S3 paths, writes DynamoDB metadata with `PK=CLIENT#{client_id}`, `SK=AUDIT#{audit_id}`, and `lifecycle_state=DRAFT`, and creates no schedules.

### AC-005: Create Existing Resources Without Force

Given at least one target S3 config object or audit metadata already exists for `client_id` and `audit_id`
When an operator runs `rcp audit create` without `--force`
Then the CLI exits non-zero and does not overwrite existing S3 config objects or DynamoDB metadata.

### AC-005A: Create Force Recreate Eligible Audit

Given target S3 config objects and audit metadata already exist for `client_id` and `audit_id`, and the existing audit lifecycle state is `DRAFT` or `FAILED`
When an operator runs `rcp audit create` with `--force` and valid configs
Then the CLI validates the configs and safety checks, overwrites only the target S3 config objects, updates DynamoDB audit metadata, appends a `lifecycle_history` entry with `reason=force_recreate`, preserves existing run evidence, preserves existing `raw-results/*` artifacts, and exits with status `0`.

### AC-005B: Create Force Recreate Ineligible Audit

Given target S3 config objects and audit metadata already exist for `client_id` and `audit_id`, and the existing audit lifecycle state is one of `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, or `CANCELLED`
When an operator runs `rcp audit create` with `--force`
Then the CLI exits non-zero and does not overwrite S3 config objects, does not update DynamoDB audit metadata, does not delete run evidence, and does not modify `raw-results/*` artifacts.

### AC-005C: Create Force Does Not Bypass Validation

Given target S3 config objects and audit metadata already exist for an eligible `DRAFT` or `FAILED` audit, and the supplied config files fail validation or safety checks
When an operator runs `rcp audit create` with `--force`
Then the CLI exits non-zero before persistence and does not overwrite S3 config objects or update DynamoDB audit metadata.

### AC-006: Schedule Dry-Run

Given persisted audit config and audit metadata in an eligible lifecycle state
When an operator runs `rcp audit schedule --client-id <client_id> --audit-id <audit_id> --stage staging --dry-run`
Then the CLI reports the schedules and metadata updates that would occur and performs no EventBridge or DynamoDB mutation.

### AC-007: Schedule Success

Given persisted audit config with enabled schedule blocks and audit metadata in `DRAFT`
When an operator runs `rcp audit schedule --client-id <client_id> --audit-id <audit_id> --stage staging`
Then the CLI creates only the schedules defined and enabled in `audit_config.json`, stores schedule metadata in DynamoDB, and transitions the audit to `SCHEDULED`.

### AC-008: Missing or Disabled Schedule Block

Given persisted audit config where `burst_schedule` is missing or disabled
When an operator runs `rcp audit schedule`
Then the CLI does not create a burst schedule and does not infer a replacement burst schedule.

### AC-009: Production Scheduling Guard

Given a production audit with valid production-safe config
When an operator runs `rcp audit schedule --stage prod` without `--allow-production`
Then the CLI exits non-zero and creates no EventBridge schedules or DynamoDB schedule metadata.

### AC-010: Partial Schedule Failure

Given the first EventBridge schedule creation succeeds and a later required schedule creation fails
When an operator runs `rcp audit schedule`
Then the CLI attempts rollback for created schedules, records sanitized failure metadata, transitions the audit to `FAILED`, exits non-zero, and never persists `SCHEDULED_WITH_ERRORS`.

### AC-011: Manual Run Without Supplied Run ID

Given valid audit metadata and a valid scenario type
When an operator runs `rcp audit run --client-id <client_id> --audit-id <audit_id> --scenario-type baseline_health --stage dev`
Then the CLI invokes the orchestrator with `triggered_by=manual` and omits `run_id` so the orchestrator generates it.

### AC-012: Manual Run With Invalid Run ID

Given an operator supplies a run ID that violates the shared run ID policy
When the operator runs `rcp audit run --run-id <unsafe_run_id>`
Then the CLI exits non-zero before Lambda invocation and reports a sanitized run ID validation error.

### AC-013: Cancel Success

Given audit metadata contains existing schedule metadata for an eligible audit
When an operator runs `rcp audit cancel --client-id <client_id> --audit-id <audit_id> --stage staging --reason "operator requested"`
Then the CLI deletes or disables associated schedules, retains schedule metadata, records the cancellation reason, and transitions the audit to `CANCELLED`.

### AC-014: Cancel Cleanup Failure

Given operator cancellation intent is successfully recorded and one schedule cleanup call fails during cancellation
When an operator runs `rcp audit cancel`
Then the CLI records sanitized `cleanup_errors` in DynamoDB, retains schedule metadata, transitions the audit to `CANCELLED`, prints a warning summary, and exits with status `3`.

### AC-015: Missing Stage Config

Given `config/stages/dev.json` is missing a required field such as `config_bucket`
When an operator runs any `rcp audit` command with `--stage dev`
Then the CLI exits non-zero before AWS client construction and reports the missing stage config field.

### AC-015A: Environment Overrides Stage Config

Given `config/stages/dev.json` contains values for all required stage config fields and `RCP_CONFIG_BUCKET` is set to a different non-empty value
When an operator runs any `rcp audit` command with `--stage dev`
Then the CLI uses the `RCP_CONFIG_BUCKET` value for `config_bucket` and uses stage config file values for required fields without corresponding environment overrides.

### AC-016: No Secrets in Output

Given validation, AWS, or invocation errors include sensitive provider details
When the CLI reports the error
Then the CLI output excludes secrets, tokens, authorization headers, cookies, raw payloads, and unsanitized provider exception text.

## 9. Edge Cases

- Invalid JSON syntax in any provided config file.
- Config files contain mismatched `client_id` or `audit_id` values.
- Required config file path does not exist or is not readable.
- Stage config file is missing, malformed, or lacks required resource fields.
- Environment variable override is set to an empty or invalid value.
- Audit window start is after end.
- Audit window duration is exactly 48 hours.
- Audit window duration exceeds 48 hours by a small amount.
- Schedule block exists but is explicitly disabled.
- Schedule block exists but is malformed.
- Audit metadata is missing when scheduling, running, or cancelling.
- Audit lifecycle state is terminal when scheduling or running is requested.
- Existing audit metadata conflicts during create without `--force`.
- Existing S3 config object conflicts during create without `--force`.
- `--force` is supplied for an existing audit in `DRAFT` state.
- `--force` is supplied for an existing audit in `FAILED` state.
- `--force` is supplied for an existing audit in `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, or `CANCELLED` state.
- `--force` is supplied but validation fails.
- EventBridge schedule name requires deterministic truncation according to existing naming convention.
- AWS provider returns an error containing sensitive text.
- Cancellation cleanup partially fails.
- Manual run supplies unsupported `scenario-type`.
- Manual run supplies unsafe `run-id`.
- Dry-run command encounters invalid config or invalid lifecycle state.

## 10. Constraints

- The CLI is internal and operator-only.
- The CLI must be thin; shared modules and schemas are the source of truth.
- Commands must consistently require `--stage`.
- Production scheduling must require explicit `--allow-production`.
- No secrets may be stored or printed.
- Dependencies must remain minimal.
- Unit tests must mock AWS and must not make real AWS calls.
- Scheduling definitions must come from `audit_config.json`; the CLI must not infer hidden complex schedules.
- Lifecycle states, transition rules, run ID policy, config schemas, and naming conventions must reuse existing definitions when present.
- If an existing shared definition is missing or incomplete, implementation must introduce it in the correct shared location and make the CLI consume it there.

## 11. Dependencies

- Existing Phase 1 orchestrator and run ID behavior.
- Existing Phase 2 payload strategy, endpoint safety, and payload safety behavior.
- Phase 3 lifecycle state machine and schedule metadata contracts.
- Shared config schemas and validators.
- AWS S3 config bucket per stage.
- AWS DynamoDB audit metadata table per stage.
- AWS EventBridge Scheduler group per stage.
- AWS Lambda orchestrator function per stage.
- Local stage config files under `config/stages/`.

## 12. Assumptions

- Requiring `--allow-production` for `rcp audit schedule --stage prod` is mandatory even when the persisted config already contains `allow_production_execution=true`.
- `--output json` is optional and should only be implemented if it does not add significant complexity.
- Dry-run validates inputs and lifecycle eligibility before reporting intended mutations.

## 13. Open Questions

- Should `rcp audit run` require production-specific explicit approval beyond config-level `allow_production_execution=true` when `--stage prod` is used?
