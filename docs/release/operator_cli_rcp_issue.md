# GitHub Issue

GitHub Issue: #11

## 1. Feature Name

Operator CLI `rcp` for internal Release Confidence Platform audit operations.

## 2. Problem Summary

Phase 3 audit operations currently require operators to interact directly with S3, DynamoDB, EventBridge Scheduler, and Lambda resources. This increases the risk of invalid audit metadata, unsafe production execution, inconsistent lifecycle transitions, unsanitized failures, and unreproducible validation. The `rcp` CLI provides a controlled internal operator entry point for validating configs, creating draft audit metadata, scheduling audits, manually invoking smoke runs, and cancelling audits while delegating business rules to shared platform modules.

## 3. Linked Planning Documents

- Product Spec: `docs/product/operator_cli_rcp_spec.md`
- Technical Design: `docs/architecture/operator_cli_rcp_technical_design.md`
- UI/UX Spec: `docs/uiux/operator_cli_rcp_design_spec.md`
- QA Test Plan: `docs/qa/operator_cli_rcp_test_plan.md`

## 4. Scope Summary

### In scope

- Internal CLI command group `rcp audit` with `validate`, `create`, `schedule`, `run`, and `cancel` subcommands.
- Minimum supported invocation through `python scripts/rcp.py audit ...`; optional packaged `rcp` console script if low effort.
- Required `--stage dev|staging|prod` on every command.
- Stage-aware resource resolution from `config/stages/{stage}.json` with documented environment variable overrides.
- Shared validation, lifecycle, run ID, schedule construction, AWS naming, production safety, and sanitization logic.
- S3 config persistence, DynamoDB audit metadata writes/updates, EventBridge schedule creation/cleanup, and Lambda manual invocation through mockable wrappers.
- Dry-run behavior for mutating commands.
- Human-readable CLI output and optional simple JSON output.
- Operator documentation and unit tests with mocked AWS dependencies only.

### Out of scope

- Customer-facing UI, API, dashboard, documentation, or self-service workflow.
- Authentication, RBAC, billing, subscriptions, tenant onboarding, or audit authoring UI.
- Complex schedule inference beyond explicit schedule blocks in persisted `audit_config.json`.
- Direct storage or output of secrets, raw tokens, credentials, authorization headers, cookies, raw payloads, or unsanitized provider exceptions.
- Real AWS calls in unit tests.
- Replacement of existing Phase 1 orchestrator behavior or Phase 2 payload/safety/data generation behavior.
- Analytics, scoring, reporting, automatic completion workflows, or status/repair operator commands.

## 5. Implementation Notes

### Frontend expectations

- No web frontend is required.
- CLI UX must use explicit subcommands, deterministic help text, stable argument names, and sanitized success/dry-run/error output.
- Output must prioritize result status, command, stage, audit identity, lifecycle outcome, action summary, next step, and sanitized diagnostics.
- Dry-run output must clearly state that no mutations were performed.
- If `--output json` is implemented, output must be a single sanitized JSON object with stable snake_case fields and no ANSI/prose wrappers.

### Backend expectations

- CLI command handlers must remain thin: parse args, build request objects, call shared services, render sanitized results, and map controlled errors to exit codes.
- Shared services must own config validation, lifecycle transition validation, run ID validation, schedule generation, production safeguards, storage orchestration, cancellation behavior, and provider-error sanitization.
- Stage config must fail fast before AWS client construction when missing or invalid.
- `validate` must never upload configs, write metadata, create schedules, or invoke Lambda.
- `create` must validate before persistence, upload deterministic S3 config keys, and write `DRAFT` metadata unless blocked by conflict without `--force`.
- `schedule` must load persisted config as source of truth, create only enabled schedules, transition eligible audits to `SCHEDULED`, and rollback/transition to `FAILED` on partial schedule failure.
- `run` must invoke the existing orchestrator with `triggered_by=manual`, omit `run_id` when not supplied, and validate supplied run IDs through shared policy.
- `cancel` must clean up schedules, retain schedule metadata, transition to `CANCELLED`, and record sanitized cleanup errors when cleanup fails.

### Dependencies or blockers

- Confirm exact environment variable override names for stage config fields.
- Confirm final cleanup-failure exit policy if it differs from the QA plan recommendation of warning/non-zero exit code `3`.
- Clarify exact `--force` overwrite behavior beyond non-force conflict blocking.
- Ensure existing shared validators, lifecycle services, scheduler safeguards, storage wrappers, and orchestrator invocation boundaries can be reused or safely extended.

## 6. QA Section

### Planned test coverage

- Parser and command contract tests for `audit` group, subcommands, required arguments, optional flags, valid/invalid stage choices, scenario choices, and help behavior.
- Validation service tests for JSON syntax, schemas/required fields, ID consistency, audit windows, endpoint methods, payload strategy/safety, auth references, and production restrictions.
- Create, schedule, run, and cancel service tests using mocked S3, DynamoDB, EventBridge Scheduler, and Lambda dependencies.
- Dry-run tests verifying validation occurs and no mutation/invocation occurs.
- Sanitization tests verifying secrets and raw provider errors are not printed.
- Stage config loader tests verifying fail-fast behavior before AWS client construction.

### Acceptance criteria mapping

- AC-001 through AC-002: `validate` success/failure behavior and no AWS side effects.
- AC-003 through AC-005: `create` dry-run, successful persistence, and conflict blocking.
- AC-006 through AC-010: `schedule` dry-run, schedule creation/skip rules, production approval guard, partial failure rollback, and `FAILED` transition.
- AC-011 through AC-012: manual run invocation payload and run ID validation.
- AC-013 through AC-014: cancellation cleanup, metadata retention, `CANCELLED` transition, and cleanup-error handling.
- AC-015: stage config validation before client construction.
- AC-016: output and error sanitization.

### Key edge cases

- Audit window exactly 48 hours versus greater than 48 hours.
- Mismatched `client_id` or `audit_id` across config files.
- Missing or disabled schedule blocks must be skipped without inferred replacements.
- Production scheduling without `--allow-production` must fail before mutation.
- Partial EventBridge schedule creation failure must rollback created schedules and never persist `SCHEDULED_WITH_ERRORS`.
- Invalid optional `run_id` must fail before Lambda invocation.
- Cleanup failures must retain schedule metadata and persist sanitized cleanup errors.
- Empty or malformed stage config environment overrides must not mask valid JSON config values.

### Test types expected

- Automated unit tests only for this release scope.
- Parser/CLI dispatch unit tests.
- Shared service unit tests with fakes/mocks.
- Renderer/error-mapping/sanitization unit tests.
- No real AWS calls, credentials, boto3 client construction, or integration tests in unit coverage.

## 7. Risks / Open Questions

- Risk: Business rules could drift into CLI handlers instead of shared modules, reducing reuse for future APIs or dashboards.
- Risk: Incomplete sanitization could expose secrets, raw payloads, or provider exception details in operator output.
- Risk: Partial schedule failures require careful rollback and metadata sequencing to avoid inconsistent lifecycle state.
- Risk: Production safeguards must be enforced consistently across validation and scheduling paths.
- Open question: Final stage environment variable override names require confirmation.
- Open question: Final cancellation cleanup warning/exit-code policy requires confirmation.
- Open question: Exact `--force` overwrite semantics require product clarification before strict QA approval.

## 8. Definition of Done

- `python scripts/rcp.py audit validate|create|schedule|run|cancel` command paths are implemented with required arguments and stage handling.
- CLI handlers delegate domain behavior to shared modules and do not directly implement business rules or call AWS SDK clients.
- Stage config loading validates required fields and fails before AWS client construction.
- Mutating commands support dry-run behavior with no mutations or invocations.
- AWS-facing behavior is routed through mockable wrappers and unit tests use mocked/faked dependencies only.
- Config validation, lifecycle transitions, production safeguards, schedule creation/rollback, manual invocation, cancellation, and sanitization satisfy the linked product and technical design requirements.
- Unit tests cover the QA plan acceptance criteria and key edge cases.
- Operator-facing output is deterministic, actionable, and sanitized.
- Documentation is added or updated for operator usage and package-level implementation notes.
