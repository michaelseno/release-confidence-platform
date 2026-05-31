# Test Report

## 1. Execution Summary

- Total command results considered: previous focused HITL suite, previous scheduling/finalization suite, previous full suite, plus post-quality-review focused finalization/scheduled execution suite and post-fix full suite. Counts are overlapping by design and are used as command evidence, not unique test totals.
- Latest post-quality-review focused regression result: 16 passed, 0 failed.
- Latest post-quality-review full-suite result: 354 passed, 1 skipped, 0 failed.
- Failed: 0
- Skipped: 1 in latest full suite
- QA-local execution note: QA-local shell remained permission-blocked for pytest; execution evidence was provided by the orchestrator from the active workspace on branch `bugfix/scheduled_execution_orchestration_rca`.
- QA status: approved based on static inspection plus orchestrator-captured execution evidence, including the newly added explicit duplicate finalization idempotency test.

## 2. Detailed Results

| Evidence Item | Scope | Outcome |
|---|---|---|
| Static inspection: `src/release_confidence_platform/storage/audit_metadata_client.py` | Repository canonical audit filtering and pagination | Inspected. `list_audits_for_client` positively filters canonical rows using `_is_canonical_audit_metadata_item`, continues pagination while canonical result count is below requested limit, and passes `ExclusiveStartKey` when DynamoDB returns `LastEvaluatedKey`. |
| Static inspection: `src/release_confidence_platform/operator_cli/discovery_service.py` | Service-level canonical filtering | Inspected via grep. `DiscoveryListService.list_audits` filters items through `_is_canonical_audit_item` before producing output. |
| Static inspection: `src/release_confidence_platform/operator_cli/result.py` | `FORCE_RECREATE_BLOCKED` guidance | Inspected. Guidance states force recreate is allowed only for DRAFT or FAILED, instructs `rcp audit list`, recommends fresh audit ID/config bundle for Phase 3 ineligible states, and warns against manual DynamoDB lifecycle mutation. |
| Static inspection: `tests/unit/test_operator_cli_discovery.py` | AC1/AC2 regression coverage | Inspected. Contains `test_audit_list_queries_by_client_and_filters_child_records` and `test_audit_metadata_repository_filters_canonical_rows_across_query_pages`. |
| Static inspection: `tests/unit/test_operator_cli_result.py` | AC3 regression coverage | Inspected. Contains guidance assertions for DRAFT/FAILED, audit list, fresh audit ID/config bundle, and DynamoDB mutation warning. |
| Static inspection: `tests/unit/test_operator_cli_rcp.py` | AC4 regression coverage | Inspected. Contains allowed DRAFT/FAILED force recreate test and blocked FINALIZING/SCHEDULED/RUNNING/COMPLETED test. |
| Static inspection: `tests/integration/test_phase3_cancellation_finalization.py` | AC5/AC6/AC7 regression coverage | Inspected. Contains nonzero finalization remains FINALIZING, zero-execution transitions to FAILED, and explicit duplicate finalization idempotency coverage in `test_duplicate_finalization_delivery_skips_existing_finalizing_or_terminal_state`. The duplicate finalization test is parametrized for `FINALIZING`, `COMPLETED`, `FAILED`, and `CANCELLED`; it verifies `status: skipped`, lifecycle state unchanged, no lifecycle history appended, and existing finalization metadata not overwritten. |
| Orchestrator execution: `python -m pytest tests/unit/test_operator_cli_discovery.py tests/api/test_operator_cli_discovery_contract.py tests/unit/test_operator_cli_result.py tests/unit/test_operator_cli_rcp.py -q` | Focused HITL CLI/discovery/result/create coverage for AC1-AC4 | Passed: `86 passed in 0.38s`. |
| Orchestrator execution: `python -m pytest tests/integration/test_phase3_cancellation_finalization.py tests/integration/test_phase3_scheduled_execution.py tests/integration/test_phase3_duplicate_delivery.py tests/integration/test_phase3_scheduling_lifecycle.py tests/unit/test_phase3_schedule_builders.py -q` | Scheduling/finalization regression coverage for AC5-AC8 | Passed: `30 passed in 0.21s`. |
| Orchestrator execution: `python -m pytest` | Full regression suite | Passed with one skip: collected 351 items; `350 passed, 1 skipped in 0.86s`. |
| Orchestrator execution after quality-review blocker fix: `python -m pytest tests/integration/test_phase3_cancellation_finalization.py tests/integration/test_phase3_duplicate_delivery.py tests/integration/test_phase3_scheduled_execution.py` | Explicit duplicate finalization idempotency plus scheduled execution regression coverage for AC5-AC8 | Passed: collected 16 items; `tests/integration/test_phase3_cancellation_finalization.py ........`; `tests/integration/test_phase3_duplicate_delivery.py ...`; `tests/integration/test_phase3_scheduled_execution.py .....`; final `16 passed in 0.22s`. |
| Orchestrator execution after quality-review blocker fix: `python -m pytest` | Full regression suite after explicit duplicate finalization coverage was added | Passed with one skip: collected 355 items; `354 passed, 1 skipped in 0.86s`. |

Acceptance criteria result mapping:

| AC | Result | Evidence |
|---|---|---|
| 1 | Passed | Static inspection of canonical filtering tests plus focused HITL suite: `86 passed`. |
| 2 | Passed | Static inspection of pagination test `test_audit_metadata_repository_filters_canonical_rows_across_query_pages` plus focused HITL suite: `86 passed`. |
| 3 | Passed | Static inspection of `FORCE_RECREATE_BLOCKED` renderer and assertions plus focused HITL suite: `86 passed`. |
| 4 | Passed | Static inspection of force recreate lifecycle tests plus focused HITL suite: `86 passed`. |
| 5 | Passed | Static inspection of nonzero finalization test plus scheduling/finalization suite: `30 passed`. |
| 6 | Passed | Static inspection of zero-execution finalization test plus scheduling/finalization suite: `30 passed`. |
| 7 | Passed | Corrected prior overclaim: previous report referenced duplicate delivery coverage too generally. Explicit finalization idempotency is now covered by `test_duplicate_finalization_delivery_skips_existing_finalizing_or_terminal_state`, parametrized for `FINALIZING`, `COMPLETED`, `FAILED`, and `CANCELLED`, and executed in the post-quality-review focused command: `16 passed`. |
| 8 | Passed | Scheduled execution, duplicate delivery, cancellation/finalization, scheduling lifecycle, schedule builder regressions passed in prior evidence; post-quality-review focused scheduled/finalization command passed (`16 passed`) and post-fix full suite passed (`354 passed, 1 skipped`). |

## 3. Failed Tests

No failed tests were reported in the orchestrator-provided execution evidence.

QA-local attempted commands and observed permission failures from the earlier QA pass:

```text
pytest tests/unit/test_operator_cli_discovery.py tests/api/test_operator_cli_discovery_contract.py tests/unit/test_operator_cli_result.py tests/unit/test_operator_cli_rcp.py -q
Observed: The user has specified a rule which prevents you from using this specific tool call.

pytest 
Observed: The user has specified a rule which prevents you from using this specific tool call.

pytest
Observed: The user has specified a rule which prevents you from using this specific tool call.
```

## 4. Failure Classification

| Issue | Classification | Root Cause Hypothesis | Reproduction Steps | Severity |
|---|---|---|---|---|
| QA-local pytest commands blocked | Environment Issue | Active QA tool permission policy denied `bash` invocations for pytest commands before execution. | From repo root, attempt the QA-local pytest commands listed above through the available bash tool. | Non-blocking after follow-up because orchestrator supplied successful execution evidence from the active workspace. |

## 5. Observations

- Static inspection indicates implementation and tests are aligned with the HITL acceptance criteria.
- No application defect was proven during this QA pass.
- Orchestrator-provided evidence shows focused HITL, scheduling/finalization regression, post-quality-review explicit duplicate finalization coverage, and full-suite commands all passed with no failures.
- Prior AC7 reporting overclaimed explicit duplicate finalization idempotency coverage. This report corrects that: AC7 approval is based on the newly inspected and executed `test_duplicate_finalization_delivery_skips_existing_finalizing_or_terminal_state` test.
- No flakiness was observed in the provided command results; however, QA did not perform repeated reruns due to local shell permission constraints.

## 6. Regression Check

Regression coverage was identified by static inspection and executed by the orchestrator:

- HITL-focused discovery/result/create coverage:
  - `tests/unit/test_operator_cli_discovery.py`
  - `tests/api/test_operator_cli_discovery_contract.py`
  - `tests/unit/test_operator_cli_result.py`
  - `tests/unit/test_operator_cli_rcp.py`
- Phase 3 scheduling/finalization coverage:
  - `tests/integration/test_phase3_scheduled_execution.py`
  - `tests/integration/test_phase3_duplicate_delivery.py`
  - `tests/integration/test_phase3_cancellation_finalization.py`
  - `tests/integration/test_phase3_scheduling_lifecycle.py`

Regression result: focused scheduling/finalization suite passed (`30 passed in 0.21s`) and full suite passed (`350 passed, 1 skipped in 0.86s`). The single skip was present in full-suite execution and did not affect the HITL blocker acceptance criteria based on the provided evidence.

Post-quality-review blocker-fix regression result: explicit duplicate finalization/scheduled execution focused command passed (`16 passed in 0.22s`) and post-fix full suite passed (`354 passed, 1 skipped in 0.86s`). The single skip remains outside the HITL acceptance criteria based on the provided evidence.

## 7. QA Decision

[QA SIGN-OFF APPROVED]

Reason: Static inspection confirms acceptance criteria are covered by targeted tests and implementation paths, including the newly added explicit duplicate finalization idempotency test. Orchestrator-provided execution evidence shows the focused HITL suite, scheduling/finalization regression suite, post-quality-review focused finalization/scheduled execution suite, and full regression suite passed with no failures.
