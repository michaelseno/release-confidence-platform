# Implementation Plan

## 1. Feature Overview
Improve `rcp audit schedule` diagnostics when persisted audit metadata is not in the lifecycle state required for scheduling.

## 2. Technical Scope
- Preserve existing lifecycle enforcement that permits scheduling only from `DRAFT`.
- Include sanitized lifecycle context in the `INVALID_LIFECYCLE_STATE` error message raised by scheduling.
- Add CLI next-step guidance specific to lifecycle scheduling failures.
- Add targeted unit/integration coverage for non-`DRAFT` diagnostics, `DRAFT` behavior, and CLI guidance.

## 3. Source Inputs
- `docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md`
- `docs/product/phase_3_audit_scheduling_lifecycle_product_spec.md`
- `docs/qa/audit_schedule_scheduler_error_handling_test_plan.md`
- `docs/bugs/audit_schedule_invalid_lifecycle_state_guidance_bug_report.md`
- Existing scheduling service and CLI rendering patterns.

## 4. API Contracts Affected
No public HTTP API contract changes.

Internal CLI error rendering affected:
- `rcp audit schedule` with `INVALID_LIFECYCLE_STATE` now renders lifecycle-specific recovery guidance instead of the generic retry guidance.

## 5. Data Models / Storage Affected
No data model or storage changes. Existing audit metadata reads are used to obtain `lifecycle_state`.

## 6. Files Expected to Change
- `src/release_confidence_platform/audit_scheduling/service.py`
- `packages/audit_scheduling/service.py`
- `src/release_confidence_platform/operator_cli/result.py`
- `packages/operator_cli/result.py`
- `tests/unit/test_operator_cli_rcp.py`
- `tests/integration/test_phase3_scheduling_lifecycle.py`
- `docs/backend/audit_schedule_invalid_lifecycle_state_guidance_implementation_report.md`

## 7. Security / Authorization Considerations
Error context is limited to safe operator identifiers and lifecycle state: `client_id`, `audit_id`, current state, and required state. No secrets, config payloads, schedule payloads, or AWS provider messages are included.

## 8. Dependencies / Constraints
No new dependencies. Do not deploy, mutate live AWS, create a branch, commit, push, or create a PR.

## 9. Assumptions
- `client_id` and `audit_id` are safe to include because existing CLI rendering already exposes them for operator workflows.
- A missing lifecycle state can be reported as `UNKNOWN` without changing lifecycle behavior.

## 10. Validation Plan
- Run targeted pytest coverage for scheduling lifecycle diagnostics and CLI error guidance.
- Run targeted prior scheduler error-handling coverage already present in the operator CLI test module.
