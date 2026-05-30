# Test Plan

## 1. Feature Overview
Validate the HITL blocker fix for `repeated_stability` iteration execution. The backend must honor persisted `repeated_schedule.iteration_count` for manual runs, preserve scheduled/EventBridge repeated iteration metadata, keep `iteration_count` as the canonical key, and avoid regressions in prior HITL fixes.

## 2. Acceptance Criteria Mapping
- AC1 Canonical key: static key scan verifies no competing persisted `iterations` key was introduced in app/config/test code.
- AC2 Manual repeated config read: `test_repeated_stability_iteration_count_five_runs_each_endpoint_five_times` validates manual `repeated_stability` uses audit config `repeated_schedule.iteration_count`.
- AC3 Five measurements: same test validates `iteration_count=5` creates five raw results for one endpoint.
- AC4 Result metadata: repeated tests validate `iteration_number`, `iteration_count`, `schedule_iteration_number/count`, and `payload_iteration_number/count`.
- AC5 Count of one: `test_repeated_stability_iteration_count_one_records_iteration_metadata` validates backward-compatible single measurement with metadata.
- AC6 Max cap: `test_repeated_stability_accepts_max_iteration_count`, `test_repeated_stability_rejects_max_plus_one_iteration_count`, and schedule validator cap test.
- AC7 Missing/non-integer validation: `test_repeated_stability_rejects_missing_and_non_integer_iteration_count`.
- AC8 Static GET/no-body: `test_repeated_stability_static_get_no_body_includes_iteration_metadata` plus full regression suite for duplicate bypass.
- AC9 Payload iterations multiplication: `test_repeated_stability_multiplies_schedule_and_payload_iterations`.
- AC10 Scheduled/EventBridge repeated metadata: `test_scheduled_repeated_event_preserves_iteration_metadata` and `test_repeated_execution_is_sequential_and_omits_run_id`.
- AC11 Baseline remains single-pass: `test_baseline_health_remains_single_pass_by_default`.
- AC12 Prior HITL regression context: full pytest covers config-init, audit-create, stage-info, Lambda packaging, observability, S3/Dynamo diagnostics, and static GET duplicate bypass suites.
- AC13 Quality gates: Ruff lint, Ruff format check, and full pytest.

## 3. Test Scenarios
- Manual `repeated_stability` with `iteration_count=1`.
- Manual `repeated_stability` with `iteration_count=5`.
- Manual repeated static GET/no-body endpoint.
- Manual repeated schedule iterations combined with endpoint `payload_iterations=3`.
- Scheduled repeated coordinator forwarding `iteration` and `repeated.iteration_count`.
- Missing, string, max, and max+1 `iteration_count` validation.
- Baseline health run with repeated schedule present but scenario type not repeated.
- Repository-wide regression suite and quality gates.

## 4. Edge Cases
- Missing `repeated_schedule.iteration_count`.
- Non-integer `iteration_count`.
- Maximum allowed repeated iteration count.
- Maximum plus one repeated iteration count.
- Static GET endpoint without payload/body.
- Schedule-level iteration combined with payload-level iteration.

## 5. Test Types Covered
- Functional: manual/scheduled repeated execution count and metadata.
- Negative: invalid/missing/over-cap values.
- Edge: count one, max cap, static GET/no-body, multiplicative iterations.
- Integration/regression: scheduled execution, prior HITL suites, full pytest.
- Static contract: canonical key scan.
- Quality gates: Ruff lint and format check.

## 6. Coverage Justification
Coverage directly maps to each requested QA focus item. The selected focused tests prove the repeated-stability fix behavior, while the full suite provides regression protection for prior HITL fixes and unrelated existing behavior. No AWS deployment or live redeploy validation is included by instruction.
