# Test Report

## 1. Execution Summary

- Total tests executed with evidence: 437 across two orchestrator-run commands
  - Focused scheduling/CLI regression suite: 94 passed, 0 failed
  - Full test suite: 342 passed, 1 skipped, 0 failed
- Passed: 436
- Failed: 0
- Skipped: 1

QA's own shell execution remained permission-blocked by the local tool policy. The orchestrator executed the same validation commands in the active workspace and provided command output evidence. QA re-evaluated the acceptance criteria using that execution evidence plus prior static implementation/test inspection.

## 2. Detailed Results

| Validation area | Evidence inspected | Outcome |
| --- | --- | --- |
| Distinct baseline occurrence IDs | `packages/audit_scheduling/builders.py:112-169`, `:301-348`; `tests/unit/test_phase3_schedule_builders.py:45-73` | Passed by orchestrator-run focused suite. Builder enumerates baseline occurrence times, emits `at(...)`, and derives canonical occurrence IDs from `client_id:audit_id:schedule_type:scenario_type:scheduled_at`. Tests assert two distinct IDs. |
| Duplicate delivery skip | `apps/backend/handlers/scheduled_execution_handler.py:83-116`; `tests/integration/test_phase3_duplicate_delivery.py:19-28` | Passed by orchestrator-run focused suite. Duplicate claim returns `duplicate_skipped` and does not call orchestrator. |
| Scheduled handler calls orchestrator | `apps/backend/handlers/scheduled_execution_handler.py:138-150`; Lambda entrypoint constructs `CoreEngineOrchestrator` at `:230-234`; `tests/integration/test_phase3_scheduled_execution.py:80-90` | Passed by orchestrator-run focused suite. Non-repeated scheduled events call `self.orchestrator.run(...)`; entrypoint injects `CoreEngineOrchestrator`. |
| Raw result and run metadata coverage | `apps/backend/handlers/scheduled_execution_handler.py:153-156`; `tests/integration/test_phase3_scheduled_execution.py:47-51`, `:100-108` | Passed by orchestrator-run focused suite. Mocked orchestrator result covers raw result key and run metadata logging behavior. |
| Required handler logs | `apps/backend/handlers/scheduled_execution_handler.py:33-64`, `:76-84`, `:102-113`, `:132-156`, `:171-197`; `tests/integration/test_phase3_scheduled_execution.py:92-118` | Passed by orchestrator-run focused suite. Coverage includes Lambda-visible startup, contract validation, claim, orchestration, raw result, and run metadata logs. |
| EventBridge target input shape | `packages/audit_scheduling/builders.py:319-332`; scheduled event validator referenced by handler at `apps/backend/handlers/scheduled_execution_handler.py:77`; tests reject `run_id` at `tests/integration/test_phase3_duplicate_delivery.py:31-37` | Passed by orchestrator-run focused suite. Payload includes required fields and omits `run_id`. |
| Schedule cleanup/cancel for multiple discrete schedules | `packages/audit_lifecycle/cancellation.py:28-34`, `:88-96`, `:108-129`; `tests/integration/test_phase3_cancellation_finalization.py:90-104` | Passed by orchestrator-run focused suite. Cancellation iterates all schedules and test expects deletion of two baselines plus finalization. |
| Manual `rcp audit run` unchanged | `tests/unit/test_operator_cli_rcp.py`, `tests/api/test_operator_cli_rcp_contract.py` | Passed by orchestrator-run focused suite. Static inspection of scheduling handler did not show direct manual CLI path changes. |

## 3. Failed Tests

No failed tests were reported in the orchestrator-provided execution evidence.

Commands and results:

1. `python -m pytest tests/unit/test_phase3_schedule_builders.py tests/integration/test_phase3_scheduled_execution.py tests/integration/test_phase3_duplicate_delivery.py tests/integration/test_phase3_scheduling_lifecycle.py tests/integration/test_phase3_cancellation_finalization.py tests/unit/test_operator_cli_rcp.py tests/api/test_operator_cli_rcp_contract.py`
   - Collected: 94 items
   - Result: `94 passed in 0.38s`
2. `python -m pytest`
   - Collected: 343 items
   - Result: `342 passed, 1 skipped in 0.85s`

QA-local execution note: this QA agent previously attempted equivalent pytest execution, but shell use was denied by local tool permission policy before command execution. The above execution evidence was provided by the orchestrator from the active workspace.

## 4. Failure Classification

| Issue | Classification | Root cause hypothesis | Reproduction steps | Severity |
| --- | --- | --- | --- | --- |
| QA-local shell execution blocked | Environment Issue | Current QA tool permission rules deny shell execution in this session. The orchestrator mitigated this by executing the same validation commands in the active workspace and providing results. | Attempt pytest execution from this QA shell tool context. | Non-blocking after orchestrator execution evidence was provided. |

No application defect was proven by this QA pass. No unresolved test failures remain.

## 5. Observations

- Static inspection aligns with the reported implementation summary.
- Existing tests cover the required acceptance criteria at the unit/integration/mock level and passed in orchestrator execution.
- The scheduled handler now logs Lambda-visible startup via `print(...)` and structured handler milestones through `StructuredLogger`.
- The orchestrator-provided full suite result matches the implementation report: `342 passed, 1 skipped`.

## 6. Regression Check

- Manual CLI regression tests were included in the orchestrator-run focused command and passed.
- Static inspection of the scheduled execution changes did not identify a direct manual CLI path modification.
- Cancellation behavior for multiple discrete schedules has passing integration coverage.

## 7. QA Decision

[QA SIGN-OFF APPROVED]

Reason: Static inspection plus orchestrator-provided execution evidence satisfy all confirmed acceptance criteria. Focused scheduling/CLI regression coverage passed with `94 passed`, and the full suite passed with `342 passed, 1 skipped`. No blocking defects, unresolved failures, or major regressions were identified.
