# Bug Report

## 1. Summary

During HITL validation for Enhanced `rcp config init` Default Profile System, `burst_stability` was found to be triggerable manually but not implemented as true burst execution. Current behavior executes the normal orchestrator endpoint loop once per endpoint/payload iteration, with no global request count, no global concurrency, no manual fallback burst defaults, and no burst evidence fields in raw results.

## 2. Investigation Context

- Source of report: HITL validation.
- Active branch: `feature/profile_driven_config_init`.
- Related workflow: `rcp config init`, `rcp audit run --scenario-type burst_stability`, scheduled burst execution.
- User-confirmed implementation-ready requirements:
  - Manual fallback defaults: `request_count=10`, `concurrency=2`, `burst_mode="manual_fallback"`, nullable window metadata.
  - `request_count` is total requests across the burst run.
  - `concurrency` is global max concurrent requests across the burst run.
  - Scheduled burst must require enabled configured burst window and must not use manual fallback defaults.

## 3. Observed Symptoms

- Manual `burst_stability` can be invoked through the CLI because `src/release_confidence_platform/operator_cli/main.py` includes `burst_stability` in valid `--scenario-type` choices.
- `ManualRunInvocationService.run()` emits only a generic orchestrator payload with `triggered_by="manual"` and `schedule_type="manual"`; it does not include burst defaults or a burst execution contract.
- `CoreEngineOrchestrator.run()` treats non-repeated scenarios identically: `_resolve_schedule_iteration_count()` returns `1` for every scenario except `repeated_stability`, then the main loop executes each endpoint/payload iteration sequentially.
- `ApiRunner.execute()` has only a single-request synchronous method and no concurrency primitive.
- Raw result records include generic iteration fields but no required burst fields (`burst_mode`, `burst_request_number`, `burst_request_count`, `burst_concurrency`, `burst_window_id`, `burst_window_start`).
- Scheduled burst payloads are built with `burst` metadata, but `ScheduledExecutionHandler.handle()` drops that metadata before calling the orchestrator, so scheduled burst also degrades to ordinary one-pass execution.

Expected behavior per confirmed requirements: `burst_stability` must always produce actual burst semantics, with one raw result per burst request and clear evidence distinguishing manual fallback from scheduled burst-window execution.

## 4. Evidence Collected

Files inspected:

- `src/release_confidence_platform/operator_cli/main.py`
  - `burst_stability` is an allowed manual scenario type.
- `src/release_confidence_platform/core/manual_run_service.py`
  - Lines 29-45 build payload with `scenario_type`, `triggered_by="manual"`, `schedule_type="manual"`; no burst defaults are attached.
- `src/release_confidence_platform/core/validators.py` and `packages/core/validators.py`
  - `OrchestratorEvent` has only client/audit/scenario/trigger/run/repeated iteration fields; no `schedule_type` or `burst` fields are parsed.
- `apps/backend/orchestrator/service.py`
  - Lines 129-181 execute nested sequential loops over schedule iterations, endpoints, and payload iterations.
  - Lines 297-301 return iteration count `1` for every non-`repeated_stability` scenario.
  - Lines 401-425 write raw result records without burst fields.
- `apps/backend/runner/api_runner.py`
  - Lines 49-152 expose only synchronous single-request `execute()`; no global concurrency or batch/burst method exists.
- `src/release_confidence_platform/audit_scheduling/builders.py`
  - Lines 152-165 attach scheduled burst `request_count`, `concurrency`, `window_start`, and `window_end` to schedule payloads.
- `apps/backend/handlers/scheduled_execution_handler.py`
  - Lines 98-105 call `orchestrator.run()` with only `client_id`, `audit_id`, `scenario_type`, and `triggered_by`, dropping `schedule_type`, `scheduled_at`, and `burst` metadata.
- `src/release_confidence_platform/config/generators/audit_config_generator.py`
  - Lines 49-50 generate `burst_schedule` as either profile-provided value or `{"enabled": false, "windows": []}`; no `manual_burst_defaults`.
- `config/defaults/dev.json`
  - Line 36 contains `"burst_schedule": {"enabled": false, "windows": []}`; no `manual_burst_defaults`. Staging/prod profiles follow the same profile schema pattern.
- `src/release_confidence_platform/operator_cli/default_profiles.py`
  - `_validate_schedule_defaults()` only requires schedule blocks and does not validate/manual-default fields.
- `src/release_confidence_platform/audit_scheduling/safeguards.py` and `packages/audit_scheduling/safeguards.py`
  - `effective_caps()` derives fixed caps from `execution_environment` target env only, not from `audit_config.operational_caps`, `client_config.operational_caps`, or `client_config.request_defaults`.
  - `ensure_execution_allowed()` enforces caps only when event has a `burst` object.
- `docs/product/phase_3_audit_scheduling_lifecycle_product_spec.md`
  - FR-007 states burst schedules require configurable concurrency and request counts and must validate caps before schedules or execution.

## 5. Execution Path / Failure Trace

Manual path today:

1. Operator invokes `rcp audit run --scenario-type burst_stability`.
2. `ManualRunInvocationService.run()` creates a generic manual payload with no burst metadata.
3. `validate_event()` discards/ignores schedule type and has no burst fields even if supplied.
4. Orchestrator loads configs and sets schedule iteration count to `1` because the scenario is not `repeated_stability`.
5. Orchestrator executes each endpoint sequentially once per payload iteration.
6. Raw results are written as ordinary results and do not identify manual fallback or burst request numbering.

Scheduled path today:

1. `ScheduleDefinitionBuilder.build_burst()` correctly creates a schedule event containing `burst.request_count`, `burst.concurrency`, `window_start`, and `window_end`.
2. `ScheduledExecutionHandler.handle()` validates/caps that incoming event, but passes only generic fields into `orchestrator.run()`.
3. Orchestrator executes ordinary one-pass semantics and raw results lose the configured burst-window evidence.

## 6. Failure Classification

- Primary classification: Application Bug.
- Contributing classification: Contract Mismatch, because runtime behavior and raw evidence shape do not satisfy the now-confirmed burst contract.
- Severity: High.

Severity justification: `burst_stability` is an accepted scenario type and a scheduled feature, but it does not exercise burst request count/concurrency semantics. This invalidates core evidence for concurrency stability and fails HITL acceptance for the current feature correction branch.

## 7. Root Cause Analysis

Most Likely Root Cause: Burst execution was modeled at scheduling/configuration level but never carried through the orchestrator/runner execution contract.

Immediate failure point:

- The orchestrator has no burst branch; it always uses the same sequential endpoint loop except for repeated iteration count handling.
- Scheduled handler drops `burst` metadata before invoking the orchestrator.

Underlying gaps:

- Event contract lacks `schedule_type`, `scheduled_at`, and `burst` fields needed to distinguish manual fallback from scheduled burst execution.
- `ApiRunner` has no reusable bounded-concurrency execution capability.
- Generated audit configs and default profiles lack `burst_schedule.manual_burst_defaults`.
- Caps are not resolved in the required order across audit/client config sources.
- Raw result shape lacks burst evidence fields.
- Scheduled strictness is missing at the orchestrator boundary; scheduled `burst_stability` without a configured enabled burst window can fall through to generic execution if called without `burst` metadata.

## 8. Confidence Level

High. The inspected code directly shows the missing event fields, dropped scheduled burst payload, sequential orchestrator loop, synchronous single-request runner, missing generated defaults, and missing raw result fields.

## 9. Recommended Fix

Likely owner: full-stack/backend platform engineer.

Recommended implementation approach within existing architecture:

1. Extend the backend event contract in both `src/release_confidence_platform/core/validators.py` and `packages/core/validators.py`:
   - Preserve optional `schedule_type`, `scheduled_at`, and `burst` metadata on `OrchestratorEvent`.
   - Validate burst payload fields as positive integers where present.

2. Preserve scheduled burst payload in `apps/backend/handlers/scheduled_execution_handler.py`:
   - When invoking `orchestrator.run()`, pass `schedule_type`, `scheduled_at`, and `burst` for burst schedule events.
   - Do not synthesize manual fallback defaults in this scheduled path.

3. Add manual fallback config generation:
   - Update bundled defaults under `config/defaults/*.json` and `generate_audit_config()` to emit:
     ```json
     "manual_burst_defaults": {"enabled": true, "request_count": 10, "concurrency": 2}
     ```
     under `burst_schedule`.
   - Update default profile validation to allow and validate these fields.

4. Add burst resolution in `apps/backend/orchestrator/service.py`:
   - If `scenario_type == "burst_stability"` and `triggered_by == "manual"` / `schedule_type == "manual"`, resolve manual defaults from `audit_config.burst_schedule.manual_burst_defaults` when present, otherwise use defensive safe fallback only if the field is missing.
   - If `scenario_type == "burst_stability"` and `triggered_by != "manual"` or `schedule_type == "burst"`, require an enabled configured burst window or incoming scheduled `burst` metadata tied to such a window; fail clearly if absent.
   - Enforce effective `request_count <= max_requests_per_run` and `concurrency <= max_concurrency` before outbound requests.

5. Implement required cap-source resolution order in a shared helper:
   1. `audit_config.operational_caps`
   2. `audit_config.execution_environment`
   3. `client_config.operational_caps`
   4. `client_config.request_defaults`
   5. hardcoded safe fallback
   Apply this helper in orchestrator burst resolution and, where applicable, creation/scheduling metadata so runtime and config evidence align.

6. Add bounded burst execution support:
   - Keep `ApiRunner.execute()` as the single-request primitive.
   - Add an orchestrator-level bounded concurrent burst dispatcher, or an `ApiRunner.execute_many_bounded()` wrapper, using global concurrency across the whole request plan.
   - Generate exactly `request_count` total request executions across the run. If multiple endpoints exist, define deterministic distribution (for example round-robin across validated endpoints) and document it in tests.

7. Extend raw results in `_raw_result()` for burst requests:
   - Add `burst_mode`, `burst_request_number`, `burst_request_count`, `burst_concurrency`, `burst_window_id`, `burst_window_start`, `iteration_number`, and `iteration_count` per request.
   - For manual fallback: `burst_mode="manual_fallback"`, `burst_window_id=None`, `burst_window_start=None`.
   - For scheduled burst: use a scheduled/configured mode and populate window evidence from schedule/config.

8. Keep duplicate packages synchronized:
   - Backend imports `packages.*`, while CLI/source tests use `src/release_confidence_platform.*`. Update both where mirrored modules exist.

## 10. Suggested Validation Steps

Targeted tests:

- Config init:
  - Generated `audit_config.json` includes `burst_schedule.manual_burst_defaults.enabled=true`, `request_count=10`, `concurrency=2`.
  - Profile validation rejects invalid manual burst defaults and remains secret-safe.
- Manual burst:
  - `rcp audit run --scenario-type burst_stability` without configured windows executes successfully using manual fallback defaults.
  - Raw evidence contains exactly 10 burst result records with global `burst_request_number` 1-10, `burst_request_count=10`, `burst_concurrency=2`, `burst_mode="manual_fallback"`, nullable window fields.
  - Caps clamp/reject defaults if configured caps are lower than requested values; expected behavior should be explicit in tests.
- Scheduled burst:
  - Enabled configured burst window executes with configured `request_count` and `concurrency` and ignores manual defaults.
  - Scheduled burst without enabled window or without required `burst` metadata fails clearly before outbound requests.
  - Scheduled handler preserves `burst` metadata into orchestrator payload.
- Caps:
  - Unit tests cover all required cap source precedence levels.
  - Production/prod alias caps still block unsafe execution unless explicitly allowed.
- Runner/orchestrator:
  - Concurrency never exceeds global configured burst concurrency across all endpoints.
  - Multiple endpoints receive exactly total `request_count` requests, not `request_count` per endpoint.
  - Every burst request writes an individual raw result entry.

## 11. Open Questions / Missing Evidence

- No additional user info is required for the confirmed requirements listed in this report.
- Implementation should still choose and document a deterministic endpoint distribution strategy when `request_count` is not evenly divisible by endpoint count.
- If configured manual defaults exceed caps, downstream implementation must decide whether to fail clearly or reduce to cap; requirement says enforce `<=`, so fail-fast is safest unless product directs clamping.

## 12. Final Investigator Decision

Ready for developer fix.
