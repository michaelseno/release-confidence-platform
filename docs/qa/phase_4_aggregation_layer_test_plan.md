# Test Plan

## 1. Feature Overview

Feature under test: Phase 4 Aggregation Layer on branch `feature/phase_4_aggregation_layer`.

QA planning status: **updated only**. Automated source tests are intentionally not implemented in this QA task.

Upstream artifacts reviewed:
- Product specification: `docs/product/phase_4_aggregation_layer_product_spec.md`
- Technical design: `docs/architecture/phase_4_aggregation_layer_technical_design.md`
- ADR: `docs/architecture/adr_phase_4_evidence_lineage_aggregation.md`
- Architecture review: `docs/architecture/phase_4_aggregation_layer_architecture_review.md` was requested but is not present in the repository at review time.
- Security review input from orchestrator: blocked on sensitive raw content allowlist, endpoint identifier safety, IAM specificity, internal trigger controls, lineage size/data exposure, logs/errors.

Phase 4 introduces a backend-only, system-managed aggregation lifecycle stage that reads immutable finalized audit execution evidence and writes deterministic, immutable, versioned aggregate datasets for later internal analytical phases. Aggregation is not a reporting, scoring, dashboard, recommendation, release-gating, AI insight, public API, or operator/customer workflow feature.

Human-approved decisions incorporated into this plan:
1. Phase 4 introduces a dedicated first-class `audit_execution_id`. `run_id` is not the long-term canonical lineage key and must not be substituted as the aggregate set identity.
2. `config_version` is mandatory. Missing `config_version` causes deterministic fail-closed validation/ineligible outcome and no aggregate creation.
3. `skipped_requests = 0` in `agg_v1` because Raw Result Schema v1 has no explicit skipped indicator. `PAYLOAD_VALIDATION_ERROR` is counted as failure, not skipped.
4. Zero-execution audits are not eligible. No aggregate is created for zero-execution or execution-failed audits.
5. Aggregates must use a bounded lineage manifest/reference rather than unbounded inline raw references. The manifest must be immutable, sanitized, versioned, access-controlled, complete, and able to deterministically reconstruct the exact source raw result references.
6. Aggregation is an automatic system-managed lifecycle stage. Manual aggregation/reaggregation is allowed only as privileged administrative disaster recovery (DR), must be idempotent, and must be auditable.

QA validation gate outcome: acceptance criteria are testable for planning, with blockers/open questions listed below. Test design follows `e2e-testing-patterns` by using deterministic fixtures, explicit setup, stable system-visible outcomes, and regression-focused journey coverage. Failure analysis follows `systematic-debugging` principles: exact symptom, expected/observed behavior, logs/records, reproducibility, failure classification, and evidence-backed owner handoff.

System boundaries in scope:
- Internal aggregation event/handler contract: `aggregate_audit`.
- Automatic lifecycle trigger after successful Phase 3 finalization only.
- Privileged administrative DR trigger path, if implemented.
- Eligibility boundary: canonical audit metadata with `lifecycle_state = COMPLETED`, successful Phase 3 finalization completion transition metadata, `finalization.execution_count > 0`, `finalization.zero_execution = false`, durable first-class `audit_execution_id` resolved/assigned before raw evidence processing, and mandatory `config_version`.
- Raw evidence boundary: Phase 1 Raw Result Schema v1 and S3 raw result objects.
- Lineage boundary: bounded lineage manifest/reference, not unbounded inline raw references.
- Persistence boundary: immutable aggregate/job metadata child records and conditional writes.
- Security boundary: strict allowed-field output contract across aggregates, job metadata, lineage manifests, errors, and logs.

Out of scope:
- Implementing source tests in this QA task.
- Customer-facing UI/API behavior.
- Reliability conclusions, scores, reports, dashboards, AI recommendations, predictive analytics, release gates, or CI/CD decisions.

## 2. Acceptance Criteria Mapping

| Acceptance criterion / decision | Planned validation | Test scenario IDs |
| --- | --- | --- |
| AC-001: Aggregation runs only after successful finalization | Verify automatic aggregation only after successful finalization; reject incomplete, non-finalized, failed, cancelled, execution-failed, zero-execution, missing/invalid finalization transition, unresolvable `audit_execution_id`, and missing `config_version` cases with no aggregate records. | P4-AGG-001 through P4-AGG-006, P4-AGG-039 |
| Dedicated `audit_execution_id`; no `run_id` or `audit_id` substitution | Assert aggregate set identity and lineage contain durable first-class `audit_execution_id`; multiple `run_id` values remain source refs only; if Phase 4 assignment is needed, it is persisted before raw evidence processing by approved conditional metadata write; unresolvable/ambiguous execution id fails closed. | P4-AGG-004, P4-AGG-005, P4-AGG-020 |
| Mandatory `config_version` | Assert missing/null/empty/inconsistent `config_version` creates deterministic validation/ineligible outcome and no aggregates. | P4-AGG-006 |
| AC-002: Raw evidence is not mutated | Snapshot raw objects/run metadata before/after success and failure paths; assert read-only behavior. | P4-AGG-007, P4-AGG-008 |
| AC-003: Audit-level aggregate fields | Use manually calculated fixture oracles for counts, distributions, execution duration, latency summary, and endpoint execution counts. | P4-AGG-009 through P4-AGG-012 |
| Skipped count / `PAYLOAD_VALIDATION_ERROR` | Assert `skipped=0` for `agg_v1` and `PAYLOAD_VALIDATION_ERROR` contributes to failed counts and approved failure bucket. | P4-AGG-010, P4-AGG-014 |
| AC-004: Endpoint-level aggregate fields and safe endpoint IDs | Assert endpoint aggregates are correct and endpoint ids are bounded, opaque/sanitized, safe for keys/logs, and never raw URLs/query/PII. | P4-AGG-013, P4-AGG-031 |
| AC-005/006: Failure classifications grouped without inference | Assert only approved raw buckets plus missing/unknown deterministic buckets; no root-cause/AI/reliability categories. | P4-AGG-014, P4-AGG-015 |
| AC-007: Evidence lineage on every aggregate | Assert every aggregate references an immutable bounded manifest/reference that resolves to exact source refs; no unbounded inline refs. | P4-AGG-016 through P4-AGG-021 |
| Bounded lineage/item-size safety | Force large lineage; assert manifest is bounded, complete, immutable, deterministic, sanitized, and item-size safe or fails before writes. | P4-AGG-018, P4-AGG-019, P4-AGG-030 |
| AC-008: Repeated aggregation is idempotent | Repeat aggregation for same `{client_id, audit_id, audit_execution_id, config_version, aggregation_version}` and assert no duplicates/double counting. | P4-AGG-022, P4-AGG-023 |
| Duplicate raw source refs | Assert duplicate raw references fail controlled validation before aggregate creation; no heuristic dedupe and no silent double counting. | P4-AGG-024 |
| AC-009: Retry after failure is safe | Inject pre-write, read, validation, storage, and conflict failures; retry safely without partial complete sets or double counting. | P4-AGG-025 through P4-AGG-027 |
| AC-010: Duplicate trigger events are safe | Sequential and concurrent duplicate automatic triggers create one aggregate set and auditable sanitized duplicate outcomes. | P4-AGG-028, P4-AGG-029 |
| AC-011: Aggregate records are immutable/versioned | Assert `agg_v1` write-once records; unsupported version rejected; future version, if testable, creates separate records only. | P4-AGG-032, P4-AGG-033 |
| AC-012: No future phase behavior | Inspect outputs/side effects/routes/logs for absence of scores, reports, dashboards, AI insights, release gates, public/operator routes, or lifecycle transitions to analysis/reporting. | P4-AGG-034 |
| AC-013: Analytical metadata available | Assert counts, distributions, version, aggregate type, timestamps, and lineage manifest references are queryable without raw recomputation. | P4-AGG-035 |
| AC-014: Sensitive raw content excluded | Search aggregates, job metadata, lineage manifests, errors, responses, and captured logs for forbidden raw content and secret/PII patterns. | P4-AGG-036 |
| AC-015: Latency precision/rounding canonical | Validate nearest-rank p95/p99, deterministic median, and 3-decimal half-up rounding for `agg_v1`. | P4-AGG-011 |
| IAM/internal trigger/admin DR controls | Validate no public/customer invocation; IAM/resource policy limits; manual DR is privileged, idempotent, and auditable where implementation exposes it. | P4-AGG-037, P4-AGG-038 |
| Phase 3 regression | Existing Phase 3 lifecycle/finalization behavior remains green; automatic aggregation triggers only after successful finalization. | P4-AGG-039 |

## 3. Test Scenarios

### Eligibility, lifecycle, and canonical identity

1. **P4-AGG-001: Automatic trigger after successful finalization creates aggregate set**
   - Purpose: Prove system-managed aggregation starts only after successful Phase 3 finalization.
   - Input: Audit metadata `lifecycle_state=COMPLETED`, `finalization.execution_count > 0`, `finalization.zero_execution=false`, successful finalization completion transition metadata, durable first-class `audit_execution_id` or approved Phase 4 identity-assignment path, `config_version=config_v1`, completed run metadata, and valid raw result fixtures.
   - Expected output: Job `COMPLETED`; one immutable `agg_v1` aggregate set exists for `{client_id, audit_id, audit_execution_id, config_version, aggregation_version}`.
   - Validation logic: Invoke automatic trigger path or handler harness; query aggregate/job records; assert exact record count, aggregate identity fields, and no lifecycle mutation beyond allowed aggregation metadata.

2. **P4-AGG-002: Non-finalized lifecycle states are rejected/no-op**
   - Purpose: Validate incomplete audits cannot aggregate.
   - Input: Valid-looking evidence with lifecycle states `DRAFT`, `SCHEDULED`, `RUNNING`, `FINALIZING`.
   - Expected output: Controlled `INELIGIBLE`/equivalent outcome; no aggregate records.
   - Validation logic: Parameterized handler/orchestrator tests; assert reason code and absence of `#AGG#` records.

3. **P4-AGG-003: Failed/cancelled/execution-failed audits are rejected**
   - Purpose: Ensure terminal unsuccessful states do not aggregate even when raw evidence exists.
   - Input: `FAILED`, `CANCELLED`, and execution-failed finalization metadata variants.
   - Expected output: Controlled ineligible outcome; no aggregates or lineage manifests.
   - Validation logic: Query storage and captured logs for controlled sanitized reason only.

4. **P4-AGG-004: Zero-execution audit is ineligible**
   - Purpose: Align with human-approved zero-execution decision.
   - Input: `COMPLETED` or stale/inconsistent audit variants with `finalization.execution_count=0`, missing, negative, non-integer, or execution-failed finalization.
   - Expected output: No aggregate; no zero-count aggregate; controlled fail-closed reason such as `ZERO_EXECUTION_AUDIT_INELIGIBLE` or approved equivalent.
   - Validation logic: Assert no audit/endpoint/failure aggregate and no lineage manifest is created.

5. **P4-AGG-005: First-class `audit_execution_id` required and propagated**
   - Purpose: Validate durable execution identity creation/propagation/linkage.
   - Input: Eligible audit with `audit_execution_id=aexec_001`, multiple `run_id` values, and raw result refs.
   - Expected output: Every aggregate, job metadata field where applicable, aggregate-set identity, and lineage manifest reference use `audit_execution_id=aexec_001`; `run_id` appears only inside source raw result refs.
   - Validation logic: Inspect persisted records/manifests and key/idempotency identity; assert no `run_id` or `audit_id` substitution as canonical lineage key.

6. **P4-AGG-006: Execution identity resolution and mandatory `config_version` guardrails**
   - Purpose: Validate mandatory lineage values without `run_id`/`audit_id` substitution.
   - Input: Otherwise eligible audits with (a) persisted valid `audit_execution_id`, (b) missing upstream `audit_execution_id` but approved Phase 4 conditional identity-assignment path available, (c) missing/null/empty/unsafe or unassignable `audit_execution_id`, and (d) missing/null/empty/inconsistent `config_version`.
   - Expected output: Cases (a) and (b) produce aggregates using a durable first-class `audit_execution_id` persisted before raw evidence processing; cases (c) and (d) produce deterministic validation/ineligible outcome with no aggregate records; no inferred/defaulted/substituted `run_id` or `audit_id` values.
   - Validation logic: Assert controlled reason codes, sanitized errors/logs, identity metadata conditional write where applicable, aggregate/manifests absence for failed cases, and no raw evidence mutation.

### Raw evidence immutability

7. **P4-AGG-007: Raw S3 evidence and run metadata unchanged after success**
   - Purpose: Confirm raw evidence remains source of truth.
   - Input: Eligible audit with S3 raw objects and run metadata snapshots.
   - Expected output: Aggregates created; raw bytes, keys, checksums/version ids where available, run metadata, and result arrays unchanged.
   - Validation logic: Before/after snapshots and repository call spies proving no raw put/update/delete.

8. **P4-AGG-008: Failure paths do not mutate raw evidence**
   - Purpose: Validate immutability under read, validation, and write failures.
   - Input: Inject raw read failure, invalid raw schema, and aggregate write failure.
   - Expected output: Job `FAILED` with sanitized reason; raw evidence unchanged; no partial aggregate set treated as complete.
   - Validation logic: Compare snapshots and inspect job/aggregate records.

### Aggregate correctness

9. **P4-AGG-009: Audit-level counts and distributions match fixture oracle**
   - Purpose: Validate core audit aggregate fields.
   - Input: Mixed fixture with PASS, failures, status codes, NO_STATUS, endpoints, timestamps, and latencies.
   - Expected output: Exact `request_counts`, status distribution, endpoint execution counts, and duration match manual oracle.
   - Validation logic: Field-by-field assertion against checked-in expected JSON.

10. **P4-AGG-010: Skipped count is exactly zero for `agg_v1`**
    - Purpose: Prove Raw Result Schema v1 skipped semantics.
    - Input: Raw results containing `PAYLOAD_VALIDATION_ERROR`, missing latency, missing HTTP status, payload metadata, and no explicit skipped indicator.
    - Expected output: `request_counts.skipped=0`; `PAYLOAD_VALIDATION_ERROR` records included in failed count and failure bucket.
    - Validation logic: Reconcile total = successful + failed + skipped; assert skipped remains zero across audit and endpoint success denominator inputs.

11. **P4-AGG-011: Latency summary method and precision**
    - Purpose: Validate `count`, `min`, `max`, `mean`, `median`, `p95`, `p99` deterministically.
    - Input: Boundary latencies `[0, 1, 2, 3, 4, 5, 100, null, -1, "bad"]`.
    - Expected output: Only numeric `duration_ms >= 0` included; median uses deterministic middle/average rule; p95/p99 use nearest-rank `ceil(p/100 * count)`; emitted numeric latency statistics are rounded to 3 decimal places using half-up rounding.
    - Validation logic: Compare to independent manual oracle covering odd/even counts, nearest-rank boundaries, excluded values, and half-up rounding cases.

12. **P4-AGG-012: Reordered source evidence produces identical output**
    - Purpose: Prove determinism.
    - Input: Same raw evidence presented original, reversed, shuffled run order, and repeated execution.
    - Expected output: Byte-stable equivalent aggregates and manifest references, excluding allowed attempt-specific job metadata.
    - Validation logic: Hash normalized serialized aggregate content and manifest content.

13. **P4-AGG-013: Endpoint-level aggregate correctness**
    - Purpose: Validate endpoint scoping.
    - Input: Multiple safe endpoint ids plus missing endpoint id.
    - Expected output: One endpoint aggregate per represented sanitized endpoint; missing uses controlled placeholder; exact execution count, success inputs, latency, timeout, failure, HTTP distribution, and endpoint-scoped manifest reference.
    - Validation logic: Compare each endpoint aggregate to endpoint oracle; assert no cross-endpoint leakage.

14. **P4-AGG-014: Failure classification buckets preserve execution categories**
    - Purpose: Prevent heuristic inference and skipped misclassification.
    - Input: `PASS`, `ASSERTION_FAILURE`, `HTTP_ERROR`, `TIMEOUT`, `CONNECTION_ERROR`, `INVALID_RESPONSE`, `RUNNER_ERROR`, `PAYLOAD_VALIDATION_ERROR`.
    - Expected output: Counts preserve approved buckets only; `PAYLOAD_VALIDATION_ERROR` counted as failed, not skipped.
    - Validation logic: Compare classification map to allowlist and reconcile counts.

15. **P4-AGG-015: Missing/unknown classifications deterministic**
    - Purpose: Validate no silent loss.
    - Input: Missing, null, empty, whitespace, and unapproved non-empty failure types.
    - Expected output: `MISSING_FAILURE_CLASSIFICATION` and `UNKNOWN_FAILURE_CLASSIFICATION` or final approved equivalent; no inferred root cause.
    - Validation logic: Sum bucket counts to included source records.

### Bounded lineage manifest/reference

16. **P4-AGG-016: Every aggregate contains bounded lineage reference**
    - Purpose: Validate lineage presence without unbounded inline refs.
    - Input: Successful aggregate set.
    - Expected output: Every aggregate contains required lineage fields and a bounded `lineage_manifest_ref`/approved equivalent; no unbounded `source_raw_result_refs` array in aggregate items if it can exceed limits.
    - Validation logic: Inspect all aggregate records for `client_id`, `audit_id`, `audit_execution_id`, `config_version`, `aggregation_version`, `aggregation_job_id`, `aggregation_timestamp`, manifest id/version/checksum/location as designed.

17. **P4-AGG-017: Manifest completeness and deterministic reconstruction**
    - Purpose: Prove manifest can reconstruct exact source raw result refs.
    - Input: Multi-run fixture with S3 keys, run ids, result indexes, endpoint ids, timestamps, raw result version, and optional S3 version ids.
    - Expected output: Manifest resolves to exact canonical sorted source refs used for aggregation; endpoint aggregates resolve to endpoint-scoped refs or scoped manifest sections.
    - Validation logic: Load manifest via approved repository; compare to manual source-ref oracle and aggregate counts.

18. **P4-AGG-018: Manifest immutability and integrity**
    - Purpose: Validate evidence chain immutability.
    - Input: Completed aggregate set then repeat aggregation/retry/duplicate trigger.
    - Expected output: Existing manifest bytes/checksum/version unchanged; duplicate attempts reference existing manifest or create auditable duplicate metadata without mutation.
    - Validation logic: Snapshot manifest checksum/version/id before/after; assert conditional write protections.

19. **P4-AGG-019: Lineage item-size and data-exposure safety**
    - Purpose: Validate bounded lineage under large evidence sets.
    - Input: Large raw source-ref fixture that would exceed DynamoDB item size if inlined.
    - Expected output: Aggregate items remain within safe size with bounded manifest refs, or fail before aggregate creation if manifest design unavailable; no partial sets.
    - Validation logic: Measure persisted item sizes; assert controlled failure or bounded success.

20. **P4-AGG-020: `run_id` remains source-ref only**
    - Purpose: Prevent identity substitution.
    - Input: One `audit_execution_id` with multiple runs and duplicate-looking run identifiers across fixtures where safe.
    - Expected output: Aggregate-set identity never changes per run; `run_id` cannot be used in place of `audit_execution_id` for aggregate keys, lineage root, or idempotency.
    - Validation logic: Inspect keys/body/manifests; assert aggregate set count remains one per execution/config/version.

21. **P4-AGG-021: S3 version unavailable is explicitly represented without exposure**
    - Purpose: Preserve reproducibility evidence when versioning is unavailable.
    - Input: Raw evidence refs with no S3 version id.
    - Expected output: Manifest has approved sentinel/metadata for unavailable version identity, not omitted ambiguously; no raw sensitive fields.
    - Validation logic: Inspect manifest schema and reconstruction output.

### Idempotency, duplicate input, retry, and concurrency

22. **P4-AGG-022: Repeated aggregation creates no duplicates**
    - Purpose: Validate idempotency.
    - Input: Same finalized audit triggered multiple times with same aggregate identity.
    - Expected output: One immutable aggregate set; counts unchanged; duplicate job metadata sanitized/auditable.
    - Validation logic: Count records before/after and compare aggregate/manifest hashes.

23. **P4-AGG-023: Same audit with different config/execution/version creates distinct allowed set only when valid**
    - Purpose: Validate aggregate-set identity dimensions.
    - Input: Same audit id with changed valid `audit_execution_id`, `config_version`, or future supported aggregation version if available.
    - Expected output: Separate sets only when identity/version differs and is explicitly valid; no overwrite of existing records.
    - Validation logic: Query by prefixes and compare immutable snapshots.

24. **P4-AGG-024: Duplicate raw result reference fails before aggregate creation**
    - Purpose: Validate human-approved duplicate input failure behavior.
    - Input: Run metadata or manifest candidate containing duplicate stable refs `{raw_result_s3_key, s3_version_id if present, run_id, result_index}`.
    - Expected output: Controlled sanitized validation failure; no aggregate records; no lineage manifest for failed set except allowed failed-job metadata.
    - Validation logic: Query aggregate prefixes and logs; assert no heuristic dedupe/silent double count.

25. **P4-AGG-025: Retry after pre-write failure is safe**
    - Purpose: Validate no partial writes before retry.
    - Input: Inject raw evidence read or validation failure; retry after removal.
    - Expected output: First job failed with sanitized reason and no aggregates; retry creates exactly one set.
    - Validation logic: Inspect job and aggregate records after each attempt.

26. **P4-AGG-026: Retry after persistence conflict/partial boundary is safe**
    - Purpose: Validate transaction/rollback behavior.
    - Input: Inject conditional conflict or transaction failure during aggregate/manifest writes.
    - Expected output: No partial set treated as complete; retry either completes exactly one matching set or fails controlled conflict.
    - Validation logic: Inspect complete marker/manifest/aggregate consistency if implemented.

27. **P4-AGG-027: Aggregate set too large fails safely unless bounded manifest/chunk protocol is approved**
    - Purpose: Validate item/transaction limit handling.
    - Input: Large endpoint/lineage fixture.
    - Expected output: Controlled `AGGREGATE_SET_TOO_LARGE`/equivalent before aggregate creation, or fully validated bounded/chunked protocol.
    - Validation logic: Assert no partial aggregate set or complete bounded set only.

28. **P4-AGG-028: Duplicate trigger events are auditable no-ops**
    - Purpose: Validate duplicate event safety.
    - Input: Two identical automatic aggregation events.
    - Expected output: One aggregate set; duplicate attempt `DUPLICATE_COMPLETED`/equivalent; sanitized metadata/logs.
    - Validation logic: Sequential duplicate invocations; assert record counts and no sensitive content.

29. **P4-AGG-029: Concurrent trigger race produces one aggregate set**
    - Purpose: Validate concurrency safety.
    - Input: Parallel internal invocations for same aggregate identity.
    - Expected output: One completes/claims; others duplicate/conflict; no duplicate records.
    - Validation logic: Thread/process fake repository or integration harness with conditional write simulation.

### Security, authorization, scope guardrails, and regression

30. **P4-AGG-030: Storage-limit and lineage DoS guardrails**
    - Purpose: Validate bounded processing against oversized source sets/manifests.
    - Input: Evidence volume near and beyond configured caps.
    - Expected output: Bounded success or controlled sanitized failure before writes; no large raw content in logs/errors.
    - Validation logic: Item-size checks, failure reason checks, log scan.

31. **P4-AGG-031: Endpoint identifier safety**
    - Purpose: Validate endpoint IDs are safe for storage/logging.
    - Input: Endpoint fields containing raw URLs, query strings, credentials, PII-like values, headers, payload fragments, very long strings, control characters, path separators, and key-delimiter characters.
    - Expected output: Aggregate uses opaque/sanitized bounded identifier or controlled placeholder; unsafe content absent from keys, bodies, manifests, errors, and logs.
    - Validation logic: Assert identifier regex/length constraints and forbidden string scan.

32. **P4-AGG-032: Version validation and unsupported versions**
    - Purpose: Validate `agg_v1` and write-once versioning.
    - Input: `aggregation_version=agg_v1`, missing version if defaulting is specified, and unsupported `agg_v2`.
    - Expected output: Valid `agg_v1` succeeds; unsupported version returns controlled validation error and no aggregate.
    - Validation logic: Inspect handler response, job records, aggregate keys/body.

33. **P4-AGG-033: Existing aggregate/manifest immutability under future version seam**
    - Purpose: Protect versioned immutability.
    - Input: Existing `agg_v1`; future supported version only if implementation exposes a test seam.
    - Expected output: Future version writes separate records; existing `agg_v1` aggregate and manifest unchanged.
    - Validation logic: Snapshot byte/hash before/after. If no seam exists, execute unsupported-version rejection only.

34. **P4-AGG-034: No future-phase or public-facing behavior**
    - Purpose: Confirm scope boundaries.
    - Input: Successful aggregate run and source/static inspection.
    - Expected output: No scores, conclusions, reports, dashboards, recommendations, public/customer/operator route, release gate, CI/CD decision, Phase 5/6/7 trigger, or audit lifecycle transition to analyzing/reporting.
    - Validation logic: Inspect records, logs, route declarations, handlers, side effects, and lifecycle repository calls.

35. **P4-AGG-035: Analytical consumption metadata queryable**
    - Purpose: Validate internal future consumer readiness without raw recomputation.
    - Input: Completed aggregate set.
    - Expected output: Counts, distributions, aggregate types, version metadata, timestamps, and lineage manifest refs are typed/queryable.
    - Validation logic: Query by designed keys/prefixes and validate schema.

36. **P4-AGG-036: Strict allowed-field sanitization across all artifacts**
    - Purpose: Address security review blocker.
    - Input: Fixture with forbidden raw headers, cookies, request/response bodies, payloads, query params, raw URLs, tokens, secrets, credentials, PII-like values, and tenant-sensitive content.
    - Expected output: None of those strings/patterns appear in aggregate records, job metadata, lineage manifests/refs, handler responses/errors, exceptions, or captured logs; only approved fields/reason codes/counts/distributions/timestamps/versions/sanitized ids/bounded refs.
    - Validation logic: Persisted artifact scan plus captured structured-log scan using exact canary strings and secret-pattern regexes.

37. **P4-AGG-037: IAM and internal trigger controls**
    - Purpose: Validate aggregation is internal-only and least-privilege.
    - Input: Infrastructure/config/source policy artifacts and invocation attempts where executable.
    - Expected output: No public/customer HTTP route; IAM permits only approved backend roles/events; raw-results S3 write/delete not granted to aggregation role; metadata permissions scoped to required read/query/write prefixes where platform supports specificity.
    - Validation logic: Static policy review and negative invocation tests using unauthorized principal/harness where available.

38. **P4-AGG-038: Privileged administrative DR trigger controls**
    - Purpose: Validate manual aggregation/reaggregation is DR-only.
    - Input: Admin DR invocation path if implemented, unauthorized actor, authorized admin role, already aggregated audit.
    - Expected output: Unauthorized invocation denied; authorized DR invocation is auditable, idempotent, sanitized, and does not overwrite existing aggregates/manifests.
    - Validation logic: Authz tests/policy review plus record/log inspection. If no DR path is implemented, confirm no manual public/operator path exists.

39. **P4-AGG-039: Phase 3 lifecycle regression and automatic trigger boundary**
    - Purpose: Protect existing scheduling/finalization behavior.
    - Input: Existing Phase 3 targeted suites and finalization scenarios.
    - Expected output: Successful nonzero finalization reaches `COMPLETED` and triggers aggregation once; zero-execution finalization reaches failed/ineligible path and does not trigger aggregation; audit listing/discovery ignores `#AGG#`/`#AGGJOB#` child records.
    - Validation logic: Execute/review relevant existing tests when implementation is ready: scheduled execution, duplicate delivery, lifecycle state machine, cancellation/finalization, occurrence claims, event contracts, safeguards, and canonical audit-list filtering.

## 4. Edge Cases

- Aggregation trigger arrives before finalization metadata is durably persisted: controlled ineligible/conflict outcome and no aggregate.
- Audit is `COMPLETED` but lacks persisted first-class `audit_execution_id`: approved Phase 4 identity-assignment path may create a durable conditional metadata identity before raw evidence processing; otherwise fail closed. `run_id` or `audit_id` must never be substituted as canonical identity.
- Audit is `COMPLETED` but lacks `config_version`: fail closed; no aggregate and no inferred/default value.
- `finalization.execution_count=0`, missing, invalid, or execution-failed: ineligible; no zero-count aggregate.
- Raw evidence contains no explicit skipped indicator: `skipped=0` for `agg_v1`.
- Raw evidence contains `PAYLOAD_VALIDATION_ERROR`: counted as failure, not skipped.
- Raw results include missing/non-numeric/negative latency: excluded from latency stats and reflected only by `latency_summary_ms.count` of valid values.
- Latency percentile and rounding edge cases: nearest-rank p95/p99, deterministic median, and 3-decimal half-up rounding must match manual oracle values exactly.
- Raw result has non-HTTP/network failure and no HTTP status: status distribution uses `NO_STATUS` if allowed by schema.
- Failure classification missing/null/empty/whitespace/unknown: deterministic bucket or final approved explicit behavior; no silent discard.
- Endpoint identifier missing/unsafe/unbounded/contains raw URL/query/credential/PII/header/payload: safe placeholder or opaque/sanitized id; raw content absent everywhere.
- Duplicate source raw result refs: controlled validation failure before aggregate creation; no heuristic dedupe.
- Existing `agg_v1` set receives duplicate trigger: duplicate/no-op; no overwrite or count changes.
- Unsupported aggregation version: controlled validation error and no aggregate.
- Source raw evidence cannot be read: failed job with sanitized reason; no raw mutation; no partial aggregate set.
- Aggregate/manifest write fails after job start: retry/rollback protocol prevents partial complete set and double counting.
- Concurrent triggers race: one aggregate set at most.
- Large lineage/reference set: bounded manifest/ref or controlled failure before aggregate creation; aggregate item size remains safe.
- S3 version id unavailable: manifest explicitly records unavailable object-version identity in approved non-sensitive form.
- Logs/errors/job metadata must never expose raw headers, cookies, bodies, payloads, query params, raw URLs, tokens, secrets, credentials, PII, or tenant-sensitive raw content.
- Manual DR trigger, if present: privileged only, auditable, idempotent, sanitized, and no public/operator/customer access.

## 5. Test Types Covered

- **Unit tests:** eligibility, event validation, `audit_execution_id`/`config_version` guards, count semantics, skipped/failure classification buckets, latency statistics, endpoint id sanitizer, lineage manifest builder, duplicate raw ref validator, deterministic sorting/serialization, version validation.
- **Integration tests:** internal handler/orchestrator with fake/local DynamoDB/S3, automatic trigger after finalization, aggregate/job persistence, manifest persistence/reconstruction, raw evidence read-only behavior, retry/duplicate/concurrency behavior.
- **Contract/API tests:** internal event schema validation, unsupported versions, identifier safety, sanitized responses/errors, no public route.
- **Security tests:** strict allowed-field scans, endpoint id safety, IAM/resource policy review, internal trigger authorization, admin DR authorization, no raw-results S3 write/delete permission, sanitized logs/errors.
- **Regression tests:** Phase 1 raw evidence assumptions, Phase 3 scheduling/finalization/lifecycle behavior, canonical audit discovery/listing unaffected by aggregate child records, automatic trigger only after successful finalization.
- **Static/source inspection:** no raw mutation methods in aggregation path, no future-phase behavior, no public/operator/customer invocation path, key/index/constraint alignment, sanitized logging usage.
- **Concurrency/reliability tests:** duplicate triggers, repeated runs, retries after failure, conditional write conflicts, oversized set handling.
- **Fixture-based deterministic tests:** manually calculated expected oracle JSON for audit, endpoint, failure classification, latency, manifest, and sanitization outcomes.

## 6. Coverage Justification

The planned coverage maps product acceptance criteria, architecture decisions, and security-review blockers to deterministic validations at the smallest stable boundary and the internal end-to-end orchestration boundary. The aggregation engine must be proven with fixture oracles, while the handler/orchestrator/repository path must prove eligibility gating, first-class execution identity, mandatory configuration version, immutable bounded lineage, conditional-write idempotency, duplicate/retry safety, authorization boundaries, and sanitized auditability.

### Required fixture additions after implementation

Add implementation-appropriate fixtures and manual oracle outputs when source tests are created:
- `fixture_aggregate_mixed_results_v1`: multiple completed runs/endpoints, approved failure types, status codes including `NO_STATUS`, timestamps, valid/invalid latencies, `audit_execution_id`, `config_version`.
- `fixture_skipped_zero_payload_validation_failure_v1`: `PAYLOAD_VALIDATION_ERROR` and no skipped indicator; oracle `skipped=0`, failed includes payload validation.
- `fixture_latency_percentiles_v1`: values proving canonical percentile method and precision/rounding.
- `fixture_endpoint_id_safety_v1`: raw URLs, query params, credentials, PII-like strings, headers, payload fragments, long/control/key-delimiter strings.
- `fixture_missing_unknown_failures_v1`: missing/null/empty/whitespace/unapproved failure types.
- `fixture_lineage_manifest_multi_run_v1`: multiple runs/results with exact source-ref oracle and manifest checksum expectation.
- `fixture_duplicate_raw_refs_v1`: duplicate stable source reference expected to fail validation before writes.
- `fixture_reordered_sources_v1`: same evidence reordered for deterministic hash comparison.
- `fixture_sensitive_raw_content_v1`: canary secrets/tokens/cookies/headers/bodies/query params/PII for aggregate/job/manifest/error/log scans.
- `fixture_large_lineage_set_v1`: enough source refs/endpoints to exercise bounded manifest/item-size/transaction-limit behavior.
- `fixture_identity_resolution_v1` and `fixture_missing_config_version_v1`: persisted identity, approved Phase 4 identity assignment, unassignable/unsafe identity fail-closed, and mandatory config guardrails.
- `fixture_zero_execution_audit_v1`: finalization execution count zero/failed; no aggregate expected.

Manual oracle content must include request counts, status distributions, duration, latency summary, endpoint execution counts, endpoint-scoped counts, failure classification buckets, manifest source refs, manifest checksum/content identity where applicable, and forbidden-string expectations for sanitization tests.

### Storage, lineage, index, and constraint validation

QA must validate:
- Aggregate identity includes `{client_id, audit_id, audit_execution_id, config_version, aggregation_version}`.
- `run_id` is not used as canonical aggregate lineage/set identity.
- Aggregate/job key patterns are safe and do not expose raw endpoint content.
- Aggregate records are write-once and one complete aggregate set exists per valid identity.
- Lineage uses bounded immutable manifest/reference rather than unbounded inline refs.
- Manifest references resolve deterministically to exact source refs and reconcile to aggregate counts.
- Manifest and aggregate items stay under safe storage limits or fail before writes.
- Canonical audit discovery/listing remains unaffected by new child records.

### Regression coverage requirements

Phase 4 sign-off requires no regression in Phase 3 scheduling/audit lifecycle behavior because automatic aggregation depends on Phase 3 finalization. At minimum, execute or review targeted existing coverage for:
- schedule creation and duplicate delivery behavior;
- lifecycle state machine transitions;
- cancellation and finalization;
- successful nonzero finalization reaching `COMPLETED` and triggering aggregation once;
- zero-execution finalization reaching failed/ineligible behavior and not triggering aggregation;
- audit discovery/listing strict canonical-row filtering.

### Failure classification process for execution reporting

For every failed or inconclusive validation, the later test report must include:
- Exact test name and command/workflow.
- Expected behavior and observed behavior.
- Error messages, logs, persisted records, manifest refs/content hashes, and fixture identifiers.
- Reproduction steps and whether reproduction is deterministic.
- Impact severity: Blocker, Critical, Major, Minor, or Informational.
- Classification: Application Bug, Test Bug, Environment Issue, Flaky Test, Data/Contract Issue, Security Finding, or Unclear.

QA must not infer root cause without evidence. Any unresolved failure, unclear data/contract mismatch, missing security control evidence, or nondeterministic/flaky behavior affecting critical criteria blocks sign-off.

### QA sign-off criteria

QA may approve Phase 4 only if all of the following are proven with execution evidence in a later test report:
- All critical acceptance-criteria tests pass.
- Dedicated `audit_execution_id` is present, propagated, and used for aggregate set identity; no `run_id` or `audit_id` substitution.
- Missing/unassignable `audit_execution_id` or missing `config_version` fails closed with no aggregate; approved Phase 4 identity assignment, if needed, persists a durable first-class identity before raw evidence processing.
- Zero-execution/execution-failed audits create no aggregate.
- `skipped=0` for `agg_v1`; `PAYLOAD_VALIDATION_ERROR` is counted as failure.
- Duplicate source raw refs fail controlled validation before writes.
- Deterministic fixture outputs match manual oracle values.
- Bounded immutable lineage manifest/reference is complete, reconstructable, sanitized, and item-size safe.
- Repeated, duplicate, retry, rollback, and concurrency tests create no duplicate records and no double counting.
- Raw evidence, existing aggregate records, and lineage manifests remain immutable.
- Latency summaries match final documented percentile and precision/rounding rules.
- Strict allowed-field tests prove no raw headers/cookies/bodies/payloads/query params/tokens/secrets/PII leak into aggregates, job metadata, lineage, errors, or logs.
- Endpoint identifier safety tests pass.
- IAM/internal trigger/admin DR controls are verified where testable; no public/customer/operator invocation exists.
- No Phase 5/6/7 behavior, public API, UI, dashboard, score, recommendation, or release gate is introduced.
- Targeted Phase 3 scheduling/audit lifecycle regression tests pass.
- No blocking defects, major regressions, unresolved failures, or unclassified flaky tests remain.

### Remaining QA blockers / implementation-time evidence required before final sign-off

- Architecture/security review evidence should be refreshed against the revised design before implementation sign-off; prior review artifacts are not present in the repository.
- Implementation must expose enough records/logs/test seams for QA to verify Phase 4 identity assignment, if used, occurs by approved conditional metadata write before raw evidence processing and never substitutes `run_id` or `audit_id`.
- IAM/internal trigger/admin DR policies must be available for review if infrastructure changes are included.
- If implementation deviates from current MVP fail-before-write behavior and introduces chunked/S3 manifest persistence, QA requires a separately reviewed complete marker, chunk integrity, access-control, and recovery protocol before approval.
