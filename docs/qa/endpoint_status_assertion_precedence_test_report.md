# Test Report

## 1. Execution Summary

- Total tests: 306 full pytest regression tests, plus Ruff format/lint gates.
- Passed: 306 pytest tests; Ruff format and lint passed.
- Failed: 0 unresolved failures.
- Branch verified active: `feature/profile_driven_config_init`.
- AWS deployment/live redeploy: not performed per QA constraint.

## 2. Detailed Results

| Test / Gate | Outcome | Evidence |
| --- | --- | --- |
| Targeted endpoint assertion QA + developer regression subset | PASS | `./.venv/bin/python -m pytest tests/api/test_endpoint_status_assertion_precedence_qa.py tests/unit/test_phase1_core_engine.py tests/unit/test_operator_cli_rcp.py -q` -> `130 passed in 0.42s` |
| Ruff format gate | PASS | `./.venv/bin/python -m ruff format --check .` -> `189 files already formatted` |
| Ruff lint gate | PASS | `./.venv/bin/python -m ruff check .` -> `All checks passed!` |
| Full pytest regression suite | PASS | `./.venv/bin/python -m pytest -q` -> `306 passed in 0.82s` |

Targeted coverage confirmed:

- Nested `assertions.expected_status_codes: [200]` remains honored.
- Top-level `expected_status_codes: [200]` normalizes into nested assertions.
- Top-level `expected_status_code: 200` normalizes into nested `[200]`.
- Endpoint-level `[200]` overrides fallback `[200..399]`.
- Runner `assertion_results.expected_status_codes` reflects `[200]` when configured.
- `302` fails when `[200]` is configured.
- Missing assertions intentionally default to `[200..399]` and accept `302`.
- Agreeing top-level/nested values normalize; conflicts fail with `CONFIG_VALIDATION_ERROR`.
- Empty, boolean, non-integer, and out-of-range status values are rejected.
- Generated sample endpoints continue to emit preferred nested assertions and no top-level alias keys.
- Runtime validator mirror (`packages/config/validators.py`) and source validator mirror (`src/release_confidence_platform/config/validators.py`) behave consistently.

## 3. Failed Tests

No unresolved failed tests.

Historical execution notes:

- `python -m ...` failed because `python` was not on PATH.
- `python3 -m ...` failed because global Python 3.13 lacked `pytest` and `ruff`.
- Initial QA test iteration had a test-data issue using short IDs shorter than the product validator requires; fixed by using valid 8-character lowercase hex IDs.

## 4. Failure Classification

No application failures remain.

Resolved non-application issues:

- Environment Issue: `python` command unavailable and global `python3` missing QA dependencies. Reproduced by `python -m pytest ...` and `python3 -m pytest ...`; mitigated by using repository virtual environment `./.venv/bin/python`.
- Test Bug: QA sample endpoint test used invalid `client_shortid="qa01"` / `audit_shortid="qa02"`; product requires lowercase hex with at least 8 characters. Corrected to valid deterministic hex IDs.

## 5. Observations

- No flakiness observed in repeated targeted execution or full pytest execution.
- Raw assertion metadata remains runner-derived, which is appropriate because it reflects the actual assertion set evaluated.
- No AWS calls or deployment were performed.

## 6. Regression Check

Full pytest passing confirms regression protection for prior HITL fixes covered by the current repository suite, including config-init, audit-create paths, stage-info, Lambda packaging, orchestrator observability, S3/DynamoDB diagnostics, static GET duplicate bypass, and repeated iteration metadata.

## 7. QA Decision

Approved. All critical acceptance criteria passed with automated evidence, no blocking defects, no unresolved failures, and no major regressions detected.
