# Bug Report

## 1. Summary

During HITL validation, `rcp audit schedule` now reaches DynamoDB but fails with `INVALID_LIFECYCLE_STATE` because the target audit is no longer in `DRAFT`. Scheduling from persisted audit metadata currently allows only `DRAFT`, while the CLI error guidance is generic and does not tell the operator how to inspect the current lifecycle state or safely recover.

## 2. Investigation Context

- Source of report: HITL validation.
- Active branch: `feature/profile_driven_config_init`.
- Workflow: operator CLI audit scheduling after prior `audit create`, manual `audit run`, and failed `audit schedule` attempts.
- Command reported by user:

```bash
rcp audit schedule \
  --client-id client_layer_1_validation_client_b5817642 \
  --audit-id audit_20260524_ec3f2d9b \
  --stage dev
```

## 3. Observed Symptoms

Observed output:

```text
ERROR: audit schedule failed
stage: dev
code: INVALID_LIFECYCLE_STATE
message: Audit lifecycle does not allow scheduling
next_step: correct the error and retry
```

Expected behavior depends on current lifecycle state:

- If the audit is `DRAFT`, scheduling should proceed or fail with a scheduler/config/provider error.
- If the audit is not `DRAFT`, scheduling should be blocked, but the CLI should explain the current state, allowed scheduling state, and safe recovery options.

## 4. Evidence Collected

- `src/release_confidence_platform/audit_scheduling/service.py:51-55`: `schedule_from_persisted_audit()` loads audit metadata and raises `ValidationError("Audit lifecycle does not allow scheduling", "INVALID_LIFECYCLE_STATE")` whenever `audit.get("lifecycle_state") != "DRAFT"`.
- `src/release_confidence_platform/audit_scheduling/service.py:88-119`: when schedule creation raises after the service starts mutating schedules, it rolls back created schedules where possible, persists schedule/cleanup metadata, transitions the audit to `FAILED`, and re-raises the original exception.
- `src/release_confidence_platform/audit_lifecycle/constants.py:33-56`: lifecycle transition map allows `DRAFT -> SCHEDULED`, `CANCELLED`, or `FAILED`; terminal `FAILED`/`CANCELLED`/`COMPLETED` have no outgoing transitions.
- `src/release_confidence_platform/core/audit_creation_service.py:80-89`: `audit create --force` is guarded and allowed only when existing metadata is `DRAFT` or `FAILED`; it rejects `SCHEDULED` and other states before mutation.
- `src/release_confidence_platform/core/manual_run_service.py:29-65`: manual `audit run` builds and invokes an orchestrator payload; it does not transition audit-level lifecycle state itself.
- `src/release_confidence_platform/operator_cli/result.py:351-446`: `INVALID_LIFECYCLE_STATE` has no specialized next-step mapping, so it falls through to `correct the error and retry`.
- `src/release_confidence_platform/operator_cli/discovery_service.py:46-64` and `:184-207`: `rcp audit list --client-id ... --stage ...` is a read-only CLI path that returns safe audit metadata including `lifecycle_state`, `created_at`, `updated_at`, `audit_window`, and target environment.
- `docs/product/phase_3_audit_scheduling_lifecycle_product_spec.md:181-199` and `docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md:143-157`: approved lifecycle transition table confirms strict lifecycle behavior and terminal states.
- `docs/backend/audit_schedule_scheduler_error_handling_implementation_report.md:47`: prior implementation notes already warn live dev HITL may require a fresh `DRAFT` audit if a previous attempt transitioned the audit to `FAILED`.

## 5. Execution Path / Failure Trace

1. `rcp audit schedule` dispatches to `services.schedule_command()`.
2. The CLI loads stage config and validates scheduler config.
3. `AuditSchedulingService.schedule_from_persisted_audit()` calls `repository.get_audit_metadata(client_id, audit_id)`.
4. Before S3 config read or EventBridge Scheduler mutation, the service checks `audit.get("lifecycle_state") != "DRAFT"`.
5. Any non-`DRAFT` state raises `INVALID_LIFECYCLE_STATE`.
6. `operator_cli.main` renders the structured error, but `result._error_next_step()` has no lifecycle-specific guidance and emits the generic fallback.

Likely state history for this HITL audit:

- `audit create` created audit-level metadata in `DRAFT`.
- Manual `audit run` did not directly change audit-level lifecycle state.
- A previous `audit schedule` attempt that reached schedule creation and then failed would have transitioned the audit to `FAILED` by design.
- If a previous schedule attempt fully succeeded, the audit would be `SCHEDULED`; if a scheduled occurrence later fired, it may be `RUNNING`; if finalization fired, it may be `FINALIZING` or `FAILED` for zero executions.

The current error proves only that the audit is not `DRAFT`; DynamoDB/CLI inspection is required to identify the exact current state.

## 6. Failure Classification

- Primary classification: Application Bug.
- Severity: Medium.

Justification: the lifecycle block itself is expected and protects the state machine, but the operator-facing diagnostic is insufficient during HITL and can block validation without actionable guidance. It does not appear to corrupt data or break core scheduling semantics.

## 7. Root Cause Analysis

Most Likely Root Cause: the audit metadata lifecycle state is no longer `DRAFT`, most likely `FAILED` from a previous schedule attempt that entered `AuditSchedulingService.schedule_from_persisted_audit()` and hit a scheduler/provider failure. The current implementation intentionally allows scheduling only from `DRAFT`, then returns a generic error when this precondition fails.

Immediate failure point:

- `src/release_confidence_platform/audit_scheduling/service.py:51-55` rejects non-`DRAFT` audit metadata.

Underlying issue:

- The behavior is expected state-machine enforcement, but the CLI guidance is poor. The error omits current lifecycle state, allowed scheduling state (`DRAFT`), whether `--force` applies, and read-only diagnostics.

Contributing factors:

- `operator_cli.result._error_next_step()` does not handle `INVALID_LIFECYCLE_STATE`.
- No `rcp audit get` command exists; users must use `audit list` or AWS DynamoDB read commands to inspect exact metadata.

## 8. Confidence Level

Medium.

The code path and allowed state are confirmed. The exact current state of `client_layer_1_validation_client_b5817642/audit_20260524_ec3f2d9b` has not been inspected in live DynamoDB, so `FAILED` is the most likely state but not confirmed.

## 9. Recommended Fix

Likely owner: full-stack/backend operator tooling.

Recommended developer changes:

1. In `AuditSchedulingService.schedule_from_persisted_audit()`, include sanitized lifecycle context in the `INVALID_LIFECYCLE_STATE` message or metadata where supported:
   - current `lifecycle_state`
   - allowed scheduling state: `DRAFT`
   - safe recovery summary based on current state
2. In `src/release_confidence_platform/operator_cli/result.py`, add a specific `_error_next_step()` branch for `INVALID_LIFECYCLE_STATE` that tells users to run `rcp audit list --client-id ... --stage ... --output json`, inspect DynamoDB metadata, and use either a fresh audit ID/config bundle or guarded `audit create --force` only when metadata is `DRAFT`/`FAILED` and replacement is safe.
3. Consider adding a read-only `rcp audit get --client-id --audit-id --stage` command that returns safe audit-level metadata (`lifecycle_state`, `lifecycle_history` summary, `schedules`, counters, finalization state) without raw evidence or secrets.
4. Do not add implicit rescheduling from `FAILED`, `SCHEDULED`, `RUNNING`, `FINALIZING`, `CANCELLED`, or `COMPLETED` unless product explicitly approves a repair/reschedule lifecycle contract.

## 10. Suggested Validation Steps

Immediate safe diagnostics for the current HITL audit:

```bash
rcp audit list \
  --client-id client_layer_1_validation_client_b5817642 \
  --stage dev \
  --output json
```

```bash
aws dynamodb get-item \
  --profile "$RCP_AWS_PROFILE" \
  --region "$RCP_AWS_REGION" \
  --table-name "$RCP_AUDIT_METADATA_TABLE" \
  --key '{"PK":{"S":"CLIENT#client_layer_1_validation_client_b5817642"},"SK":{"S":"AUDIT#audit_20260524_ec3f2d9b"}}' \
  --projection-expression 'client_id,audit_id,lifecycle_state,lifecycle_history,schedules,audit_window,execution_counters,finalization,cleanup_errors,updated_at'
```

```bash
aws scheduler list-schedules \
  --profile "$RCP_AWS_PROFILE" \
  --region "$RCP_AWS_REGION" \
  --group-name "$RCP_SCHEDULER_GROUP_NAME" \
  --query 'Schedules[?contains(Name, `audit_20260524_ec3f2d9b`)]'
```

These commands are read-only. Do not update/delete DynamoDB metadata or schedules until current state and existing schedule ownership are confirmed.

1. Unit test `schedule_from_persisted_audit()` with audit states `FAILED`, `SCHEDULED`, `RUNNING`, `FINALIZING`, `CANCELLED`, and `COMPLETED`; verify it blocks before S3/Scheduler calls and surfaces actionable lifecycle context.
2. Unit test CLI rendering for `INVALID_LIFECYCLE_STATE` to verify next-step guidance is not the generic `correct the error and retry`.
3. Manual HITL validation on dev:
   - Inspect current audit state with read-only commands.
   - Create a fresh audit ID/config bundle and verify `audit create` produces `DRAFT`.
   - Run `audit schedule --dry-run` and then `audit schedule` from `DRAFT`.
   - Re-run `audit schedule` against the now-`SCHEDULED` audit and verify the improved lifecycle guidance.

## 11. Open Questions / Missing Evidence

- Exact live DynamoDB `lifecycle_state` for `client_layer_1_validation_client_b5817642/audit_20260524_ec3f2d9b` is not yet confirmed.
- Exact previous failed schedule error that may have transitioned the audit to `FAILED` is not included in the report.
- Whether EventBridge schedules already exist for this audit is unknown and should be checked before any destructive recovery.

## 12. Final Investigator Decision

Ready for developer fix.

The scheduling block is expected when the audit is not `DRAFT`, but operator guidance should be fixed. Immediate user recovery should use read-only diagnostics first, then a fresh audit ID/config bundle or guarded dev/test-only force recreate where appropriate.
