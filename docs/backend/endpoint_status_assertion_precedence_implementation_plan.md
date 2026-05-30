# Implementation Plan

## 1. Feature Overview
Fix endpoint expected-status assertion precedence so runtime config validation honors endpoint-level status assertion aliases by normalizing them into `assertions.expected_status_codes` before runner execution.

## 2. Technical Scope
- Update both validator mirrors to normalize top-level `expected_status_codes` and `expected_status_code` into nested assertions.
- Reject conflicting top-level and nested expected-status values with `CONFIG_VALIDATION_ERROR`.
- Validate expected-status values before runner execution.
- Add targeted tests for normalization, conflicts, invalid values, runner behavior, raw result output, and sample endpoint shape.

## 3. Source Inputs
- `docs/bugs/endpoint_status_assertion_precedence_bug_report.md`
- `docs/architecture/phase_1_core_engine_foundation_technical_design.md`
- Existing validator, runner, orchestrator, and config-init test patterns.

## 4. API Contracts Affected
No API contract changes. This is backend config validation and runtime normalization behavior for existing audit execution paths.

## 5. Data Models / Storage Affected
No data model or storage changes. Raw results continue to persist runner `assertion_results`; normalized assertions affect the assertion metadata already emitted by the runner.

## 6. Files Expected to Change
- `packages/config/validators.py`
- `src/release_confidence_platform/config/validators.py`
- `tests/unit/test_phase1_core_engine.py`
- `tests/unit/test_operator_cli_rcp.py` or equivalent config-init tests
- `docs/backend/endpoint_status_assertion_precedence_implementation_report.md`

## 7. Security / Authorization Considerations
No authentication or authorization changes. Input validation is tightened for expected-status assertions to reject empty, boolean, non-integer, and out-of-range status-code values.

## 8. Dependencies / Constraints
No new dependencies. Must not deploy, change branches, commit, push, or create PR. Current branch must remain `feature/profile_driven_config_init`.

## 9. Assumptions
- Backward-compatible normalization is required by task instruction because no explicit product spec mandating strict rejection was identified.
- HTTP status range validation uses `100..599`, matching conventional HTTP status-code bounds.

## 10. Validation Plan
- Run targeted unit tests covering endpoint validator, API runner, raw result serialization, and sample endpoint generation.
- Run syntax/import validation through pytest collection and targeted tests where possible.
