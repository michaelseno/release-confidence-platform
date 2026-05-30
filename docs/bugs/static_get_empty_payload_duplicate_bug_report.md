# Bug Report

## 1. Summary

During HITL validation of the Enhanced `rcp config init` Default Profile System, backend/orchestrator execution allows the first static no-body GET endpoint but marks later static no-body GET endpoints as duplicate payloads and returns `PAYLOAD_VALIDATION_ERROR` before execution.

## 2. Investigation Context

- Source of report: HITL validation.
- Related feature/workflow: Enhanced `rcp config init` default profile-generated endpoint configuration executed through the backend orchestrator.
- Branch context: `feature/profile_driven_config_init` remains the active HITL correction branch.
- Affected workflow: orchestrator run over multiple static GET health endpoints, including `health_fast`, `health_slow`, `health_flaky`, `health_inconsistent_variant_a`, and `health_inconsistent_variant_b`.
- Reported symptom: first endpoint executes; subsequent GET endpoints fail with `PAYLOAD_VALIDATION_ERROR`, `duplicate_detected=true`, and the same `payload_fingerprint` because all no-body requests hash `EMPTY_PAYLOAD`.

## 3. Observed Symptoms

- Failing workflow: backend/orchestrator endpoint execution for multiple static GET/HEAD-style endpoints without request bodies.
- Exact reported error/failure fields:
  - `failure_type` / `error_code`: `PAYLOAD_VALIDATION_ERROR`
  - `duplicate_detected = true`
  - identical `payload_fingerprint` for all static no-body GET endpoints.
- Observed behavior: the first no-body GET reserves the `EMPTY_PAYLOAD` fingerprint; later distinct no-body GET endpoints are treated as duplicates before outbound execution.
- Expected behavior: distinct GET/HEAD endpoints with no request body should all execute in the same run. Duplicate prevention should not block them solely because their absent bodies share the canonical `EMPTY_PAYLOAD` fingerprint.

## 4. Evidence Collected

Files inspected:

- `apps/backend/orchestrator/service.py`
  - Creates one run-scoped `DuplicateChecker` per orchestrator run at lines 94-96.
  - Executes each endpoint and iteration with the same checker at lines 117-134.
- `apps/backend/runner/api_runner.py`
  - Calls `PayloadPreparationService.prepare(...)` before sending the HTTP request at lines 64-72.
  - Converts `PayloadValidationError` to a `RunnerOutcome` with `failure_type=PAYLOAD_VALIDATION_ERROR`, `status_code=None`, and no outbound request at lines 73-87.
  - Sends requests with `json=endpoint.get("payload")` at lines 96-101.
- `packages/data_generation/generator.py`
  - Validates endpoint payload config at line 51.
  - Builds static payload from `endpoint.get("payload")`; absent/null payload returns `None` at lines 119-120.
  - Computes `fp = payload_fingerprint(payload)` at line 62.
  - Always runs payload duplicate reservation/checking for every strategy/method using only the payload fingerprint at lines 74-81.
  - Raises `PayloadValidationError` for duplicate `fail_fast` at lines 92-95 or regenerate exhaustion at lines 96-98.
- `packages/data_generation/fingerprints.py`
  - Defines `EMPTY_PAYLOAD_SENTINEL = "EMPTY_PAYLOAD"` at line 11.
  - `payload_fingerprint(payload)` hashes with `empty_payload=True` when `payload is None` at lines 29-30.
- `packages/data_generation/duplicate_checker.py`
  - Uses a reservation key of `(scope, run scope, duplicate_subject_type, fingerprint)` at line 42.
  - The key does not include `endpoint_id`, HTTP method, URL, or iteration, even though those values are stored as metadata at lines 47-52.
- `src/release_confidence_platform/data_generation/*`
  - Contains the same generator/duplicate checker implementation and should be kept in sync if this repo currently ships both package paths.
- `tests/unit/test_phase2_payload_generation.py`
  - Existing duplicate tests cover generated payload duplicates and expect `duplicate_detected=true` for repeated generated payloads at lines 144-189.
- `tests/api/test_phase2_payload_generation_qa.py`
  - Existing QA test confirms generated fail-fast duplicates become `PAYLOAD_VALIDATION_ERROR` and block the second request at lines 86-108.
- `docs/product/phase_2_payload_data_generation_product_spec.md`
  - Requires no-body payloads to fingerprint as SHA-256 of canonical `EMPTY_PAYLOAD`, but duplicate policy text focuses on generated/data-pool duplicate behavior and does not require no-body GET endpoints to be blocked solely by the sentinel fingerprint.

## 5. Execution Path / Failure Trace

1. `CoreEngineOrchestrator.run()` creates a single `DuplicateChecker` for the run.
2. The orchestrator loops through configured endpoints and calls `ApiRunner.execute()` with the same checker.
3. `ApiRunner.execute()` calls `PayloadPreparationService.prepare()` before outbound HTTP.
4. For a static GET endpoint with no payload, `_build_payload()` returns `None`.
5. `payload_fingerprint(None)` hashes canonical `EMPTY_PAYLOAD`.
6. `PayloadPreparationService.prepare()` calls `duplicate_checker.check_and_reserve()` for `duplicate_subject_type="payload"` regardless of HTTP method, payload strategy, or whether the request has a body.
7. `DuplicateChecker.check_and_reserve()` keys reservations only by scope, run identity, subject type, and fingerprint. Distinct endpoints sharing the `EMPTY_PAYLOAD` fingerprint collide.
8. For default `duplicate_policy="regenerate"`, the static no-body payload is deterministic and remains `None` across all attempts, so regeneration cannot produce a new fingerprint and eventually raises `PayloadValidationError("Duplicate payload regeneration exhausted")`. For `fail_fast`, it raises `PayloadValidationError("Duplicate payload detected")` immediately.
9. `ApiRunner.execute()` catches the validation error and returns a `PAYLOAD_VALIDATION_ERROR` outcome without executing the endpoint.

## 6. Failure Classification

- Primary classification: Application Bug.
- Severity: Blocker.

Justification: HITL validation cannot complete the configured default-profile health workflow because only the first static no-body GET executes; subsequent distinct endpoints are blocked before outbound execution.

## 7. Root Cause Analysis

Confidence label: Confirmed Root Cause.

- Immediate failure point: `PayloadPreparationService.prepare()` raises `PayloadValidationError` after duplicate detection for a static no-body GET/HEAD payload.
- Underlying root cause: payload duplicate reservation is applied unconditionally to static no-body requests, and `DuplicateChecker` uses a payload-only reservation key. Since all absent bodies intentionally fingerprint to `EMPTY_PAYLOAD`, distinct no-body GET endpoints collide in the run-scoped duplicate map.
- Supporting evidence:
  - `payload_fingerprint(None)` uses the `EMPTY_PAYLOAD` sentinel (`packages/data_generation/fingerprints.py:11,29-30`).
  - Static payload generation returns `endpoint.get("payload")`, producing `None` for no-body endpoints (`packages/data_generation/generator.py:119-120`).
  - Duplicate checking is unconditional for payload fingerprints (`packages/data_generation/generator.py:74-81`).
  - Duplicate checker key excludes endpoint identity (`packages/data_generation/duplicate_checker.py:42`).
  - Runner maps preparation errors to `PAYLOAD_VALIDATION_ERROR` without sending the request (`apps/backend/runner/api_runner.py:73-87`).

Contributing factor: `duplicate_check_scope` currently only supports `current_run`; there is no `not_applicable` normalized scope for metadata-only bypass semantics.

## 8. Confidence Level

High. The reported runtime fields match the inspected code path exactly: no-body static endpoints produce the same sentinel fingerprint, the run-scoped checker reserves by fingerprint only, and runner preparation errors are converted to `PAYLOAD_VALIDATION_ERROR` outcomes.

## 9. Recommended Fix

Likely owner: backend/full-stack engineer working on orchestrator payload preparation.

Recommended implementation:

1. In `packages/data_generation/generator.py` and the mirrored `src/release_confidence_platform/data_generation/generator.py`, bypass payload duplicate checking/reservation for static no-body safe methods:
   - condition: `endpoint["payload_strategy"] == "static"`, `endpoint.get("payload") is None` after build, and `endpoint.get("method", "").upper() in {"GET", "HEAD"}`.
   - for this case, do not call `duplicate_checker.check_and_reserve()` for `duplicate_subject_type="payload"`.
   - return metadata with `duplicate_detected=false`, `duplicate_allowed=false`, and either `duplicate_check_scope="not_applicable"` or the existing configured scope plus an additional marker if schema compatibility requires keeping `current_run`.
2. Preserve existing duplicate behavior for:
   - `payload_strategy="generated"`;
   - `payload_strategy="data_pool"` payload fingerprints and data-pool record fingerprints;
   - static requests with actual payload bodies;
   - non-GET/HEAD methods even when payload is `None`, because side-effect-prone methods may still need duplicate safeguards depending on policy.
3. If choosing the alternative endpoint-aware key approach, update `DuplicateChecker.check_and_reserve()` to optionally include `endpoint_id` in the reservation key for static no-body GET/HEAD payload reservations only. Do not globally include `endpoint_id` for generated/data_pool payloads, or cross-endpoint duplicate prevention for side-effect-prone generated/data_pool payloads will be weakened.

Caution: Do not change `payload_fingerprint(None)` or the `EMPTY_PAYLOAD` canonicalization. The Phase 2 spec and tests require this fingerprint behavior.

## 10. Suggested Validation Steps

Targeted tests to add/run after the fix:

- Unit: `PayloadPreparationService.prepare()` with two distinct static GET endpoints, both `payload=None`, same run checker. Assert both return without `PayloadValidationError`, both metadata have `duplicate_detected=false`, and both keep the `EMPTY_PAYLOAD` fingerprint.
- Unit: same as above for static HEAD.
- Integration/API: orchestrator run containing `health_fast`, `health_slow`, `health_flaky`, `health_inconsistent_variant_a`, and `health_inconsistent_variant_b` static no-body GET endpoints. Assert all five outbound requests are sent and none fail with `PAYLOAD_VALIDATION_ERROR` solely due to `EMPTY_PAYLOAD` reuse.
- Regression: existing generated duplicate fail-fast test must still pass (`tests/api/test_phase2_payload_generation_qa.py::test_fail_fast_duplicate_failure_preserves_safe_duplicate_metadata`).
- Regression: generated/data_pool duplicate `regenerate`, `fail_fast`, and `allow` policies should retain current behavior.
- Edge: static POST/PUT/PATCH/DELETE with `payload=None` should not automatically receive the GET/HEAD bypass unless product explicitly approves that behavior.
- Edge: static GET with explicit empty object `{}`, empty string `""`, or other body-like payload should not be treated as no-body unless the product defines those as no body.

## 11. Open Questions / Missing Evidence

- The exact live raw result/log excerpt was not provided, but the reported fields are sufficient to trace the code path.
- Product should confirm whether metadata must literally set `duplicate_check_scope="not_applicable"` for bypassed GET/HEAD no-body requests, or whether keeping `current_run` with `duplicate_detected=false` is acceptable for backward compatibility.

## 12. Final Investigator Decision

Ready for developer fix.
