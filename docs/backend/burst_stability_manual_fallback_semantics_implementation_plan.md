# Implementation Plan

## 1. Feature Overview
Implement true `burst_stability` execution semantics for manual and scheduled audit runs, including manual fallback defaults, scheduled burst strictness, cap enforcement, global concurrency, and burst evidence fields in raw results.

## 2. Technical Scope
- Preserve `schedule_type`, `scheduled_at`, and `burst` metadata through event validation and scheduled handler invocation.
- Generate and validate `burst_schedule.manual_burst_defaults` for config init profiles.
- Add orchestrator burst resolution for manual fallback and scheduled-window modes.
- Dispatch exactly `request_count` total burst requests with bounded global concurrency and round-robin endpoint distribution.
- Emit burst metadata in each raw result entry.

## 3. Source Inputs
- `docs/bugs/burst_stability_manual_fallback_semantics_bug_report.md`
- `docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md`
- `docs/architecture/enhanced_config_init_default_profile_system_technical_design.md`
- Existing orchestrator, scheduled execution, config init, and test patterns.

## 4. API Contracts Affected
No public HTTP API contract changes.

Backend event contracts affected:
- Orchestrator event now preserves optional `schedule_type`, `scheduled_at`, and `burst` metadata.
- Scheduled execution handler forwards scheduled metadata to the orchestrator for non-repeated scheduled executions.

## 5. Data Models / Storage Affected
Raw result records for `burst_stability` now include burst evidence fields:
- `burst_mode`
- `burst_request_number`
- `burst_request_count`
- `burst_concurrency`
- `burst_window_id`
- `burst_window_start`
- `iteration_number`
- `iteration_count`

Generated audit config defaults now include `burst_schedule.manual_burst_defaults`.

## 6. Files Expected to Change
- `apps/backend/orchestrator/service.py`
- `apps/backend/handlers/scheduled_execution_handler.py`
- `packages/core/validators.py`
- `src/release_confidence_platform/core/validators.py`
- `packages/audit_scheduling/events.py`
- `packages/audit_scheduling/safeguards.py`
- `src/release_confidence_platform/audit_scheduling/safeguards.py`
- `src/release_confidence_platform/config/generators/audit_config_generator.py`
- `src/release_confidence_platform/operator_cli/default_profiles.py`
- `config/defaults/*.json`
- Targeted unit/integration tests.

## 7. Security / Authorization Considerations
- No secrets are added to schedule/orchestrator payloads or logs.
- Scheduled burst execution fails before outbound requests when required scheduled metadata/configured windows are absent.
- Production/environment safeguards remain enforced through existing safeguard paths.
- Request count and concurrency are capped before burst dispatch.

## 8. Dependencies / Constraints
- No new third-party dependencies.
- Uses standard-library `ThreadPoolExecutor` for bounded global concurrency.
- No AWS deployment or remote calls.
- Active branch remains unchanged; no commit per HITL correction instruction.

## 9. Assumptions
- Scheduled orchestrator strictness can require `burst_schedule.enabled=true`, at least one configured window, and incoming scheduled `burst` metadata; exact date/window matching is not broadened beyond available metadata.
- Manual burst defaults present with `enabled=false` are treated as disabled and fail clearly rather than silently executing.
- Manual defaults above caps are clamped to caps per confirmed HITL edge-case guidance.

## 10. Validation Plan
- Run targeted pytest for config init, event contracts, safeguards, scheduled execution, and orchestrator burst behavior.
- Run prior orchestrator/repeated stability tests to verify regression safety.
