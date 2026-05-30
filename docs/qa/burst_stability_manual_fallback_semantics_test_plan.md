# Test Plan

## 1. Feature Overview

Validate the HITL refinement for `burst_stability` so manual runs use true burst fallback semantics, scheduled burst runs remain strict, raw results contain per-request burst evidence, generated configs contain manual defaults, cap precedence is enforced, and previously approved HITL fixes remain protected.

## 2. Acceptance Criteria Mapping

| Requirement | Validation |
| --- | --- |
| Total `request_count` across burst run | `tests/unit/test_phase1_core_engine.py::test_burst_request_count_is_total_and_endpoints_are_round_robin` |
| Global `concurrency` across burst run | `tests/unit/test_phase1_core_engine.py::test_burst_concurrency_is_global_cap` |
| Per-request raw burst metadata | `tests/unit/test_phase1_core_engine.py::test_manual_burst_without_windows_uses_fallback_defaults_and_raw_evidence` and scheduled burst raw-result tests |
| Manual fallback metadata semantics | Manual burst raw evidence test |
| Config init manual defaults | `tests/unit/test_config_init_generation.py`, `tests/api/test_config_init_profiles.py` |
| Orchestrator audit_config preferred source with safe fallback | Burst default and caps precedence tests in core engine and safeguards suites |
| Caps resolution order and enforcement | `tests/unit/test_phase3_safeguards.py`, manual clamp and scheduled cap tests |
| Scheduled burst strictness | `tests/unit/test_phase1_core_engine.py::test_scheduled_burst_without_enabled_window_fails_before_outbound_requests`, scheduled integration tests |
| Round-robin endpoint distribution | `test_burst_request_count_is_total_and_endpoints_are_round_robin` |
| Prior HITL regressions | Full pytest suite across config-init, audit-create adjacent behavior, packaging/config, observability, diagnostics, duplicate bypass, repeated metadata, and expected status precedence |
| Ruff/format gates and full pytest | `python3.11 -m ruff check .`, `python3.11 -m ruff format --check .`, `python3.11 -m pytest` |

## 3. Test Scenarios

1. Manual `burst_stability` without burst windows produces exactly 10 raw result records using `manual_fallback` and nullable window metadata.
2. Manual fallback defaults are resolved from audit config and clamped to effective caps.
3. Scheduled burst uses supplied configured window metadata and ignores manual defaults.
4. Scheduled burst missing enabled window metadata fails before runner execution.
5. Multi-endpoint burst distributes total requests round-robin rather than per endpoint.
6. Concurrent burst execution never exceeds global configured concurrency.
7. Config init/profile generation includes `burst_schedule.manual_burst_defaults` with enabled true, request_count 10, concurrency 2.
8. Regression suite confirms prior HITL fixes remain passing.
9. Static quality gates confirm lint and formatting compliance.

## 4. Edge Cases

- Request count not evenly divisible by endpoint count.
- Effective caps lower than configured manual defaults.
- Scheduled burst path with missing/disabled configured window.
- Raw result nullable window fields for manual fallback.
- Repeated iteration metadata remains unaffected for non-burst scenarios.

## 5. Test Types Covered

- Functional: burst execution semantics and raw evidence.
- Negative: scheduled missing enabled window, invalid cap cases.
- Edge: uneven endpoint distribution and cap clamping.
- Integration/regression: full pytest suite.
- Static quality: Ruff lint and Ruff format gate.

## 6. Coverage Justification

The selected suites directly exercise the backend orchestrator, config generation, scheduling safeguards, scheduled execution integration, and prior QA regression areas. Full pytest provides broad regression protection. Ruff gates cover required static quality checks.
