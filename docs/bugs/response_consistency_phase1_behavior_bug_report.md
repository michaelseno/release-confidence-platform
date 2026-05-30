# Bug Report

## 1. Summary

Investigation confirms that `response_consistency` is currently a supported scenario taxonomy value only. Runtime execution collects per-response sanitized `response_fingerprint` values in raw results, but no inspected code computes cross-response consistency verdicts or analytics for this scenario.

## 2. Investigation Context

- Source of report: user-requested repository investigation.
- Related feature/workflow: `response_consistency`, response fingerprints, raw result generation, assertions, finalization/reporting boundaries.
- Branch context: `feature/profile_driven_config_init` must remain active; no branch/commit/PR actions were performed.
- Relevant command/test/screen/endpoint: static inspection only; no test commands were run.

## 3. Observed Symptoms

- No failing command or runtime error was reported.
- Question under investigation: whether current behavior is fingerprint collection only, without consistency verdict computation.
- Expected behavior for Phase 1/Phase 3 scope, if confirmed: raw results collect fingerprints and defer fingerprint comparison analytics/verdicts to later reporting/aggregation phases.
- Observed behavior: code paths emit `response_fingerprint` per response and preserve `response_consistency` as taxonomy metadata, but do not compare fingerprints across iterations/runs/endpoints or produce a consistency verdict/status.

## 4. Evidence Collected

Files/functions inspected:

- `apps/backend/runner/api_runner.py`
  - `RunnerOutcome` includes `response_fingerprint: str | None = None`.
  - `ApiRunner.execute()` computes `response_body = _response_body_for_fingerprint(response)` and stores `response_fingerprint=response_fingerprint(response_body)` on successful HTTP responses.
  - `evaluate_response()` returns only assertion/failure outcomes based on status code and optional JSON/required-field assertions; it does not inspect scenario type, compare fingerprints, or emit consistency verdicts.
  - `_response_body_for_fingerprint()` extracts JSON or text evidence for fingerprinting only.
- `packages/data_generation/fingerprints.py`
  - `response_fingerprint(value)` is a SHA-256 wrapper over sanitized canonicalized content; there is no comparison or verdict logic.
- `apps/backend/orchestrator/service.py`
  - `_raw_result()` serializes `**asdict(outcome)` into raw result records, so the runner's `response_fingerprint` is persisted as evidence.
  - `run()` writes a raw-result envelope and terminal metadata status `COMPLETED`/`FAILED`; no aggregation/reporting/verdict stage is invoked.
  - Repeated execution loops append independent raw result records with iteration metadata; no cross-iteration comparison is performed.
- `packages/audit_scheduling/constants.py`
  - `SCENARIO_RESPONSE_CONSISTENCY = "response_consistency"` is listed in `SCENARIO_TYPES` and mapped to category `Stability`.
- `src/release_confidence_platform/operator_cli/main.py`
  - `rcp audit run --scenario-type` accepts `response_consistency` as a choice.
- `apps/backend/handlers/audit_finalization_handler.py`
  - Finalization transitions audits with executions to `FINALIZING` and records metadata; it does not run analytics, reporting, or response consistency comparison.
- `docs/product/phase_3_audit_scheduling_lifecycle_product_spec.md`
  - Existing Phase 3 scope says scenario taxonomy is preserved for downstream analysis/reporting without executing analytics/reporting workflows.
  - Existing out-of-scope list excludes analytics/report generation and reliability scoring.
- `tests/integration/test_phase2_orchestrator_payloads.py`
  - Existing integration coverage asserts identical `response_fingerprint` values can be persisted in raw results, but does not assert a consistency verdict.

## 5. Execution Path / Failure Trace

For any scenario, including `response_consistency`:

1. CLI/scheduling/event validation permits `scenario_type = "response_consistency"` as taxonomy metadata.
2. `CoreEngineOrchestrator.run()` loads execution config and calls `ApiRunner.execute()` for each endpoint/schedule/payload iteration.
3. `ApiRunner.execute()` evaluates only configured endpoint assertions via `evaluate_response()`.
4. On a successful HTTP response, the runner computes a sanitized `response_fingerprint` from the response body.
5. `_raw_result()` persists the outcome via `asdict(outcome)`, including the fingerprint and ordinary assertion fields.
6. No inspected code groups records by endpoint/scenario/iteration, compares fingerprints, or emits a response-consistency verdict.

## 6. Failure Classification

- Primary classification: Requirements Ambiguity / documentation gap.
- Severity: Low.

Severity justification: no application failure was reported and current code behavior aligns with the staged architecture, but documentation should explicitly state the Phase 1/Phase 3 boundary to prevent QA/product misunderstanding.

## 7. Root Cause Analysis

- Immediate failure point: none; this is a behavior verification request, not a runtime failure.
- Underlying root cause: current implementation only has raw evidence collection and taxonomy support for `response_consistency`; analytics/reporting verdict generation has not been implemented in this phase.
- Supporting evidence:
  - `response_fingerprint()` only hashes canonical sanitized response content.
  - `evaluate_response()` only evaluates status/JSON/field assertions.
  - `_raw_result()` only persists raw runner outcome data.
  - Phase 3 docs explicitly defer analytics/reporting/scoring.

Confidence label: Confirmed Root Cause.

## 8. Confidence Level

High. Static inspection covered the runner, raw result persistence, scenario taxonomy, CLI entrypoint, finalization handler, documentation, and relevant tests. Searches found no `response_consistency`-specific analytics module and no aggregation/reporting implementation that computes consistency verdicts.

## 9. Recommended Fix

No application code change is needed if fingerprint-only collection is expected Phase 1/Phase 3 behavior.

Likely owner: product/docs with backend reviewer.

Recommended documentation updates:

1. `docs/product/phase_2_payload_data_generation_product_spec.md`, FR-011 Response Fingerprint:
   - Add: "Phase 1/Phase 2 response fingerprinting is evidence collection only. The runner must not compare fingerprints or emit response-consistency verdicts; comparison analytics are deferred to a later analysis/reporting phase."
2. `docs/architecture/phase_2_payload_data_generation_technical_design.md`, Raw Result Schema v1 Extension:
   - Add: "`response_fingerprint` is a raw evidence field. Raw result schema v1 does not include `response_consistency_status`, `consistency_verdict`, or cross-iteration comparison output."
3. `docs/product/phase_3_audit_scheduling_lifecycle_product_spec.md`, FR-010 Scenario Taxonomy and/or Out of Scope:
   - Add: "`response_consistency` is an operational scenario taxonomy value in Phase 3. It schedules/labels evidence collection only; consistency analytics and verdict calculation are deferred to downstream reporting/aggregation after finalization."
4. `docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md`, Scenario Taxonomy Constants:
   - Add: "The taxonomy mapping does not imply built-in scenario-specific verdict computation in Phase 3. `response_consistency` uses ordinary runner execution and raw fingerprint persistence."

## 10. Suggested Validation Steps

- Static QA check: confirm no raw result record includes `consistency_verdict`, `response_consistency_status`, or equivalent verdict field.
- Unit/integration regression, if docs-only change is paired with tests later:
  - Run existing response fingerprint persistence coverage in `tests/integration/test_phase2_orchestrator_payloads.py`.
  - Add future test coverage only when analytics/reporting phase introduces fingerprint comparison verdicts.
- Manual validation: run or inspect a `response_consistency` scenario and verify raw results include `scenario_type: "response_consistency"` and per-record `response_fingerprint`, with no aggregate verdict.

## 11. Open Questions / Missing Evidence

- No live raw result sample was provided; the conclusion is based on repository source/docs/tests.
- Product should confirm whether the docs should call this "Phase 1", "Phase 2 fingerprint evidence", or "Phase 3 taxonomy-only" behavior for consistency across project terminology.

## 12. Final Investigator Decision

Resolved as documentation clarification.

Product and architecture documentation now explicitly state that current `response_consistency` behavior is fingerprint evidence collection only and that consistency analytics/verdicts are deferred to later reporting/aggregation.
