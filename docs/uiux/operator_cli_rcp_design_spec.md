# Design Specification

## 1. Feature Overview

The Operator CLI `rcp` is an internal terminal interface for trusted operators to validate, create, schedule, manually run, and cancel Phase 3 audits. This specification defines CLI interaction behavior only; no web UI, visual dashboard, or customer-facing experience is in scope.

Primary invocation:

```bash
python scripts/rcp.py audit <command> [options]
```

Preferred optional invocation if packaged:

```bash
rcp audit <command> [options]
```

## 2. User Goal

Operators need a safe, repeatable way to perform audit operations without directly manipulating S3, DynamoDB, EventBridge Scheduler, or Lambda resources.

## 3. UX Rationale

- Use explicit subcommands to make operational intent clear.
- Require `--stage` on every command to prevent ambiguous environment targeting.
- Use dry-run summaries for mutating commands so operators can verify effects before execution.
- Use deterministic text output for copy/paste, logs, screen readers, and automated assertions.
- Provide optional `--output json` for machine-readable automation if implemented.
- Fail fast before AWS client construction when arguments, stage config, or local files are invalid.

## 4. User Flow

### Validate

1. Operator runs `rcp audit validate` with three config file paths and `--stage`.
2. CLI validates arguments and stage config.
3. CLI delegates config validation to shared services.
4. CLI prints success summary or sanitized validation errors.
5. CLI exits `0` on success or non-zero on failure.

### Create

1. Operator runs `rcp audit create` with config file paths, `--stage`, and optional `--dry-run` / `--force`.
2. CLI validates configs using the same validation path as `validate`.
3. Dry-run prints intended S3 uploads and DynamoDB metadata write with no mutation.
4. If an existing audit is found and `--force` is supplied, CLI must visibly communicate overwrite scope and guardrails before applying mutations: overwrite is allowed only for existing audits in `DRAFT` or `FAILED`, never bypasses validation/safety checks, and never overwrites run evidence or raw-results artifacts.
5. Non-dry-run persists configs and draft metadata, then prints created summary.

### Schedule

1. Operator runs `rcp audit schedule --client-id ... --audit-id ... --stage ...`.
2. If stage or target is production, operator must also pass `--allow-production`.
3. CLI loads persisted source-of-truth config through shared services.
4. Dry-run prints planned schedules and metadata transition.
5. Non-dry-run creates only enabled schedules from `audit_config.json` and transitions to `SCHEDULED`.

### Run

1. Operator runs `rcp audit run` with IDs, `--scenario-type`, `--stage`, and optional `--run-id`, `--schedule-type`, `--dry-run`.
2. CLI validates scenario type and optional run ID.
3. Dry-run prints intended Lambda invocation payload summary.
4. Non-dry-run invokes orchestrator with `triggered_by=manual`.

### Cancel

1. Operator runs `rcp audit cancel` with IDs, `--stage`, and optional `--reason`, `--dry-run`.
2. CLI validates lifecycle eligibility.
3. Dry-run prints schedules that would be cleaned up and lifecycle transition.
4. Non-dry-run cleans up schedules, retains schedule metadata, and transitions to `CANCELLED`.
5. If cancellation partially succeeds but cleanup fails, CLI exits `3`, prints a warning summary, and clearly states that audit state may be `CANCELLED` while operator follow-up is required.

## 5. Information Hierarchy

Terminal output must prioritize:

1. Result status: `SUCCESS`, `DRY-RUN`, `ERROR`, or `WARNING`.
2. Command and stage.
3. Audit identity: `client_id`, `audit_id` when known.
4. Lifecycle outcome, when applicable.
5. Action summary: created/planned/cleaned-up resources.
6. Guardrail summary for potentially destructive operations such as `audit create --force`.
7. Operator next step for failures, production guard blocks, or partial cleanup warnings.
8. Sanitized diagnostic code/details.

## 6. Layout Structure

### Command Structure

```text
rcp
  audit
    validate  --client-config PATH --audit-config PATH --endpoints-config PATH --stage dev|staging|prod [--output text|json]
    create    --client-config PATH --audit-config PATH --endpoints-config PATH --stage dev|staging|prod [--dry-run] [--force] [--output text|json]
    schedule  --client-id ID --audit-id ID --stage dev|staging|prod [--dry-run] [--allow-production] [--output text|json]
    run       --client-id ID --audit-id ID --scenario-type TYPE --stage dev|staging|prod [--run-id ID] [--schedule-type TYPE] [--dry-run] [--output text|json]
    cancel    --client-id ID --audit-id ID --stage dev|staging|prod [--reason TEXT] [--dry-run] [--output text|json]
```

### Help Structure

Top-level help must list command groups only:

```text
usage: rcp [-h] {audit} ...

Internal Release Confidence Platform operator CLI.

commands:
  audit    Audit validation, creation, scheduling, manual run, and cancellation commands
```

`rcp audit --help` must list subcommands with one-line descriptions. Each subcommand help must include required arguments first, optional safety/output flags second, and examples last.

## 7. Components

CLI components:

- Command parser and help text.
- Text output renderer.
- Optional JSON output renderer.
- Error renderer.
- Dry-run action summary.
- Production safety guard messaging.
- Force overwrite guard messaging.
- Cancel partial cleanup warning renderer.
- Stage configuration environment override diagnostics.

No web components are defined.

## 8. Interaction Behavior

### Human-Readable Success Pattern

```text
SUCCESS: audit <command>
stage: <stage>
client_id: <client_id>
audit_id: <audit_id>
summary: <one concise sentence>
actions:
  - <verb>: <resource or operation>
next_step: <operator follow-up or "none">
```

### Dry-Run Pattern

```text
DRY-RUN: audit <command>
stage: <stage>
client_id: <client_id>
audit_id: <audit_id>
summary: validation passed; no mutations performed
planned_actions:
  - <would create/upload/update/invoke/delete>: <resource summary>
next_step: rerun without --dry-run to apply these actions
```

Dry-runs must never imply resources were changed.

### Failure Pattern

```text
ERROR: audit <command> failed
stage: <stage if parsed>
code: <CONTROLLED_ERROR_CODE>
message: <sanitized actionable message>
next_step: <specific corrective action>
```

Multiple validation failures may be shown as a deterministic list:

```text
errors:
  - path: audit_window.end_at
    message: audit window must be <= 48 hours
```

### Production Scheduling Guard

If scheduling production without `--allow-production`, CLI must fail before schedule creation or metadata mutation:

```text
ERROR: audit schedule failed
stage: prod
code: PRODUCTION_APPROVAL_REQUIRED
message: production scheduling requires explicit --allow-production
next_step: verify the persisted config is production-approved, then rerun with --allow-production
```

### Force Create Overwrite Guard

When `audit create --force` is used, output must make overwrite scope and guardrails explicit. The command must not continue for existing audits in `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, or `CANCELLED`.

Allowed force overwrite states:

- `DRAFT`
- `FAILED`

Forbidden force overwrite states:

- `SCHEDULED`
- `RUNNING`
- `FINALIZING`
- `ANALYZING`
- `REPORTING`
- `COMPLETED`
- `CANCELLED`

Force output must include these guardrails in text mode:

```text
WARNING: audit create --force
stage: <stage>
client_id: <client_id>
audit_id: <audit_id>
existing_lifecycle_state: DRAFT|FAILED
overwrite_scope:
  - replace persisted client/audit/endpoints configuration artifacts
  - update draft audit metadata
guardrails:
  - validation and safety checks are still enforced
  - run evidence artifacts are never overwritten
  - raw-results artifacts are never overwritten
next_step: review overwrite scope before rerunning without --dry-run, or continue if already executing
```

If `--force` is supplied for a forbidden lifecycle state, CLI must fail before mutation:

```text
ERROR: audit create failed
stage: <stage>
code: FORCE_OVERWRITE_NOT_ALLOWED
message: --force can overwrite only DRAFT or FAILED audits; current state is <state>
next_step: choose a different audit_id or use the appropriate lifecycle operation for this audit
```

`--force` must never be described as bypassing validation, production safety rules, lifecycle rules, run evidence protection, or raw-results artifact protection.

### Cancel Partial Cleanup Warning

If audit cancellation transitions or may have transitioned the audit to `CANCELLED` but one or more cleanup actions fail, CLI must return exit code `3` and print a warning status rather than a full success status:

```text
WARNING: audit cancel partial cleanup failure
stage: <stage>
client_id: <client_id>
audit_id: <audit_id>
lifecycle_state: CANCELLED
summary: audit cancellation completed, but schedule cleanup requires operator follow-up
cleanup_warnings:
  - <sanitized cleanup failure summary>
next_step: inspect remaining schedules and complete cleanup before treating cancellation as operationally closed
```

The warning must not expose raw provider errors, credentials, request IDs containing sensitive data, or unsanitized schedule payloads.

### Optional JSON Output Expectations

If `--output json` is implemented:

- Output must be a single JSON object to stdout.
- Errors must also use JSON when argument parsing succeeds and `--output json` is known.
- No ANSI color codes or human prose outside the JSON object.
- Field names must be stable and snake_case.
- Secret-bearing fields, raw provider errors, headers, cookies, tokens, credentials, and raw payloads must be omitted or sanitized.

Minimum shape:

```json
{
  "status": "success|dry_run|error|warning",
  "command": "audit.schedule",
  "stage": "staging",
  "client_id": "client-a",
  "audit_id": "audit-2026-01",
  "lifecycle_state": "SCHEDULED",
  "actions": [],
  "warnings": [],
  "errors": [],
  "next_step": "none"
}
```

For `audit create --force`, JSON output must include stable fields for `existing_lifecycle_state`, `overwrite_scope`, and `guardrails`. For cancel partial cleanup failures, JSON output must use `status="warning"`, include `lifecycle_state` when known, include non-empty `warnings`, and preserve exit code `3`.

## 9. Component States

### Command Parser

- Default: parses valid command and dispatches.
- Focus/hover/active: not applicable in terminal.
- Disabled: command unavailable only if not implemented; help must not advertise unavailable commands.
- Loading: no spinner required; commands may be silent while running unless a safe progress line is necessary.
- Success: renderer receives sanitized result and exits `0`.
- Error: parser errors exit `2` with usage; controlled command failures exit non-zero.
- Empty: missing command shows help and exits non-zero.

### Text Renderer

- Default: deterministic key/value blocks.
- Focus/hover/active/disabled: not applicable.
- Loading: no color or animation dependency.
- Success: prints `SUCCESS` or `DRY-RUN` header.
- Warning: prints `WARNING` header, warning summary, lifecycle state when known, and required operator follow-up; cancel partial cleanup failure exits `3`.
- Error: prints `ERROR` header, code, message, next step.
- Empty: omit empty optional sections rather than printing placeholders.

### JSON Renderer

- Default: emits one JSON object.
- Focus/hover/active/disabled/loading: not applicable.
- Success: `status="success"` or `status="dry_run"`.
- Warning: `status="warning"` with non-empty `warnings` array; cancel partial cleanup failure exits `3`.
- Error: `status="error"` with non-empty `errors` array.
- Empty: use empty arrays for `actions`, `warnings`, `errors`.

### Production Guard

- Default: inactive for non-production scheduling.
- Active: blocks production scheduling without `--allow-production`.
- Success: permits command to proceed only after all shared production rules pass.
- Error: returns actionable `PRODUCTION_APPROVAL_REQUIRED` or shared safety error.

### Force Overwrite Guard

- Default: inactive unless `audit create --force` is supplied.
- Active: evaluates existing audit lifecycle state before mutation and renders overwrite scope/guardrails.
- Disabled: not available for lifecycle states other than `DRAFT` or `FAILED`.
- Loading: no spinner required; do not print irreversible language until validation and lifecycle checks complete.
- Success: permits overwrite only after validation/safety checks pass and only for config artifacts and draft metadata.
- Error: returns `FORCE_OVERWRITE_NOT_ALLOWED` for `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, or `CANCELLED`; no mutation occurs.
- Empty: if no existing audit exists, `--force` has no overwrite scope to show; create proceeds as normal after validation.

### Cancel Cleanup Warning State

- Default: cancellation reports cleaned-up schedules and `CANCELLED` lifecycle transition on full success.
- Active: if cleanup partially fails after cancellation transition or possible transition, render `WARNING` with follow-up.
- Disabled: not applicable to dry-run because no cleanup is attempted.
- Loading: no spinner required; avoid intermediate success messaging before cleanup result is known.
- Success: all cleanup actions complete and lifecycle transition is confirmed; exit `0`.
- Warning: partial cleanup failure; audit state may be `CANCELLED`; exit `3`.
- Error: cancellation eligibility or transition fails before partial success; use controlled non-zero error and do not imply cancellation completed.

## 10. Responsive Design Rules

Not applicable to a web viewport. Terminal usability rules:

- Lines should target <= 100 characters where practical.
- Avoid tables that require wide terminals for critical data.
- Use deterministic indentation and bullet lists.
- Output must remain understandable in plain text logs.

## 11. Visual Design Tokens

No visual tokens are required. ANSI color may be added only as progressive enhancement and must never be the sole indicator of status. Status words (`SUCCESS`, `DRY-RUN`, `ERROR`, `WARNING`) are required even when color is enabled.

### Environment Override Names

Help text and diagnostics must refer to environment overrides by their exact names:

- `RCP_AWS_REGION`
- `RCP_AWS_PROFILE`
- `RCP_CONFIG_BUCKET`
- `RCP_AUDIT_METADATA_TABLE`
- `RCP_ORCHESTRATOR_FUNCTION_NAME`
- `RCP_SCHEDULER_GROUP_NAME`
- `RCP_SCHEDULE_NAME_PREFIX`

Do not introduce alternate aliases or abbreviated names in operator-facing output.

## 12. Accessibility Requirements

- Do not rely on color, emoji, cursor movement, or spinners to communicate state.
- Use plain text labels before values for screen readers and copied logs.
- Keep output deterministic for assistive tooling and automated parsing.
- Place the most important status on the first line.
- Include actionable `next_step` for errors.
- Avoid printing raw stack traces by default.
- Provide `--output json` as the machine-readable option if implemented.

## 13. Edge Cases

- Missing required arguments: show usage and exit `2`.
- Invalid stage: fail before AWS client construction.
- Missing/malformed stage config: identify missing field and next step.
- Invalid JSON or unreadable config file: identify file path and parser/permission category without dumping file contents.
- Mismatched `client_id` / `audit_id`: identify expected vs found IDs when safe.
- Existing audit without `--force`: fail before overwrite.
- `--force` supplied but validation fails: fail validation; do not mutate; message must state that `--force` does not bypass validation or safety checks.
- `--force` supplied for `DRAFT` or `FAILED`: allowed only for persisted config artifacts and draft metadata; never overwrite run evidence or raw-results artifacts.
- `--force` supplied for `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, or `CANCELLED`: fail before mutation with `FORCE_OVERWRITE_NOT_ALLOWED`.
- Missing/disabled schedule block: report skipped schedule type only in summary; do not infer replacements.
- Partial schedule creation failure: print rollback outcome, transition result, and sanitized warning/error.
- Cancel partial cleanup failure: exit `3`, print `WARNING`, state that audit state may be `CANCELLED`, and provide explicit operator follow-up; do not expose provider raw errors.
- Invalid run ID: fail before Lambda invocation.
- Provider errors containing secrets: sanitize before output and persistence.

## 14. Developer Handoff Notes

- Keep CLI output rendering separate from service/business logic.
- Use stable controlled error codes for test assertions.
- Human-readable output should be concise and deterministic; no interactive prompts are required in current scope.
- `--allow-production` is an explicit flag, not a prompt substitute.
- `--force` is an explicit overwrite guard for only `DRAFT` and `FAILED`; it must not be implemented or documented as a validation/safety bypass.
- Preserve exit code `3` for cancel partial cleanup failure in both text and JSON output modes.
- Use only the confirmed `RCP_*` environment override names in help, errors, and documentation.
- `--output json` should preserve exit codes and sanitization behavior.
- No customer-facing or web UI work should be created for this feature.
