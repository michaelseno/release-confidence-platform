# Pull Request

## 1. Feature Name
scheduled_execution_orchestration_rca

## 2. Summary
Fixes scheduled execution orchestration for recurring audit schedules by replacing static recurring occurrence identity with bounded discrete scheduled occurrences. Also includes HITL blocker fixes for canonical audit list filtering and duplicate finalization idempotency coverage.

Root cause: recurring `rate(...)` schedules reused a static `schedule_occurrence_id`, causing duplicate-prevention to skip later scheduled executions before orchestration.

## 3. Related Documents
- Product Spec: docs/release/phase_3_audit_scheduling_lifecycle_issue.md
- Technical Design: docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md
- Technical Design: docs/architecture/adr_scheduled_execution_occurrence_identity.md
- Technical Design: docs/architecture/hitl_audit_create_blocker_technical_design.md
- Bug Report: docs/bugs/scheduled_execution_orchestration_rca.md
- Bug Report: docs/bugs/hitl_audit_create_lambda_permissions.md
- Bug Report: docs/bugs/hitl_audit_schedule_scheduler_config.md
- Backend Implementation: docs/backend/scheduled_execution_orchestration_rca_implementation_plan.md
- Backend Implementation: docs/backend/scheduled_execution_orchestration_rca_implementation_report.md
- Backend Implementation: docs/backend/hitl_audit_create_blocker_fixes_implementation_plan.md
- Backend Implementation: docs/backend/hitl_audit_create_blocker_fixes_implementation_report.md
- QA Report: docs/qa/scheduled_execution_orchestration_rca_test_plan.md
- QA Report: docs/qa/scheduled_execution_orchestration_rca_test_report.md
- QA Report: docs/qa/hitl_audit_create_blocker_fix_test_plan.md
- QA Report: docs/qa/hitl_audit_create_blocker_fix_test_report.md

## 4. Changes Included
- Replaced baseline recurring `rate(...)` schedules with bounded discrete `at(...)` schedules.
- Added deterministic per-occurrence `schedule_occurrence_id` generation.
- Preserved duplicate-prevention behavior while avoiding false duplicate skips for later scheduled executions.
- Added scheduled handler observability logs.
- Updated `audit list` to return only canonical audit metadata rows.
- Excluded child `#RUN#`, `#OCCURRENCE#`, and future child rows from audit list output.
- Added pagination-aware audit list filtering.
- Improved `FORCE_RECREATE_BLOCKED` guidance.
- Added duplicate finalization idempotency test coverage.

## 5. QA Status
- Approved: YES
- QA approved after scheduling fix: `[QA SIGN-OFF APPROVED]`
- QA approved after HITL blocker fix: `[QA SIGN-OFF APPROVED]`
- Final quality review after duplicate finalization test: Approved, Release Readiness: Yes
- HITL validation: `HITL validation successful`

## 6. Test Coverage
- Focused scheduling suite: passed.
- HITL blocker focused tests: passed.
- Final focused finalization/duplicate/scheduled execution: `16 passed in 0.22s`.
- Final full suite: `354 passed, 1 skipped in 0.86s`.
- Live HITL validation confirmed:
  - schedule creation succeeded
  - scheduledExecution Lambda invoked
  - orchestrator produced raw results in S3
  - audit list now returns only canonical audit metadata
  - lifecycle currently `RUNNING` as expected
  - client_id: `client_layer_1_schedule_validation_client_7331df81`
  - audit_id: `audit_20260531_5f6409d1`

## 7. Risks / Notes
- `SCHEDULER_CONFIG_ERROR` was identified as operator environment configuration and resolved by exporting deployed scheduler outputs; no app code change was required for that issue.
- This PR does not deploy or mutate AWS resources.
- The approved current Phase 3 architecture/design preserves successful nonzero finalization at `FINALIZING`.
- This PR does not implement `FINALIZING -> COMPLETED` and does not implement `FINALIZING -> ANALYZING -> REPORTING -> COMPLETED`.
- Follow-ups:
  - confirm finalization Lambda fires after the audit window;
  - confirm schedule cleanup behavior;
  - if `COMPLETED` transition is required, open/track a separate product/architecture decision for the next lifecycle phase.

## 8. Linked Issue
- Closes #21
