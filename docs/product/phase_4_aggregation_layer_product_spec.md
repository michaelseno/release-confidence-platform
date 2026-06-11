# Product Specification

## 1. Feature Overview

Phase 4 implements the Aggregation Layer for the Release Confidence Platform.

This phase transforms finalized raw audit execution evidence into deterministic, reproducible, lineage-preserving aggregate datasets. Raw execution evidence remains the source of truth. Aggregates are derived summaries only and must never mutate, delete, replace, reinterpret, or supersede raw evidence.

Phase 4 begins after Phase 3 audit scheduling, lifecycle orchestration, execution evidence capture, and finalization are complete. Aggregation may execute only for successfully finalized audits that meet the confirmed eligibility boundary: `lifecycle_state = COMPLETED`, `finalization.execution_count > 0`, `finalization.zero_execution = false`, and a successful finalization completion transition. Eligible audits must also have valid execution evidence, valid `audit_execution_id`, and valid `config_version`, and must produce audit-level and endpoint-level aggregate records that are ready for later analytical consumption by Phase 5 Reliability Intelligence, Phase 6 Reporting, and Phase 7 CI/CD Integration.

Phase 4 does not implement reliability conclusions, AI insight, scoring, dashboards, reports, customer recommendations, predictive analytics, release gating, operator workflows, or customer-facing features.

### Backend / System Impact

- The platform must introduce a durable `audit_execution_id` and a deterministic aggregation job that reads finalized raw evidence and writes immutable aggregate records.
- The aggregation lifecycle must be auditable and retry-safe.
- Every aggregate record must preserve complete evidence lineage back to the source audit, durable audit execution identity, configuration version, aggregation version, aggregation job, timestamp, and bounded source evidence lineage without exposing sensitive raw evidence content.
- Aggregate outputs must be reproducible from the same finalized raw evidence and aggregation version.
- Duplicate event delivery, repeated job execution, and retry scenarios must not create duplicates or double-count evidence.

## 2. Problem Statement

The platform can collect raw audit execution evidence and finalize audit windows, but downstream reliability intelligence and reporting phases require normalized, queryable, reproducible datasets. Without an aggregation layer, later phases would either need to repeatedly scan raw evidence directly or risk introducing inconsistent summarization logic across multiple consumers.

Phase 4 solves this by creating a deterministic aggregation layer that summarizes finalized raw evidence into immutable audit-level and endpoint-level datasets while preserving full evidence lineage and keeping raw evidence as the authoritative source of truth.

## 3. User Persona / Target User

- **Platform engineer / developer:** implements deterministic aggregation, storage, versioning, idempotency, lineage, and lifecycle integration.
- **QA engineer:** validates aggregate correctness, retry safety, duplicate handling, lifecycle gating, and reproducibility.
- **Future internal analytical consumer:** Phase 5 Reliability Intelligence, Phase 6 Reporting, and Phase 7 CI/CD Integration components that will consume aggregate datasets later without owning raw evidence summarization logic.

No operator or customer-facing persona is in scope for Phase 4.

## 4. User Stories

- As a platform engineer, I want finalized raw audit evidence to be summarized into deterministic aggregate records so that later phases can consume consistent datasets.
- As a platform engineer, I want every aggregate record to preserve source evidence lineage so that any derived summary can be traced back to the raw evidence used to produce it.
- As a QA engineer, I want repeated aggregation for the same finalized audit to produce identical results without duplicates so that retries and duplicate events are safe.
- As a future internal analytical consumer, I want audit-level and endpoint-level aggregate datasets so that Phase 5, Phase 6, and Phase 7 can build on stable inputs without implementing aggregation in their own scope.

## 5. Goals / Success Criteria

Phase 4 is successful when:

- Aggregation executes only after an audit meets the confirmed successful-finalization eligibility boundary: `lifecycle_state = COMPLETED`, `finalization.execution_count > 0`, `finalization.zero_execution = false`, and a successful finalization completion transition.
- Incomplete, non-finalized, failed-finalization, execution-failed, zero-execution, cancelled, or in-progress audits are not aggregated.
- Phase 4 introduces a durable `audit_execution_id` as the primary long-term execution identifier for evidence lineage; `run_id` may continue only as an implementation detail and must not be the long-term lineage identifier.
- `config_version` is mandatory for evidence lineage, must be validated before aggregation processing, and no aggregate may be produced without a valid `config_version`.
- Raw execution evidence remains immutable and is never mutated, deleted, replaced, or reclassified by aggregation.
- Audit-level aggregate records include total, successful, failed, and skipped request counts; timeout count; network failure count; status code distribution; execution duration; latency summary statistics; and endpoint execution counts, using canonical count semantics defined in this specification. For Phase 4 / Raw Result Schema v1, `skipped_requests` is always `0` because there is no explicit skipped indicator.
- Endpoint-level aggregate datasets include endpoint execution count, success-rate inputs, latency distributions, timeout occurrences, failure classification counts, and HTTP response distribution.
- Failure classification aggregation groups only execution-generated Raw Result Schema v1 categories that already exist in raw evidence and does not perform heuristic root-cause inference. In-scope categories are `PASS`, `ASSERTION_FAILURE`, `HTTP_ERROR`, `TIMEOUT`, `CONNECTION_ERROR`, `INVALID_RESPONSE`, `RUNNER_ERROR`, and `PAYLOAD_VALIDATION_ERROR`; missing or unknown classifications must use deterministic controlled bucket names defined by architecture.
- Every aggregate record includes evidence lineage fields: audit identifier, durable audit execution identifier, configuration version, aggregation version, aggregation job identifier, aggregation timestamp, and a bounded lineage manifest/reference that can deterministically resolve to the exact source raw result references.
- Repeated aggregation against the same finalized audit and aggregation version produces identical aggregate content without duplicate records or double counting.
- Duplicate aggregation events and retry attempts are handled deterministically and audibly.
- Aggregate records are immutable, versioned, reproducible, lineage-preserving, and structured for analytical consumption.
- Phase 4 creates future-compatible datasets for Phase 5 Reliability Intelligence, Phase 6 Reporting, and Phase 7 CI/CD Integration without implementing those phases.
- Aggregate outputs, job metadata, lineage, errors, and logs contain only approved aggregate fields, sanitized identifiers, controlled reason codes, counts, distributions, timestamps, versions, and bounded source references; they must not persist raw headers, cookies, request bodies, response bodies, payloads, query parameters, tokens, secrets, credentials, PII, or tenant-sensitive raw content.

## 6. Feature Scope

### In Scope

Phase 4 includes only the following functionality:

- Aggregation lifecycle integration after successful audit finalization.
- Deterministic aggregation job creation and execution for finalized audits.
- Audit-level aggregate record generation.
- Endpoint-level aggregate dataset generation.
- Aggregation of execution-generated failure classification categories.
- Evidence lineage capture on every aggregate record.
- Introduction and propagation of durable `audit_execution_id` for aggregation lineage.
- Mandatory `config_version` validation before aggregation processing.
- Strict allowed-field aggregation contract and sensitive-data exclusion for aggregate records, job metadata, lineage, errors, and logs.
- Opaque or sanitized endpoint identifiers suitable for aggregation and storage.
- Idempotency and retry safety for repeated aggregation attempts.
- Duplicate aggregation event handling.
- Immutable aggregate record storage requirements.
- Aggregate versioning and aggregation version metadata.
- Reproducibility requirements for aggregate outputs.
- Analytical consumption readiness for later internal phases.
- QA-testable behavior for lifecycle gating, aggregate correctness, lineage preservation, duplicate handling, and retry safety.

### Out of Scope

The following are explicitly excluded from Phase 4:

- Operator experience initiative or operator-facing workflow changes.
- Customer-facing UI, dashboards, reports, report exports, or visualizations.
- Reliability conclusions, reliability scoring, release confidence scoring, or pass/fail release judgments.
- AI insights, AI-generated recommendations, customer recommendations, or remediation guidance.
- Predictive analytics, trend interpretation, anomaly explanation, or root-cause inference.
- Release gating, CI/CD pass/fail decisions, deployment blocking, or pipeline integrations.
- Phase 5 Reliability Intelligence implementation.
- Phase 6 Reporting implementation.
- Phase 7 CI/CD Integration implementation.
- New public customer-facing API surface.
- Authentication, RBAC, billing, subscriptions, account management, or onboarding.
- Mutation, deletion, compaction, reclassification, or replacement of raw evidence.
- Heuristic failure classification or inference beyond grouping categories already present in execution evidence.
- Cross-audit benchmarking, customer benchmarking, or long-term trend analysis.
- Operational dashboards, distributed tracing, advanced observability products, load testing, uptime-monitor clone behavior, or chaos engineering.
- Public, customer, or operator invocation of aggregation jobs.
- Normal operator-triggered aggregation or reaggregation actions.
- Raw URLs, query strings, request/response headers, cookies, bodies, payload fragments, credentials, secrets, tokens, PII, or tenant-sensitive raw content in aggregate outputs, job metadata, lineage, errors, or logs.

### Future Considerations

- Phase 5 may consume aggregates to produce reliability intelligence and conclusions.
- Phase 6 may consume aggregates to generate operator/customer-facing reports.
- Phase 7 may consume aggregates to support CI/CD integration and release workflow signals.
- Future phases may add re-aggregation workflows for new aggregation versions, provided lineage and immutability requirements are preserved.
- Future schema evolution may add explicit skipped semantics without changing Phase 4 behavior that treats `skipped_requests` as `0` for Raw Result Schema v1.

## 7. Functional Requirements

### FR-001: Aggregation Trigger Eligibility

The system must run aggregation only for audits that have completed successful finalization and have valid execution evidence.

An audit is eligible for aggregation only when the persisted audit lifecycle state and finalization metadata satisfy all confirmed eligibility requirements: `lifecycle_state = COMPLETED`, `finalization.execution_count > 0`, `finalization.zero_execution = false`, and a successful finalization completion transition. Audits that are incomplete, not finalized, finalizing, failed, cancelled, execution-failed, zero-execution, metadata-inconsistent, or finalized with a failure outcome must be rejected or skipped without aggregate creation.

Product rule: No evidence → No aggregation → No downstream intelligence.

### FR-002: Raw Evidence Source of Truth

Aggregation must read raw execution evidence as an input and must not mutate, delete, replace, compact, reclassify, or otherwise alter raw evidence.

Aggregate records must be treated as derived summaries. They must not be used as the source of truth for evidence capture.

### FR-003: Audit-Level Aggregate Record

For each eligible finalized audit, the system must produce an audit-level aggregate record containing, at minimum:

- total request count
- successful request count
- failed request count
- skipped request count
- timeout count
- network failure count
- HTTP status code distribution
- execution duration for the audit evidence window being aggregated
- latency summary statistics
- endpoint execution counts

Latency summary statistics must be deterministic and derived only from raw evidence latency values that are present and valid for aggregation.

Canonical request count semantics for Phase 4 are:

- `total request count` is the count of included raw result records after validation for aggregation.
- `successful request count` is the count of included raw result records whose raw execution outcome is successful.
- `failed request count` is the count of included raw result records whose raw execution outcome is failed, including `PAYLOAD_VALIDATION_ERROR`.
- `skipped request count` is `0` for all Phase 4 aggregates because Raw Result Schema v1 has no explicit skipped indicator; Phase 4 must not infer skipped status heuristically from `PAYLOAD_VALIDATION_ERROR`, missing latency, missing HTTP status, payload metadata, or other failure fields.
- `timeout count` and `network failure count` are counted only from execution-generated raw evidence categories or flags that explicitly represent those outcomes.

`PAYLOAD_VALIDATION_ERROR` remains an execution failure and is not skipped.

### FR-004: Endpoint-Level Aggregate Dataset

For each endpoint represented in the finalized raw evidence, the system must produce endpoint-level aggregate data containing, at minimum:

- opaque or sanitized endpoint identifier
- endpoint execution count
- success-rate inputs, including numerator and denominator values rather than a reliability conclusion
- latency distribution data
- timeout occurrence count
- failure classification counts
- HTTP response distribution

Endpoint-level data must support analytical consumption without requiring consumers to rescan raw evidence for these basic counts and distributions.

Endpoint identifiers used in aggregate records must be bounded and safe for storage/logging. They must not contain raw URLs, query strings, credentials, PII, request/response headers, payload fragments, or unbounded strings. If a safe endpoint identifier is missing or cannot be derived from approved non-sensitive fields, the record must use a controlled sanitized placeholder rather than raw endpoint content.

### FR-005: Failure Classification Aggregation

The system must aggregate failure classifications by deterministically grouping only categories already generated during execution and stored in raw evidence.

For Raw Result Schema v1, in-scope execution-generated classification categories are `PASS`, `ASSERTION_FAILURE`, `HTTP_ERROR`, `TIMEOUT`, `CONNECTION_ERROR`, `INVALID_RESPONSE`, `RUNNER_ERROR`, and `PAYLOAD_VALIDATION_ERROR`.

The system must not infer root cause, assign new failure categories, reinterpret failures, enrich failures with AI, or perform heuristic classification.

Unknown or missing failure classification values must be handled deterministically using controlled bucket names defined by architecture, not heuristic inference, ad hoc labels, silent discard, or documented exclusion.

### FR-006: Evidence Lineage Fields

Every aggregate record must include lineage metadata containing, at minimum:

- audit identifier
- durable audit execution identifier
- configuration version
- aggregation version
- aggregation job identifier
- aggregation timestamp
- bounded lineage manifest/reference that can resolve deterministically to the exact source raw result references

Lineage metadata must be sufficient for a developer or QA engineer to identify the exact raw evidence inputs used to produce the aggregate.

Phase 4 must introduce a durable `audit_execution_id` as the primary long-term execution identifier for aggregation lineage. Future lineage for Reliability Intelligence, Reporting, CI/CD integration, Commercialization, customer-facing reports, support tooling, and multi-tenant commercialization must reference `audit_execution_id` as the primary execution identifier.

The system must not reuse `run_id` as the long-term `audit_execution_id`. `run_id` may continue to exist only as an implementation detail and must not be used as the primary durable execution identifier in aggregate lineage.

Phase 4 must not create aggregate records when the durable `audit_execution_id` is missing or invalid. The system must not silently substitute `audit_id`, `run_id`, or any other identifier for `audit_execution_id`.

An approved Phase 4 implementation path may assign and persist the first-class durable `audit_execution_id` before raw evidence processing so that finalized evidence has valid execution identity for aggregation lineage. If the system cannot safely assign or confirm this identity, aggregation must still fail closed as missing or invalid identity without substituting `audit_id`, `run_id`, or any other identifier.

`config_version` is mandatory for evidence lineage. Aggregation must validate `config_version` before processing. Phase 4 may propagate and persist `config_version` where necessary, but no aggregate may be produced when `config_version` is missing or invalid. The system must fail closed with a deterministic sanitized validation error and must not invent, default, or infer a configuration version.

Aggregates must not embed unbounded raw result reference lists. Phase 4 must use a bounded lineage manifest or deterministic lineage reference that enables complete source evidence reconstruction. The lineage design must satisfy deterministic reconstruction, complete traceability, auditability, and immutable evidence linkage without oversized aggregate records.

The lineage manifest/reference itself becomes part of the immutable evidence chain and must be immutable, sanitized, versioned, access-controlled by existing internal boundaries, and resolvable to the exact source raw result references used for aggregation.

### FR-007: Aggregation Job Identity

Each aggregation attempt must have an aggregation job identifier.

The job identifier must be persisted with aggregate records and with any aggregation lifecycle or audit trail metadata created by Phase 4. Retry attempts must be traceable without causing duplicate aggregate records or double counting.

### FR-008: Idempotency and Retry Safety

Repeated execution of aggregation against the same finalized audit, same source raw evidence set, same configuration version, and same aggregation version must produce identical aggregate outputs.

The system must prevent duplicate aggregate records and double counting when aggregation is retried, when an aggregation event is delivered more than once, or when an already-aggregated audit is processed again.

If the aggregation input contains duplicate source raw result references within the same aggregate set, the system must fail aggregation before aggregate record creation with a controlled sanitized validation outcome. Silent double counting is prohibited, and heuristic deduplication that hides the duplicate-input condition is out of scope for Phase 4.

### FR-009: Duplicate Event Handling

The system must detect duplicate aggregation trigger events for the same finalized audit and aggregation version.

Duplicate events must not create additional aggregate records, overwrite immutable aggregates, or increment counts. Duplicate handling must be auditable through controlled metadata or logs that do not expose sensitive raw evidence content.

### FR-010: Lifecycle Integration

Aggregation must integrate with the audit lifecycle boundary created by Phase 3 finalization.

Aggregation is a system-managed lifecycle stage that is automatically triggered after successful audit finalization. It must not be exposed as a normal operator action.

Manual aggregation or reaggregation is reserved exclusively for privileged administrative disaster recovery. Any administrative disaster recovery trigger must be idempotent and fully auditable, and must not bypass eligibility, lineage, immutability, `audit_execution_id`, or `config_version` requirements.

The system must ensure:

- aggregation starts only after successful finalization;
- incomplete or non-finalized audits are not aggregated;
- aggregation lifecycle transitions are deterministic and auditable;
- aggregation failure does not mutate raw evidence;
- aggregation completion is recorded without automatically executing Phase 5, Phase 6, or Phase 7 workflows.

### FR-011: Immutable Aggregate Storage

Aggregate records must be immutable after creation.

Corrections, new aggregation logic, or new aggregation versions must create new versioned aggregate records rather than modifying existing aggregate records. Existing aggregate records must remain traceable to their aggregation version and source evidence.

If the complete aggregate set cannot be written atomically or safely within platform storage limits, the MVP behavior is controlled failure before aggregate record creation. Partial aggregate sets must not be treated as complete. Chunked aggregate persistence is out of scope unless separately specified by architecture and validated by QA.

### FR-012: Aggregation Versioning and Reproducibility

Aggregate outputs must include an aggregation version.

For a fixed raw evidence input set, configuration version, and aggregation version, aggregate computation must be reproducible. Any future change that can alter aggregate output semantics must use a new aggregation version.

For `agg_v1`, latency summaries must use only numeric latency duration values greater than or equal to zero from included raw evidence. The canonical latency summary set is `count`, `min`, `max`, `mean`, `median`, `p95`, and `p99`. Latency summaries must use the architecture-confirmed canonical rule: deterministic median, nearest-rank p95 and p99, 3 decimal places, and half-up rounding so repeated aggregation produces byte-stable equivalent values.

### FR-013: Analytical Consumption Readiness

Aggregate records must be structured so later internal phases can consume counts, distributions, lineage, and version metadata without implementing Phase 4 aggregation logic.

Phase 4 must not expose these datasets as customer-facing reports, dashboards, recommendations, scores, or release gates.

## 8. Non-Functional Requirements

### NFR-001: Determinism

Aggregation must produce stable outputs for identical finalized inputs and aggregation version. Ordering-dependent processing must not alter counts, distributions, lineage references, or serialized aggregate content where deterministic serialization is required by implementation.

### NFR-002: Auditability

Aggregation eligibility decisions, job execution, duplicate handling, retry handling, success, and failure must be auditable through persisted metadata or sanitized logs.

### NFR-003: Data Integrity

Aggregate counts and distributions must reconcile to the source raw evidence included in lineage. The system must avoid silent loss of source records.

### NFR-004: Immutability

Raw evidence and aggregate records must remain immutable under Phase 4 behavior.

### NFR-005: Security and Sensitive Data Handling

Aggregate records, job metadata, lineage, errors, and logs must follow a strict allowed-field contract. Allowed persisted content is limited to sanitized identifiers, controlled reason codes, aggregate counts, aggregate distributions, approved failure classification labels, timestamps, versions, bounded source references/manifests, and other explicitly approved non-sensitive aggregate metadata.

Phase 4 must not persist or log sensitive raw fields, including headers, cookies, request bodies, response bodies, payloads, query parameters, raw URLs, tokens, secrets, credentials, PII, tenant-sensitive raw content, or payload fragments. This prohibition applies equally to successful outputs, failed-job metadata, validation errors, duplicate handling metadata, lineage references, and logs.

### NFR-006: Testability

All aggregation behavior must be unit-testable or integration-testable using deterministic finalized raw evidence fixtures.

## 9. Acceptance Criteria

### AC-001: Aggregation Runs Only After Successful Finalization

Given an audit has `lifecycle_state = COMPLETED`, `finalization.execution_count > 0`, `finalization.zero_execution = false`, a successful finalization completion transition, valid execution evidence, a valid `audit_execution_id`, and a valid `config_version`  
When the aggregation trigger is processed  
Then the system creates aggregate records for that finalized audit.

Given an audit is otherwise finalized but lacks a confirmed durable audit execution identifier or configuration version  
When the aggregation trigger is processed  
Then the system creates no aggregate records and records a controlled sanitized ineligible or validation-failed outcome without inventing missing lineage values.

Given an audit has a `run_id` but lacks a valid durable `audit_execution_id`  
When the aggregation trigger is processed  
Then the system creates no aggregate records and does not reuse `run_id` as the durable `audit_execution_id`.

Given an audit lacks a valid `config_version`  
When aggregation validation runs  
Then aggregation fails closed with a deterministic sanitized validation error before processing and creates no aggregate records.

Given an audit is in `DRAFT`, `SCHEDULED`, `RUNNING`, or `FINALIZING` state  
When the aggregation trigger is processed  
Then the system does not create aggregate records and records a controlled ineligible-audit outcome.

Given an audit is `FAILED` or `CANCELLED`  
When the aggregation trigger is processed  
Then the system does not create aggregate records.

Given an audit has zero valid raw execution result records or execution failed before valid evidence was produced  
When the aggregation trigger is processed  
Then the system creates no aggregate records and records a controlled no-evidence or execution-failed outcome.

### AC-002: Raw Evidence Is Not Mutated

Given finalized raw evidence exists for an eligible audit  
When aggregation completes successfully  
Then the raw evidence records remain unchanged and no raw evidence records are deleted or replaced.

### AC-003: Audit-Level Aggregate Fields Are Produced

Given finalized raw evidence contains successful, failed, timeout, network failure, HTTP status, latency, duration, and endpoint execution data  
When aggregation completes  
Then the audit-level aggregate contains total, successful, failed, and skipped request counts; timeout count; network failure count; status code distribution; execution duration; latency summary statistics; and endpoint execution counts derived from the raw evidence.

Given finalized raw evidence contains `PAYLOAD_VALIDATION_ERROR` records without an explicit skipped indicator  
When aggregation computes request counts  
Then those records are counted according to their failed execution outcome and are not counted as skipped.

Given finalized raw evidence has no explicit skipped indicator  
When aggregation computes request counts  
Then skipped request count is `0` and is not inferred from failure categories, missing latency, missing HTTP status, or payload metadata.

Given Phase 4 processes Raw Result Schema v1 evidence  
When aggregation computes request counts  
Then `skipped_requests` is `0` for all aggregates because Raw Result Schema v1 has no explicit skipped indicator.

### AC-004: Endpoint-Level Aggregate Fields Are Produced

Given finalized raw evidence contains results for one or more endpoints  
When aggregation completes  
Then each represented endpoint has aggregate data containing endpoint execution count, success-rate numerator and denominator inputs, latency distribution data, timeout occurrence count, failure classification counts, and HTTP response distribution.

Given raw evidence contains endpoint data with raw URLs, query strings, credentials, PII, headers, payload fragments, or unsafe unbounded strings  
When endpoint-level aggregation completes or fails validation  
Then aggregate outputs, job metadata, lineage, errors, and logs contain only opaque or sanitized endpoint identifiers and do not expose the unsafe raw endpoint content.

### AC-005: Failure Classifications Are Grouped Without Inference

Given raw evidence contains execution-generated failure classification categories  
When aggregation computes failure classification counts  
Then the aggregate groups counts only by the categories present in the raw evidence and does not create inferred root-cause categories.

Given Raw Result Schema v1 evidence contains `PASS`, `ASSERTION_FAILURE`, `HTTP_ERROR`, `TIMEOUT`, `CONNECTION_ERROR`, `INVALID_RESPONSE`, `RUNNER_ERROR`, or `PAYLOAD_VALIDATION_ERROR` classifications  
When aggregation computes failure classification counts  
Then the aggregate groups those classifications using the execution-generated category names and does not rename, reinterpret, or infer alternate categories.

### AC-006: Missing or Unknown Failure Classifications Are Deterministic

Given raw evidence contains failed results with missing or unknown failure classification values  
When aggregation computes failure classification counts  
Then those values are handled through deterministic controlled bucket names defined by architecture and are not heuristically inferred, silently discarded, or assigned ad hoc labels.

### AC-007: Evidence Lineage Is Present on Every Aggregate

Given aggregation produces any aggregate record  
When the record is inspected  
Then it includes audit identifier, durable audit execution identifier, configuration version, aggregation version, aggregation job identifier, aggregation timestamp, and a bounded lineage manifest/reference that resolves to the exact source raw result references.

Given inline source raw result references would exceed bounded storage limits or expose sensitive raw content  
When aggregation records lineage  
Then lineage is preserved through a bounded immutable sanitized manifest/reference that resolves to the exact source raw result references without exposing sensitive raw fields.

Given an aggregate record references a lineage manifest/reference  
When the lineage is inspected by an authorized internal reviewer  
Then the manifest/reference is immutable, sanitized, versioned, part of the evidence chain, and enables deterministic reconstruction of the complete source evidence set.

### AC-008: Repeated Aggregation Is Idempotent

Given aggregation has already completed for a finalized audit with a specific aggregation version  
When aggregation is executed again for the same finalized audit and aggregation version  
Then the system produces no duplicate aggregate records and no counts are double-counted.

Given aggregation input contains duplicate source raw result references within the same aggregate set  
When aggregation validates input before writing aggregate records  
Then aggregation fails with a controlled sanitized validation outcome and creates no aggregate records for that attempt.

### AC-009: Retry After Failure Is Safe

Given an aggregation job fails before successful completion  
When the aggregation job is retried for the same finalized audit and aggregation version  
Then the retry either completes with exactly one immutable aggregate output set or fails without leaving double-counted aggregate data.

Given an aggregate set would exceed safe storage transaction or item-size limits and no chunking design has been explicitly approved  
When aggregation attempts to persist the aggregate set  
Then aggregation fails before creating aggregate records and records a controlled sanitized failure outcome.

### AC-010: Duplicate Trigger Events Are Safe

Given two aggregation trigger events are received for the same finalized audit and aggregation version  
When both events are processed  
Then only one aggregate output set is created and duplicate processing is recorded in an auditable controlled manner.

### AC-010A: Aggregation Is System-Managed With Restricted Administrative Recovery

Given an audit finalizes successfully and has valid execution evidence, valid `audit_execution_id`, and valid `config_version`  
When the system-managed lifecycle trigger runs  
Then aggregation is automatically initiated without requiring normal operator action.

Given a normal operator attempts to manually start aggregation or reaggregation  
When the request is evaluated  
Then the system does not expose or execute a normal operator aggregation action.

Given a privileged administrator initiates disaster recovery aggregation or reaggregation  
When the administrative action is processed  
Then the action is idempotent, fully auditable, and subject to the same eligibility, lineage, immutability, `audit_execution_id`, and `config_version` validation rules as automatic aggregation.

### AC-011: Aggregate Records Are Immutable and Versioned

Given an aggregate record already exists  
When aggregation logic changes or a new aggregation version is used later  
Then the system creates a new versioned aggregate record set and does not modify the existing aggregate record.

### AC-012: Aggregation Does Not Implement Future Phase Behavior

Given aggregate records have been created successfully  
When Phase 4 processing completes  
Then the system does not generate reliability conclusions, AI insights, reports, dashboards, customer recommendations, predictive analytics, release gates, CI/CD decisions, public/customer/operator invocation paths, or customer/operator workflows.

### AC-013: Analytical Consumption Metadata Is Available

Given aggregate records have been created  
When an internal future phase reads the aggregate dataset  
Then counts, distributions, lineage metadata, and version metadata are available without requiring recomputation from raw evidence for the fields in Phase 4 scope.

### AC-014: Sensitive Raw Content Is Excluded From Aggregation Artifacts

Given raw evidence contains headers, cookies, request bodies, response bodies, payloads, query parameters, raw URLs, tokens, secrets, credentials, PII, tenant-sensitive raw content, or payload fragments  
When aggregation completes, fails, handles a duplicate trigger, or records lineage  
Then aggregate records, job metadata, lineage, errors, and logs contain none of those sensitive raw fields and contain only approved sanitized aggregate fields.

### AC-015: Latency Precision and Rounding Are Canonical

Given finalized raw evidence contains valid numeric latency durations and invalid latency values  
When aggregation computes latency summaries  
Then only numeric durations greater than or equal to zero are included, invalid values are excluded, and `count`, `min`, `max`, `mean`, `median`, `p95`, and `p99` are emitted using deterministic median, nearest-rank p95 and p99, 3 decimal places, and half-up rounding.

## 10. Edge Cases

- Aggregation trigger arrives before finalization metadata is durably persisted.
- Aggregation trigger arrives multiple times for the same audit.
- Aggregation job is retried after partial progress.
- Finalized audit contains zero raw result records and must not produce aggregates.
- Finalized audit contains execution-failed state or no valid execution evidence and must not produce aggregates.
- Future raw evidence contains explicit skipped semantics, while Phase 4 / Raw Result Schema v1 still requires `skipped_requests = 0`.
- Finalized audit contains raw results with missing latency values.
- Finalized audit contains raw results with non-HTTP/network failures and no HTTP status code.
- Finalized audit contains duplicate raw result references or duplicate event deliveries from earlier lifecycle stages.
- Finalized audit contains `PAYLOAD_VALIDATION_ERROR` results but no explicit skipped indicator.
- Failure classification is missing, unknown, or not applicable.
- Endpoint identifier is missing, inconsistent, unsafe, unbounded, or contains raw URL/query/credential/PII content in one or more raw results.
- Configuration version referenced by finalization metadata is missing or invalid.
- Durable `audit_execution_id` is missing or invalid, even if `run_id` exists.
- Inline lineage references would exceed safe storage size or expose sensitive raw content.
- Aggregate output set would exceed safe atomic-write or transaction limits.
- Source raw evidence cannot be read at aggregation time.
- Aggregate storage write fails after the aggregation job has started.
- A future aggregation version is introduced for an audit that already has aggregates from an older version.

## 11. Constraints

- Raw evidence is the authoritative source of truth and must remain immutable.
- Aggregates are derived records only.
- Aggregation must be deterministic, idempotent, retry-safe, and auditable.
- Aggregation must run only after successful audit finalization.
- Successful audit finalization eligibility requires `lifecycle_state = COMPLETED`, `finalization.execution_count > 0`, `finalization.zero_execution = false`, and a successful finalization completion transition.
- Aggregation is a system-managed lifecycle stage automatically triggered after successful audit finalization and valid evidence availability.
- Manual aggregation/reaggregation is reserved exclusively for privileged administrative disaster recovery and must remain idempotent and fully auditable.
- Zero-execution and execution-failed audits must not produce aggregates.
- Aggregation must not infer reliability meaning, root cause, business impact, or release readiness.
- Aggregation must not expose unsanitized sensitive raw evidence content.
- Aggregate records must preserve lineage through a bounded lineage manifest/reference that enables deterministic reconstruction of source raw result references.
- Lineage must remain complete without creating unbounded item-size, denial-of-service, or data-exposure risk; the lineage manifest/reference is part of the immutable evidence chain.
- Missing or invalid `audit_execution_id` or `config_version` must block aggregate creation.
- `run_id` must not be reused as the durable `audit_execution_id`; `run_id` may remain only an implementation detail.
- `PAYLOAD_VALIDATION_ERROR` must be treated as an execution failure and must not be treated as skipped.
- For Phase 4 / Raw Result Schema v1, `skipped_requests` must be `0` for all aggregates.
- Duplicate source raw result references must not be silently double-counted or heuristically hidden.
- MVP aggregate persistence must fail before aggregate record creation when safe storage limits would be exceeded and chunking has not been explicitly designed.
- Latency percentile and decimal precision/rounding rules must be canonical for `agg_v1`: deterministic median, nearest-rank p95 and p99, 3 decimal places, and half-up rounding.
- Aggregate records must be immutable and versioned.
- Phase 4 must remain backend/internal and must not introduce operator/customer-facing experiences.

## 12. Dependencies

- Phase 1 raw execution evidence schema and raw result persistence.
- Phase 2 payload metadata, fingerprints, and sanitized raw result extensions where present.
- Phase 3 audit lifecycle, scheduled execution records, successful finalization metadata, valid execution evidence availability, and configuration version metadata.
- Phase 4 durable `audit_execution_id` generation/propagation for aggregate lineage; `run_id` is not the durable lineage identifier.
- Existing raw evidence storage availability and read access for finalized audits.
- Storage mechanism capable of preserving immutable, versioned aggregate records with lineage metadata.
- Sanitized logging and metadata conventions used elsewhere in the repository.
- Approved raw evidence field contract identifying which raw fields may be aggregated or referenced without exposing sensitive content.

## 13. Assumptions

- No unresolved product assumptions remain for the architecture-resolved Phase 4 decisions covered by this revision.

## 14. Open Questions

- None.

## 15. QA Expectations

QA validation for Phase 4 must include:

- Eligibility tests confirming only audits with `lifecycle_state = COMPLETED`, `finalization.execution_count > 0`, `finalization.zero_execution = false`, and a successful finalization completion transition are aggregated.
- Negative tests for incomplete, non-finalized, failed, cancelled, execution-failed, and zero-execution audits.
- Fixture-based aggregate correctness tests for audit-level counts and distributions.
- Fixture-based aggregate correctness tests for endpoint-level counts and distributions.
- Failure classification grouping tests confirming no inferred categories are created.
- Lineage tests confirming every aggregate includes all required lineage fields and uses `audit_execution_id` rather than `run_id` as the durable execution identifier.
- Lineage manifest/reference tests confirming bounded immutable evidence-chain linkage and deterministic reconstruction of source raw result references.
- Idempotency tests confirming repeat execution creates no duplicates and no double counting.
- Duplicate trigger tests confirming duplicate events are safely ignored or no-op handled.
- Retry tests confirming failed or partial attempts can be retried without corrupting aggregates.
- Immutability tests confirming raw evidence and existing aggregate records are not modified.
- Versioning tests confirming new aggregation versions create separate versioned outputs.
- Security/sanitization tests confirming aggregates and logs do not expose unsanitized sensitive content.
- Tests confirming missing or invalid `audit_execution_id` or `config_version` prevents aggregate creation, including a deterministic fail-closed validation error for missing `config_version`.
- Tests confirming `run_id` is not reused as durable `audit_execution_id`.
- Tests confirming `PAYLOAD_VALIDATION_ERROR` is counted as an execution failure and not counted as skipped.
- Tests confirming `skipped_requests = 0` for all Phase 4 / Raw Result Schema v1 aggregates.
- Tests confirming automatic system-managed aggregation after successful finalization and absence of normal operator aggregation actions.
- Tests confirming privileged administrative disaster recovery aggregation/reaggregation is idempotent, auditable, and does not bypass eligibility or lineage validation.
- Tests confirming duplicate source raw result references fail validation before aggregate record creation.
- Tests confirming oversized aggregate sets fail before writes unless chunking is explicitly designed.
- Tests confirming latency summaries use deterministic median, nearest-rank p95 and p99, 3 decimal places, and half-up rounding.

## 16. Scope Risks

- Later phases may attempt to pull reliability conclusions, scoring, or report semantics into Phase 4. These must remain out of scope.
- Operator experience requests may arise because aggregate data sounds report-ready. Operator/customer-facing experiences are explicitly excluded.
- Missing or invalid durable `audit_execution_id` or `config_version` can block lineage and reproducibility; Phase 4 must fail closed instead of substituting, reusing `run_id`, or inventing values.
- If raw evidence lacks required fields for one or more aggregates, Phase 4 must define deterministic handling rather than infer or backfill meaning.
- If raw evidence contains sensitive endpoint or payload content, aggregation must use only approved sanitized fields and must not leak raw content through errors, logs, metadata, or lineage.
- Re-aggregation for future versions could become mutable-update behavior unless versioned immutable output rules are enforced.
- Administrative disaster recovery triggers could expand into normal operator workflows unless access, auditability, and scope boundaries are enforced.
