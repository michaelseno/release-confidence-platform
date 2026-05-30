# Test Plan

## 1. Feature Overview

Validate the HITL blocker fix for static no-body GET/HEAD endpoint execution in one orchestrator run. The fix must bypass payload duplicate reservation for static `payload=None` GET/HEAD requests only, while preserving Phase 2 generated/data-pool duplicate safeguards and prior HITL regression behavior.

## 2. Acceptance Criteria Mapping

| Acceptance criterion | Validation approach |
| --- | --- |
| Multiple static GET endpoints with `payload=None` are allowed in one run | Unit coverage in `test_static_get_no_body_bypasses_payload_duplicate_reservation`; orchestrator integration coverage in `test_orchestrator_executes_named_static_get_health_endpoints_without_duplicate_errors` |
| Multiple static HEAD endpoints with `payload=None` are allowed | Unit coverage in `test_static_head_no_body_bypasses_payload_duplicate_reservation` |
| Acceptance endpoints all execute in one orchestrator run | Integration test uses `health_fast`, `health_slow`, `health_flaky`, `health_inconsistent_variant_a`, `health_inconsistent_variant_b` and verifies five outbound requests |
| Bypass metadata is safe/expected | Tests assert `duplicate_detected=false` and `duplicate_check_scope="not_applicable"` |
| Static GET with explicit `{}` or `""` does not bypass | Parameterized unit coverage in `test_static_get_explicit_empty_body_does_not_bypass_duplicate_check` |
| Static POST/PUT/PATCH/DELETE no-body does not bypass by default | Parameterized unit coverage in `test_static_no_body_side_effect_methods_do_not_bypass_duplicate_check` |
| Generated duplicate behavior remains unchanged for `fail_fast`, `regenerate`, and `allow` | Existing and added Phase 2 tests cover `test_payload_preparation_fail_fast_duplicate_error_carries_safe_metadata`, `test_generated_regenerate_duplicate_behavior_unchanged`, `test_payload_preparation_duplicate_allow_metadata`, and API runner fail-fast regression |
| Data-pool duplicate prevention remains unchanged | `test_data_pool_duplicate_prevention_unchanged` |
| Mirrored runtime/source paths are consistent | Diff review of `packages/data_generation/generator.py` and `src/release_confidence_platform/data_generation/generator.py`; functional logic matches with import namespace differences only |
| Prior HITL fixes still pass | Full pytest suite, including config-init, audit-create/storage guidance, Lambda packaging, orchestrator observability, S3/DynamoDB diagnostics tests |
| Ruff/format gates and full pytest pass | Execute `ruff check`, `ruff format --check`, and full pytest |

## 3. Test Scenarios

1. Prepare two static GET endpoints with absent payload using one duplicate checker; expect both prepared successfully with identical `EMPTY_PAYLOAD` fingerprint and no duplicate detection.
2. Prepare two static HEAD endpoints with absent payload; expect both prepared successfully and duplicate scope marked not applicable.
3. Run orchestrator over the five named health endpoints; expect completed run, five outbound requests, all results `PASS`, and no `PAYLOAD_VALIDATION_ERROR`.
4. Repeat static GET with explicit empty object and empty string; expect second preparation to fail duplicate policy and retain `current_run` duplicate scope.
5. Repeat static no-body POST/PUT/PATCH/DELETE; expect second preparation to fail duplicate policy and retain `current_run` duplicate scope.
6. Repeat generated payloads under `allow`, `fail_fast`, and `regenerate`; expect historical duplicate behavior.
7. Repeat data-pool record/payload use without reuse allowance; expect duplicate prevention.
8. Execute repository regression suite and static quality gates.

## 4. Edge Cases

- No-body canonical fingerprint remains SHA-256 of `EMPTY_PAYLOAD`.
- Explicit empty object `{}` is treated as a body, not absent body.
- Explicit empty string `""` is treated as a body, not absent body.
- Side-effect-prone methods with no body are not granted the GET/HEAD bypass.
- Data-pool record duplicate protection remains independent of payload duplicate bypass.

## 5. Test Types Covered

- Unit tests
- Integration/orchestrator tests
- API runner regression tests
- Static analysis and formatting gates
- Full regression suite

## 6. Coverage Justification

Coverage directly exercises the reported blocker path, the five default-profile health endpoints, metadata expectations, explicit body edge cases, unsafe-method boundaries, generated duplicate policies, data-pool duplicate prevention, source/runtime mirror consistency, and prior HITL regression tests. Live AWS deployment was intentionally excluded per instruction.
