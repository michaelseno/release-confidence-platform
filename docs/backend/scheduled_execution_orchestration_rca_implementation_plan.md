# Implementation Plan

## 1. Feature Overview
Fix scheduled baseline execution orchestration so each intended baseline occurrence has deterministic occurrence identity and duplicate deliveries remain idempotent.

## 2. Technical Scope
Replace recurring baseline `rate(...)` schedule generation with bounded discrete `at(...)` schedule definitions, add deterministic occurrence IDs, preserve duplicate claim behavior, add scheduled handler observability, and update relevant tests.

## 3. Source Inputs
- `docs/bugs/scheduled_execution_orchestration_rca.md`
- `docs/architecture/adr_scheduled_execution_occurrence_identity.md`
- `docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md`

## 4. API Contracts Affected
No public API contract changes. EventBridge scheduled execution target payloads retain the existing Phase 3 scheduled event contract and continue to omit `run_id`.

## 5. Data Models / Storage Affected
No table schema changes. Occurrence claim keys continue to use `schedule_occurrence_id`, now deterministic per intended occurrence time. Audit schedule metadata may contain multiple baseline schedule entries.

## 6. Files Expected to Change
- `packages/audit_scheduling/builders.py`
- `packages/audit_scheduling/constants.py`
- `src/release_confidence_platform/audit_scheduling/builders.py`
- `src/release_confidence_platform/audit_scheduling/constants.py`
- `apps/backend/handlers/scheduled_execution_handler.py`
- Phase 3 and operator scheduling tests

## 7. Security / Authorization Considerations
Scheduled payloads remain secret-free and continue to omit `run_id`. Logs are structured and sanitized through existing sanitizer/logger paths and avoid raw payloads, tokens, credentials, and large bodies.

## 8. Dependencies / Constraints
No new dependencies. Baseline schedule expansion is bounded by the existing 48-hour audit window and a conservative maximum of 192 baseline occurrences per audit.

## 9. Assumptions
The approved default 48-hour audit window and 15-minute baseline cadence define the expected maximum baseline occurrence count: 192.

## 10. Validation Plan
- `python -m ruff check <changed files>`
- `python -m pytest tests/unit/test_phase3_schedule_builders.py tests/integration/test_phase3_scheduling_lifecycle.py tests/integration/test_phase3_scheduled_execution.py tests/integration/test_phase3_duplicate_delivery.py tests/integration/test_phase3_cancellation_finalization.py`
- `python -m pytest tests/unit/test_phase3_*.py tests/integration/test_phase3_*.py`
- `python -m pytest`
