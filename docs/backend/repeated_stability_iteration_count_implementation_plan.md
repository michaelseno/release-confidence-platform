# Implementation Plan

## 1. Feature Overview
Fix manual and scheduled `repeated_stability` backend execution so persisted `repeated_schedule.iteration_count` is applied and raw evidence records preserve repeated-iteration metadata.

## 2. Technical Scope
Update the core orchestrator to load repeated schedule settings from the audit config for `scenario_type=repeated_stability`, execute schedule-level iterations separately from endpoint `payload_iterations`, and write both schedule- and payload-iteration metadata into each raw result record. Preserve baseline default single-pass behavior.

## 3. Source Inputs
- `docs/bugs/repeated_stability_iteration_count_not_applied_bug_report.md`
- `docs/architecture/enhanced_config_init_default_profile_system_technical_design.md`
- Existing orchestrator, scheduling, payload generation, and test patterns.

## 4. API Contracts Affected
No public HTTP API contract changes. Existing orchestrator Lambda/event payloads continue to accept manual and EventBridge-shaped events. Raw result evidence records gain iteration metadata fields for backend aggregation.

## 5. Data Models / Storage Affected
No storage schema or table/index changes. Raw result JSON records written to S3 include schedule iteration and payload iteration metadata fields.

## 6. Files Expected to Change
- `apps/backend/orchestrator/service.py`
- `packages/core/validators.py`
- `src/release_confidence_platform/core/validators.py`
- `packages/audit_scheduling/repeated.py`
- `src/release_confidence_platform/audit_scheduling/repeated.py`
- `tests/unit/test_phase1_core_engine.py`
- `tests/integration/test_phase3_scheduled_execution.py`
- backend implementation docs under `docs/backend/`

## 7. Security / Authorization Considerations
No authentication model changes. Continue existing client/audit config loading and validation. Validate `iteration_count` is a positive integer within the existing repeated cap before execution to prevent unbounded runs.

## 8. Dependencies / Constraints
No new dependencies. Use existing `MAX_REPEATED_ITERATIONS`, config loaders, validators, and sanitized raw-result path. Do not deploy, redesign scheduling, or commit.

## 9. Assumptions
- Schedule-level repeated iterations are the outer loop; endpoint `payload_iterations` remain the inner loop.
- For scheduled repeated execution, the coordinator-provided iteration identifies the single schedule iteration executed by that orchestrator invocation.
- Baseline `requests_per_run` remains outside this fix scope and unchanged.

## 10. Validation Plan
- `python3.11 -m pytest tests/unit/test_phase1_core_engine.py tests/integration/test_phase3_scheduled_execution.py -q`
