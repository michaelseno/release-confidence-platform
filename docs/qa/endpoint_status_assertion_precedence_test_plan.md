# Test Plan

## 1. Feature Overview

Validate the HITL blocker fix for endpoint expected-status assertion precedence. Endpoint-level configured status assertions must be normalized before runner execution so raw `assertion_results.expected_status_codes` reflects the actual configured set, not the fallback `[200..399]`, while preserving the intentional fallback when no assertion is configured.

## 2. Acceptance Criteria Mapping

| ID | Acceptance Criteria | Validation |
| --- | --- | --- |
| AC1 | Nested `assertions.expected_status_codes: [200]` works | Mirrored validator normalization tests |
| AC2 | Top-level `expected_status_codes: [200]` normalizes into nested assertions | Mirrored validator normalization tests and runner assertion-results test |
| AC3 | Top-level `expected_status_code: 200` normalizes if implemented | Mirrored validator normalization tests |
| AC4 | Endpoint-level status overrides default `[200..399]` | Runner returns `[200]` and fails `302` |
| AC5 | Raw/result assertion metadata reflects `[200]` | Runner assertion-results test plus existing orchestrator raw-result regression |
| AC6 | `302` fails when `[200]` is configured | Runner failure assertion test |
| AC7 | Missing assertions default to `[200..399]` | Runner default fallback test |
| AC8 | Agreeing top-level/nested normalize; conflicts fail | Mirrored agree/conflict tests |
| AC9 | Invalid lists/values rejected | Mirrored invalid value tests for empty, boolean, non-integer, out-of-range |
| AC10 | Generated samples emit preferred nested assertions | Config-init sample endpoint regression test |
| AC11 | Mirrored runtime/source validators are consistent | Parametrized tests execute both mirrors |
| AC12 | Prior HITL fixes still pass | Existing regression suites and full pytest |
| AC13 | Ruff/format gates and full pytest pass | Command execution evidence in report |

## 3. Test Scenarios

1. Validate nested `[200]` remains unchanged in both validator mirrors.
2. Validate top-level list alias `[200]` normalizes into `assertions.expected_status_codes` and alias keys are removed.
3. Validate top-level singular alias `200` normalizes into `[200]`.
4. Validate agreeing top-level and nested status values normalize without error.
5. Validate conflicting top-level/nested and top-level alias combinations fail with `CONFIG_VALIDATION_ERROR`.
6. Validate invalid expected-status values fail before runner execution.
7. Validate runner assertion metadata is `[200]` and a `302` response fails when `[200]` is configured.
8. Validate missing assertion fallback still accepts `302` with expected set `[200..399]`.
9. Validate generated config-init sample endpoints use nested assertion shape only.
10. Execute broader regression suites covering prior HITL fixes and full test inventory.

## 4. Edge Cases

- Empty expected-status list.
- Boolean values and booleans inside lists.
- String/float non-integer values.
- HTTP status codes below `100` and above `599`.
- Conflicting aliases across top-level and nested placements.
- Missing assertions with fallback behavior.

## 5. Test Types Covered

- Functional validation: validator normalization and runner behavior.
- Negative validation: invalid inputs and conflicts.
- Edge validation: boundary/out-of-range and empty-list handling.
- Integration/regression: orchestrator raw result coverage and config-init sample output.
- Static quality gates: Ruff check and Ruff format check.
- Full regression: complete pytest suite.

## 6. Coverage Justification

The targeted QA tests cover every configured status assertion placement and failure mode identified in the bug report. The existing developer regressions add orchestrator raw-result persistence coverage. Full pytest and Ruff gates protect prior HITL fixes and unrelated behavior without AWS deployment.
