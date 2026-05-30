# Bug Report

## 1. Summary
During HITL validation for the Enhanced `rcp config init` Default Profile System, `repeated_stability` appears to execute each endpoint once even when the generated audit config contains `repeated_schedule.iteration_count`. Code inspection confirms the manual audit-run path does not read `repeated_schedule.iteration_count`, and raw result records do not include repeated-execution iteration metadata.

## 2. Investigation Context
- Source of report: HITL validation.
- Related feature/workflow: Enhanced `rcp config init` generated default audit profiles and subsequent `rcp audit run --scenario-type repeated_stability` validation.
- Branch context: `feature/profile_driven_config_init` remains the active HITL correction branch.
- Relevant user action: run an audit with `scenario_type=repeated_stability` against generated config where `repeated_schedule.iteration_count > 1` is expected to drive repeated measurements.

## 3. Observed Symptoms
- Concern: `repeated_stability` appears to execute each endpoint once only.
- Expected behavior:
  - `repeated_schedule.iteration_count = 5` should execute each endpoint 5 times, or raw results should clearly expose repeated-iteration metadata.
  - Each endpoint result should include `iteration_index` or `iteration_number`.
  - Raw evidence should distinguish repeated executions for future aggregation.
  - `baseline_health` should remain single-pass unless `requests_per_run > 1`.
- Actual behavior from code path inspection:
  - Manual `audit run` sends only `client_id`, `audit_id`, `scenario_type`, `triggered_by`, `schedule_type`, `stage`, and optional `run_id`; it does not load or include `repeated_schedule.iteration_count`.
  - Core orchestrator loads and validates audit config but discards schedule values; it loops endpoints by `endpoint.get("payload_iterations", 1)`, not by `repeated_schedule.iteration_count`.
  - Raw result records include `scenario_type` and runner outcome fields, but no `iteration_index` / `iteration_number` for repeated schedule execution.

## 4. Evidence Collected
- Generated audit config shape:
  - `src/release_confidence_platform/config/generators/audit_config_generator.py:51-57` emits `repeated_schedule` with key `iteration_count`, not `iterations`.
  - Bundled defaults also use `iteration_count`: `config/defaults/dev.json:37-41`, `config/defaults/staging.json:37-41`, `config/defaults/prod.json:37-41`.
- Validation/normalization:
  - `src/release_confidence_platform/config/audit_validation_service.py:80-84` normalizes `repeated_schedule` into `normalized["repeated"]`.
  - `src/release_confidence_platform/audit_scheduling/validators.py:37-43` validates `repeated.get("iteration_count")`; no evidence of an `iterations` key in the schedule validators.
  - `src/release_confidence_platform/audit_scheduling/safeguards.py:135-137` also checks `event["repeated"]["iteration_count"]`.
- Schedule build path:
  - `src/release_confidence_platform/audit_scheduling/builders.py:198-201` builds scheduled repeated payloads as `{"iteration_count": repeated["iteration_count"], "execution_mode": "sequential"}`.
  - `src/release_confidence_platform/audit_scheduling/repeated.py:16-33` reads `event["repeated"]["iteration_count"]` and invokes the orchestrator once per iteration.
- Manual audit-run path:
  - `src/release_confidence_platform/core/manual_run_service.py:29-45` builds a manual Lambda payload with `scenario_type` and optional `schedule_type`, but no `repeated` block and no lookup of persisted audit config.
  - `src/release_confidence_platform/operator_cli/services.py:247-257` passes only CLI arguments into `ManualRunInvocationService.run(...)`.
- Core orchestrator execution:
  - `apps/backend/orchestrator/service.py:254-261` loads audit config and validates it, then returns endpoint config only; repeated schedule data is not returned to `run()`.
  - `apps/backend/orchestrator/service.py:116-151` executes `for endpoint in endpoints` and then `for iteration in range(1, endpoint.get("payload_iterations", 1) + 1)`. This is payload iteration, not repeated schedule iteration.
  - `apps/backend/orchestrator/service.py:310-319` builds raw result records from event fields plus `RunnerOutcome`; no repeated iteration field is added.
- Runner/raw schema evidence:
  - `apps/backend/runner/api_runner.py:28-43` defines `RunnerOutcome` without `iteration_index`, `iteration_number`, or schedule iteration metadata.
  - `packages/data_generation/generator.py:153-176` records payload metadata but does not include the current `iteration` value.
  - `tests/integration/test_phase3_scheduled_execution.py:76-88` asserts the scheduled repeated coordinator invokes the orchestrator 3 times with an `iteration` field, but the core validator/orchestrator raw result path does not preserve that field.

## 5. Execution Path / Failure Trace
Manual HITL run path:
1. Operator runs `rcp audit run --scenario-type repeated_stability`.
2. CLI calls `ManualRunInvocationService.run(...)`.
3. The service builds a direct orchestrator Lambda payload without `repeated` or `iteration_count`.
4. `CoreEngineOrchestrator.run()` validates the event, loads config, validates audit config, loads endpoints, and executes each endpoint using `payload_iterations` only.
5. Since generated/default endpoints generally have `payload_iterations` absent or `1`, each endpoint is executed once.
6. Raw results are written without repeated schedule iteration metadata.

Scheduled repeated path:
1. Schedule creation normalizes `repeated_schedule` to `repeated` and builds a repeated schedule payload with `repeated.iteration_count`.
2. `ScheduledExecutionHandler` routes repeated schedules through `RepeatedExecutionCoordinator`.
3. The coordinator loops `iteration_count` times and calls the orchestrator once per iteration.
4. The orchestrator ignores the extra `iteration` event field during validation/raw result creation, generates separate run IDs when none are supplied, and raw result records do not identify repeated iteration number.

## 6. Failure Classification
- Primary classification: Application Bug.
- Contributing classification: Contract Mismatch between generated config/schedule semantics and manual `repeated_stability` run behavior/raw evidence expectations.
- Severity: High.
  - Justification: HITL validation cannot confirm repeated-stability behavior from generated configs; repeated measurements are a core acceptance criterion for the default profile workflow and future aggregation depends on distinguishable repeated samples.

## 7. Root Cause Analysis
Most Likely Root Cause:
- The repository consistently uses `iteration_count` for repeated schedule configuration; the inspected generated configs, validators, safeguards, and schedule builder do not support or reference `iterations`. The suspected key mismatch is not supported by the inspected code.
- The primary defect is a missing application of `repeated_schedule.iteration_count` in the manual `rcp audit run --scenario-type repeated_stability` execution path. Manual audit run invokes the core orchestrator directly with only `scenario_type`; the core orchestrator does not branch on `scenario_type` or read normalized repeated schedule data.
- A secondary defect affects both manual and scheduled evidence: raw result records lack explicit repeated iteration metadata. Scheduled repeated execution loops exist, but the iteration value is passed as an extra event field that `validate_event()`/`OrchestratorEvent` do not retain, and `_raw_result()` cannot include it.

Immediate failure point:
- `apps/backend/orchestrator/service.py:118` loops on `endpoint.get("payload_iterations", 1)` rather than repeated schedule iteration count for `repeated_stability`.

Underlying root cause:
- Repeated schedule configuration is handled in the scheduler path, not in the direct/manual orchestrator run path, and the raw result contract has no repeated iteration field.

Plausible contributing factors:
- The project has two iteration concepts: endpoint-level `payload_iterations` and schedule-level `repeated_schedule.iteration_count`. The orchestrator currently implements only endpoint-level payload iterations.
- Manual `audit run` accepts `--scenario-type repeated_stability`, which implies repeated semantics to users but does not route through the scheduled repeated coordinator.

## 8. Confidence Level
High. The inspected code directly shows `iteration_count` is generated and validated, while the manual run/orchestrator path never reads it. Raw result dataclasses/builders also directly show no repeated iteration metadata field.

## 9. Recommended Fix
Likely owner: backend/full-stack CLI-runtime owner.

Recommended implementation approach:
1. Preserve `iteration_count` as the canonical config key. Do not rename to `iterations` unless product explicitly changes the contract; validators and generated configs already align on `iteration_count`.
2. Decide and implement one explicit execution contract for manual `repeated_stability`:
   - Option A: In `ManualRunInvocationService`/CLI run flow, load persisted audit config for `scenario_type=repeated_stability` and include a `repeated` block with `iteration_count` from audit config, then route to a repeated-aware handler/coordinator.
   - Option B: In `CoreEngineOrchestrator._load_and_validate_configs()` return enough audit config/schedule context for `run()` to detect `scenario_type == "repeated_stability"` and apply `repeated_schedule.iteration_count` as an outer execution loop.
   - Avoid multiplying baseline runs; only apply this to repeated schedule semantics, not `baseline_health` unless `baseline_schedule.requests_per_run` is intentionally implemented.
3. Add raw result iteration metadata:
   - Add repeated iteration metadata to the event model or run context (for example `iteration_index`/`iteration_number`, `iteration_count`, and `schedule_type` where available).
   - Include the metadata in each raw result record in `CoreEngineOrchestrator._raw_result()` or in `RunnerOutcome`.
   - Ensure scheduled repeated execution preserves the coordinator’s loop index instead of dropping the `iteration` field during `validate_event()`.
4. Keep endpoint `payload_iterations` separate from repeated schedule iterations. If both are configured, define and test the multiplication semantics clearly (for example repeated iterations as outer loop, payload iterations as inner payload-generation loop), with unambiguous metadata for both dimensions.

## 10. Suggested Validation Steps
- Unit/integration tests:
  - Generated audit config with `repeated_schedule.iteration_count = 5` and one endpoint should produce 5 raw result records or 5 per-iteration raw result objects with explicit iteration metadata.
  - Raw records for repeated runs include `iteration_index` or `iteration_number` values `[1, 2, 3, 4, 5]` and total count metadata if added.
  - `baseline_health` with default `requests_per_run = 1` remains single-pass.
  - `baseline_health` behavior with `requests_per_run > 1` is either implemented and tested or explicitly rejected/left unchanged per requirements.
  - Scheduled repeated handler still executes sequentially and now preserves iteration metadata in raw results.
  - Manual `rcp audit run --scenario-type repeated_stability` with persisted `iteration_count > 1` follows the approved manual-run contract.
- Edge cases:
  - `iteration_count = 1` remains backward compatible.
  - `iteration_count` at max cap is accepted; max + 1 is rejected by existing caps.
  - Missing or non-integer `iteration_count` fails validation for repeated schedules.
  - Endpoint-level `payload_iterations > 1` combined with repeated schedule iterations produces predictable counts and distinct metadata for schedule iteration vs payload iteration.
  - Static GET/no-body endpoints still include iteration metadata even when payload duplicate checking is bypassed.

## 11. Open Questions / Missing Evidence
- The exact HITL command output/raw S3 object was not provided, so this investigation is based on static code inspection and the reported symptom.
- Product decision needed: should manual `rcp audit run --scenario-type repeated_stability` honor persisted `repeated_schedule.iteration_count`, or should repeated iteration be guaranteed only via `rcp audit schedule` / scheduled execution? Current user expectation states manual/raw evidence should demonstrate multiple measurements.
- Product decision needed for `baseline_schedule.requests_per_run > 1`; current core orchestrator does not read this either.

## 12. Final Investigator Decision
Ready for developer fix.
