# Implementation Report

## 1. Summary of Changes
Implemented backward-compatible expected-status assertion normalization so top-level `expected_status_codes` and `expected_status_code` aliases are honored by both validator mirrors and normalized into `assertions.expected_status_codes` before runner execution.

## 2. Files Modified
- `packages/config/validators.py` — added expected-status normalization, validation, alias handling, and conflict detection.
- `src/release_confidence_platform/config/validators.py` — mirrored the same validator behavior for the packaged source path.
- `tests/unit/test_phase1_core_engine.py` — added validator, runner, and orchestrator raw-result regression coverage.
- `tests/unit/test_operator_cli_rcp.py` — added sample endpoint shape regression coverage.
- `docs/backend/endpoint_status_assertion_precedence_implementation_plan.md` — implementation plan.
- `docs/backend/endpoint_status_assertion_precedence_implementation_report.md` — this report.

## 3. API Contract Implementation
No API contract changes. Existing audit execution continues to consume endpoint config and persist raw results; normalized assertions now ensure raw `assertion_results.expected_status_codes` reflects configured endpoint intent.

## 4. Data / Persistence Implementation
No storage schema changes. Raw result persistence remains unchanged and continues to serialize runner output. The runner now receives normalized assertions from validation when top-level aliases are used.

## 5. Key Logic Implemented
- Normalizes top-level `expected_status_codes: [..]` into `assertions.expected_status_codes`.
- Normalizes top-level `expected_status_code: 200` into `assertions.expected_status_codes: [200]`.
- Preserves nested `assertions.expected_status_codes` as the preferred/current emitted shape.
- Allows agreeing top-level and nested values.
- Fails validation when top-level and nested values conflict.
- Removes normalized top-level alias keys from the validated endpoint object.

## 6. Security / Authorization Implemented
No auth changes. Input validation was tightened to reject booleans, non-integers, empty lists, and status codes outside `100..599` before execution.

## 7. Error Handling Implemented
Expected-status validation failures raise `ConfigError` with `CONFIG_VALIDATION_ERROR`, including actionable conflict messaging for disagreeing assertion placements.

## 8. Observability / Logging
No logging changes. Existing runner raw-result assertion metadata remains the source of truth for the assertion set actually used.

## 9. Assumptions Made
- Backward-compatible normalization was selected per task instruction because no explicit product spec requiring strict rejection was identified.
- Valid HTTP status-code range is `100..599`.

## 10. Validation Performed
- `pytest tests/unit/test_phase1_core_engine.py tests/unit/test_operator_cli_rcp.py -q` — `99 passed in 0.39s`.
- Re-run after cleanup: `pytest tests/unit/test_phase1_core_engine.py tests/unit/test_operator_cli_rcp.py -q` — `99 passed in 0.40s`.

## 11. Known Limitations / Follow-Ups
- No live AWS validation was performed per constraints.
- Existing deployed backend will still require redeploy before HITL/live validation can observe the fix.

## 12. Commit Status
No commit created per instruction: do not commit, push, or create PR.
