# Bug Report

## 1. Summary

During HITL validation of the Enhanced `rcp config init` Default Profile System, endpoint-specific expected status code configuration is not honored when the status code list is supplied at endpoint top level as `expected_status_codes: [200]`. The backend runner receives no configured status assertion and falls back to its broad default `200..399`, which is then persisted in raw results under `assertion_results.expected_status_codes`.

## 2. Investigation Context

- Source of report: HITL validation.
- Related feature/workflow: Enhanced `rcp config init` default-profile Layer 1 validation health endpoints executed through `rcp audit run` / backend orchestrator.
- Branch context: `feature/profile_driven_config_init` remains the active HITL correction branch.
- Relevant workflow: endpoint config load/validation -> orchestrator endpoint execution -> runner assertion evaluation -> raw result serialization.
- Reported live/raw behavior: endpoint config defines `expected_status_codes: [200]`, but raw results show `assertion_results.expected_status_codes` as `[200..399]`.

## 3. Observed Symptoms

- Failing workflow: Layer 1 health endpoint status assertion validation.
- Reported observed behavior:
  - Endpoint config has `expected_status_codes: [200]`.
  - Raw result has `assertion_results.expected_status_codes` expanded to the runner default `[200, 201, ..., 399]`.
- Expected behavior:
  - Endpoint-level expected status codes override default expected status codes.
  - Raw result `assertion_results.expected_status_codes` reflects the actual assertion set used by the runner.
  - Layer 1 health endpoints should assert only `[200]`, not every 2xx/3xx status.
- Immediate consequence: 3xx responses are treated as acceptable for health endpoints if the endpoint-level `[200]` assertion is dropped before runner execution.

## 4. Evidence Collected

Files inspected:

- `apps/backend/orchestrator/service.py`
  - Loads endpoint config via `EndpointConfigLoader(...).load(...)` and normalizes it with `validate_endpoint_config(endpoint_config)` at lines 284-291.
  - Passes the normalized endpoint to the runner after secret resolution at lines 149-155.
  - Serializes raw results by spreading `asdict(outcome)` into the raw record at lines 401-425. There is no separate assertion metadata transform in raw serialization.
- `packages/config/validators.py`
  - Reads assertions only from nested `endpoint.get("assertions", {})` at line 99.
  - Allows only nested assertion keys `expected_status_codes`, `expect_json`, and `required_response_fields` at lines 99-104.
  - Returns normalized endpoint with `"assertions": assertions` at lines 105-114.
  - Does not read, migrate, or reject top-level `endpoint["expected_status_codes"]`.
- `src/release_confidence_platform/config/validators.py`
  - Mirrors the same nested-only assertion behavior at lines 99-114.
- `apps/backend/runner/api_runner.py`
  - Calls `evaluate_response(response, endpoint.get("assertions") or {})` at lines 104-106.
  - `evaluate_response()` uses configured `assertions["expected_status_codes"]` / `assertions["expected_status_code"]` if present; otherwise it defaults to `list(range(200, 400))` at lines 155-163.
  - The `assertion_results` dict is initialized with the `expected_codes` actually used by the evaluator at line 163 and returned on every response classification path at lines 166-180.
- `src/release_confidence_platform/config/generators/endpoints_generator.py`
  - Safe sample generation emits the expected nested shape: `"assertions": {"expected_status_codes": [200]}` at line 41.
- `docs/architecture/enhanced_config_init_default_profile_system_technical_design.md`
  - Sample endpoint contract also shows the nested assertion shape at lines 486-509.
- `docs/architecture/phase_1_core_engine_foundation_technical_design.md`
  - Endpoint schema defines `assertions` as the endpoint field for foundational assertions at lines 363-385.
  - Assertion behavior says expected status code assertions are configured assertions at lines 718-723.

Test coverage observations:

- Existing tests use the nested shape (`"assertions": {"expected_status_codes": [200]}`), for example `tests/unit/test_phase1_core_engine.py:283-296` and `tests/integration/test_phase1_orchestrator_integration.py:65-78`.
- No inspected test covers top-level `expected_status_codes` being rejected, migrated, or honored.

## 5. Execution Path / Failure Trace

1. Runtime endpoint config is loaded from `configs/{client_id}/audits/{audit_id}/endpoints.json` by `EndpointConfigLoader`.
2. `CoreEngineOrchestrator._load_and_validate_configs()` calls `validate_endpoint_config(endpoint_config)`.
3. `validate_endpoint()` only extracts assertion config from the nested `assertions` object. A top-level `expected_status_codes` key is neither copied into `assertions` nor rejected as unsupported.
4. The normalized endpoint returned to the orchestrator contains `assertions: {}` when the original config used only top-level `expected_status_codes`.
5. `ApiRunner.execute()` calls `evaluate_response(response, endpoint.get("assertions") or {})`, so the evaluator receives `{}`.
6. `evaluate_response()` sees no configured expected status codes and sets `expected_codes = list(range(200, 400))`.
7. The evaluator persists those actual expected codes into `RunnerOutcome.assertion_results`.
8. `CoreEngineOrchestrator._raw_result()` serializes `RunnerOutcome.assertion_results` directly into the raw result. Therefore the raw result is not merely stale metadata; it reflects the broad default assertion set that was actually used by the runner.

## 6. Failure Classification

- Primary classification: Contract Mismatch.
- Severity: High.

Severity justification: Layer 1 validation can produce false PASS results for health endpoints by accepting 3xx statuses even though the reported endpoint intent is `[200]`. This is a HITL validation blocker for asserting the health endpoint contract, but it does not appear to crash the run or cause data loss.

## 7. Root Cause Analysis

Confidence label: Most Likely Root Cause.

- Immediate failure point: `apps/backend/runner/api_runner.py::evaluate_response()` defaults to `[200..399]` because it receives an empty assertion dict.
- Underlying root cause: endpoint status assertion placement is inconsistent with the runtime validator contract. Runtime validation/normalization recognizes only nested `endpoint["assertions"]["expected_status_codes"]`; HITL/live config appears to define `endpoint["expected_status_codes"]` at top level. The validator silently drops the top-level key instead of rejecting it or translating it into the nested assertion object.
- Supporting evidence:
  - Nested-only extraction in `packages/config/validators.py:99` and `src/release_confidence_platform/config/validators.py:99`.
  - Runner receives only `endpoint.get("assertions") or {}` (`apps/backend/runner/api_runner.py:104-106`).
  - Default fallback to `list(range(200, 400))` occurs only when no expected status assertion is present (`apps/backend/runner/api_runner.py:156-163`).
  - Raw serialization uses `asdict(outcome)` directly (`apps/backend/orchestrator/service.py:401-425`), so `assertion_results.expected_status_codes` reflects evaluator output.

Plausible contributing factors:

- The endpoint config validator permits unknown top-level endpoint keys by passing through `phase2_endpoint = validate_endpoint_payload_config({**endpoint, "payload": payload})`, then overwriting known normalized fields. This allows a misshaped top-level assertion key to survive validation without affecting runner behavior.
- Existing tests cover the nested assertion shape but not malformed/top-level status assertions.

## 8. Confidence Level

High. The reported raw result `[200..399]` exactly matches the only fallback path in `evaluate_response()`. Raw result serialization has no independent defaulting layer, which means the runner actually evaluated with the default list. Full confirmation would require the exact live `endpoints.json` excerpt to verify whether `expected_status_codes` is top-level versus nested.

## 9. Recommended Fix

Likely owner: backend/full-stack engineer responsible for config validation and runner contracts.

Recommended implementation:

1. In both validator mirrors, `packages/config/validators.py` and `src/release_confidence_platform/config/validators.py`, make endpoint expected-status configuration unambiguous:
   - Preferred strict contract fix: reject top-level `expected_status_codes` and `expected_status_code` with `ConfigError("Unsupported assertion placement" or equivalent, "CONFIG_VALIDATION_ERROR")`, instructing users/tests to use `assertions.expected_status_codes`.
   - If backward compatibility with HITL/live configs is required, normalize top-level `expected_status_codes` / `expected_status_code` into `assertions["expected_status_codes"]` before returning the endpoint, but fail if both top-level and nested values are present and disagree.
2. If normalizing, validate the normalized value type before runner execution:
   - integer -> single-item list;
   - list/range representation -> list of integers;
   - reject empty lists, booleans, non-integers, invalid HTTP status ranges, and mixed invalid values.
3. Keep `apps/backend/runner/api_runner.py::evaluate_response()` as the runtime source of raw assertion metadata. Do not add a separate raw-result serialization default because current raw results correctly reveal which assertion set was used.
4. Add targeted tests:
   - validator rejects or normalizes top-level `expected_status_codes` according to the chosen contract;
   - orchestrator raw result for a `[200]` health endpoint has `assertion_results.expected_status_codes == [200]`;
   - a `302` response fails when `[200]` is configured;
   - missing assertions still use the intentional default `[200..399]` if that default remains desired.

Caution: The generated sample endpoint and architecture docs already use nested `assertions.expected_status_codes`; avoid changing the documented shape unless product intentionally expands the contract.

## 10. Suggested Validation Steps

After the fix, validate these cases:

- Unit: `validate_endpoint_config()` with nested `assertions.expected_status_codes: [200]` returns normalized assertions unchanged.
- Unit: top-level `expected_status_codes: [200]` is either rejected with `CONFIG_VALIDATION_ERROR` or normalized into `assertions`, matching the selected fix strategy.
- Unit: both top-level and nested status assertions with conflicting values fail validation.
- Unit/API runner: response `302` with configured `[200]` returns `ASSERTION_FAILURE` or configured status mismatch, not `PASS`.
- Integration/orchestrator: raw result for Layer 1 health endpoint contains `assertion_results.expected_status_codes: [200]`.
- Regression: endpoint with no status assertion still uses the existing default `[200..399]`, if product keeps that fallback.
- Regression: generated `rcp config init --include-sample-endpoints` output still contains nested `assertions.expected_status_codes: [200]`.
- Edge cases: single integer, list of multiple codes, empty list, non-integer values, boolean values, and unknown assertion keys.

## 11. Open Questions / Missing Evidence

- The exact live `endpoints.json` excerpt was not provided. Confirmation needs to verify whether the reported `expected_status_codes: [200]` is top-level or nested under `assertions`.
- Product/engineering should choose whether top-level `expected_status_codes` is an accepted backward-compatible alias or should be rejected as invalid config.
- If audit-level assertion defaults exist in a future contract, there is no current implementation evidence that they are merged into endpoint assertions.

## 12. Final Investigator Decision

Ready for developer fix.
