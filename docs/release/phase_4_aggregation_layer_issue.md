# GitHub Issue

## 1. Feature Name

Phase 4 Aggregation Layer

## 2. Problem Summary

The Release Confidence Platform can capture raw audit execution evidence and finalize audit windows, but later phases need deterministic, queryable, reproducible aggregate datasets without repeatedly scanning raw evidence or duplicating summarization logic.

Phase 4 introduces a backend-only aggregation layer that reads successfully finalized raw execution evidence and writes immutable, versioned, lineage-preserving aggregate records for future internal analytical consumption. Raw execution evidence remains the source of truth. Aggregates are derived summaries only and must not mutate, delete, replace, compact, reinterpret, or supersede raw evidence.

## 3. Linked Planning Documents

- Product Spec: `docs/product/phase_4_aggregation_layer_product_spec.md`
- Technical Design: `docs/architecture/phase_4_aggregation_layer_technical_design.md`
- ADR: `docs/architecture/adr_phase_4_evidence_lineage_aggregation.md`
- QA Test Plan: `docs/qa/phase_4_aggregation_layer_test_plan.md`
- UI/UX Spec: Not applicable. Phase 4 is backend-only; no frontend, operator UI, dashboard, report, or customer-facing experience is in scope.

## 4. Scope Summary

### In scope

- Internal system-managed aggregation trigger after successful Phase 3 finalization.
- Eligibility validation requiring `lifecycle_state = COMPLETED`, `finalization.execution_count > 0`, `finalization.zero_execution = false`, successful finalization completion transition metadata, valid execution evidence, durable `audit_execution_id`, and mandatory `config_version`.
- Dedicated durable first-class `audit_execution_id` as the canonical execution lineage key for Phase 4 and later phases.
- Mandatory `config_version` validation before aggregation processing; missing or invalid values fail closed before aggregate creation.
- Audit-level aggregate records for counts, status distributions, execution duration, latency summary statistics, and endpoint execution counts.
- Endpoint-level aggregate records for sanitized endpoint identifiers, execution counts, success-rate inputs, latency distributions, timeout occurrences, failure classification counts, and HTTP response distributions.
- Failure classification aggregation from execution-generated Raw Result Schema v1 categories only, with deterministic controlled buckets for missing/unknown classifications.
- Bounded immutable lineage manifest/reference that resolves deterministically to exact source raw result references without embedding unbounded raw references in aggregate records.
- Immutable, versioned aggregate records using `aggregation_version = agg_v1` for the initial implementation.
- Idempotency, duplicate-trigger handling, duplicate raw reference validation, retry safety, and conditional write behavior to prevent duplicate records or double counting.
- Fail-before-write behavior for duplicate source references, missing lineage fields, invalid eligibility, and aggregate/manifest size limits unless a separately reviewed persistence design is approved.
- Strict allowed-field storage/logging contract for aggregate records, job metadata, lineage, errors, and logs.
- Implementation evidence for architecture/security review concerns, including IAM least privilege, internal-only invocation, sanitization, S3 versioning residual risk handling, and no raw key/sensitive raw content logging.

### Out of scope

- Frontend work, dashboards, reports, report exports, visualizations, or customer-facing UI.
- Public/customer-facing aggregation API or normal operator/customer aggregation action.
- Normal manual aggregation or reaggregation workflow; any manual path is limited to privileged administrative disaster recovery and must remain auditable and idempotent.
- Reliability conclusions, scoring, release confidence scoring, release gates, CI/CD pass/fail decisions, AI insights, recommendations, predictive analytics, trend interpretation, anomaly explanation, or root-cause inference.
- Phase 5 Reliability Intelligence, Phase 6 Reporting, or Phase 7 CI/CD Integration implementation or triggering.
- Raw evidence mutation, deletion, replacement, compaction, checksum backfill, reclassification, or retrofitting raw S3 objects with `audit_execution_id` or `config_version`.
- Chunked aggregate persistence protocol unless separately designed, reviewed, and QA-planned.
- S3 object-versioning enablement or retroactive version id guarantees.

## 5. Implementation Notes

### Frontend expectations

- No frontend implementation is expected.
- No customer-facing dashboard, report, visualization, UI state, public API integration, or operator aggregation action is required.
- Phase 4 aggregate datasets are internal analytical inputs only for later phases.

### Backend expectations

- Implement an internal `aggregate_audit` handler/event contract only; reject unsafe event shapes and unsupported fields.
- Allow normal aggregation invocation only from approved internal lifecycle/system principals after successful finalization.
- Resolve or assign a durable first-class `audit_execution_id` before raw evidence processing through approved Phase 4 metadata, not by mutating raw S3 evidence.
- Never substitute `run_id`, `audit_id`, or any other identifier as the canonical lineage key when `audit_execution_id` is missing or invalid.
- Validate mandatory `config_version` before processing; do not invent, default, infer, or silently backfill it.
- Enforce eligibility only after successful finalization with nonzero execution evidence; zero-execution, execution-failed, incomplete, cancelled, failed, in-progress, metadata-inconsistent, or failed-finalization audits are ineligible and create no aggregates.
- Read raw evidence through read-only repository/S3 paths and preserve raw evidence immutability.
- Build canonical allowed-field raw input DTOs and sanitized source references before aggregation.
- Reject duplicate raw result references before lineage or aggregate writes; do not silently dedupe or double-count.
- Use deterministic sorting, counting, latency summary, percentile, and rounding rules for `agg_v1`.
- Persist immutable job metadata, lineage manifests/references, and aggregate records with conditional writes and one aggregate set per `{client_id, audit_id, audit_execution_id, config_version, aggregation_version}`.
- Use bounded immutable lineage manifests/references with manifest hash/source count to preserve complete reconstructable lineage without oversized aggregate records.
- Fail before aggregate/manifest creation when safe item/transaction limits would be exceeded unless a separately approved design exists.
- Persist only approved sanitized aggregate fields, controlled reason codes, counts, distributions, timestamps, versions, and bounded source references. Do not persist or log raw headers, cookies, request bodies, response bodies, payloads, query parameters, raw URLs, tokens, secrets, credentials, PII, tenant-sensitive raw content, payload fragments, or unsafe raw S3 keys.
- Explicitly record S3 object-version lineage unavailability when version ids are absent rather than mutating raw evidence or claiming stronger lineage guarantees.
- Preserve Phase 3 lifecycle behavior and do not transition audits to analysis/reporting states or trigger Phase 5/6/7.

### Dependencies or blockers

- Depends on Phase 1 raw execution evidence schema and raw result persistence.
- Depends on Phase 3 audit lifecycle/finalization metadata and valid finalized raw execution evidence.
- Requires durable `audit_execution_id` propagation or approved Phase 4 conditional identity assignment before raw evidence processing.
- Requires reliable `config_version` availability from canonical audit/finalization metadata.
- Requires storage support for immutable aggregate/job/lineage child records under existing client/audit partitions.
- Requires IAM/resource policy evidence for internal-only invocation and least-privilege raw evidence read/aggregate write access.
- Governance reviews are Approved with Concerns and no blockers; implementation must carry concerns forward as evidence requirements.

## 6. QA Section

### Planned test coverage

- Eligibility tests for successful finalization boundary, non-finalized states, failed/cancelled/execution-failed audits, zero-execution audits, missing `audit_execution_id`, and missing `config_version`.
- Unit tests for event validation, identity/config guards, count semantics, skipped/failure-classification behavior, deterministic sorting, latency statistics, endpoint identifier sanitization, lineage manifest construction, duplicate raw reference validation, and aggregation version validation.
- Integration tests for internal handler/orchestrator behavior with mocked or local DynamoDB/S3 boundaries, aggregation job persistence, manifest reconstruction, immutable aggregate writes, retries, duplicates, conflicts, and concurrency.
- Security tests for strict allowed-field storage/logging, endpoint ID safety, IAM/internal trigger controls, privileged DR controls if implemented, and absence of raw evidence mutation permissions.
- Regression tests for Phase 1 raw evidence assumptions and Phase 3 scheduling/finalization/lifecycle behavior, including canonical audit-list filtering that must ignore aggregate child records.
- Static/source inspection for no public/customer/operator aggregation path, no future-phase behavior, no raw evidence mutation, sanitized logging, and no raw key or sensitive raw content logging.

### Acceptance criteria mapping

- Successful finalization eligibility and zero-execution exclusion: AC-001 and QA scenarios P4-AGG-001 through P4-AGG-006, P4-AGG-039.
- Raw evidence immutability: AC-002 and P4-AGG-007 through P4-AGG-008.
- Audit-level aggregate correctness: AC-003 and P4-AGG-009 through P4-AGG-012.
- Endpoint-level aggregate correctness and endpoint safety: AC-004 and P4-AGG-013, P4-AGG-031.
- Failure classification grouping without inference: AC-005, AC-006 and P4-AGG-014 through P4-AGG-015.
- Evidence lineage, durable `audit_execution_id`, mandatory `config_version`, and bounded manifest/reference: AC-007 and P4-AGG-016 through P4-AGG-021.
- Idempotency, duplicate prevention, retry safety, and duplicate trigger behavior: AC-008 through AC-010 and P4-AGG-022 through P4-AGG-029.
- System-managed internal-only aggregation and restricted administrative recovery: AC-010A and P4-AGG-037 through P4-AGG-038.
- Immutable/versioned aggregate records: AC-011 and P4-AGG-032 through P4-AGG-033.
- No future-phase/customer/operator behavior: AC-012 and P4-AGG-034.
- Analytical consumption readiness: AC-013 and P4-AGG-035.
- Sensitive raw content exclusion: AC-014 and P4-AGG-036.
- Canonical latency precision/rounding: AC-015 and P4-AGG-011.

### Key edge cases

- Aggregation trigger arrives before finalization metadata is durably persisted.
- `COMPLETED` audit lacks durable `audit_execution_id`; approved assignment may occur before processing, otherwise fail closed.
- `run_id` or `audit_id` exists but must not be substituted as canonical lineage identity.
- `config_version` is missing, null, empty, unsafe, or inconsistent.
- `finalization.execution_count = 0`, invalid, missing, or execution-failed.
- Raw Result Schema v1 has no explicit skipped indicator; `skipped_requests = 0` and `PAYLOAD_VALIDATION_ERROR` remains failed.
- Raw results contain duplicate stable source references.
- Repeated, concurrent, or duplicate aggregation trigger events occur.
- Raw evidence cannot be read or aggregate storage write fails after job start.
- Aggregate set or lineage manifest would exceed safe storage limits.
- S3 version id is unavailable for source objects.
- Endpoint identifier is missing, unsafe, unbounded, or contains raw URL/query/credential/PII/header/payload content.
- Logs, errors, manifests, job metadata, or aggregate outputs could leak raw headers, cookies, bodies, payloads, query strings, tokens, secrets, credentials, PII, tenant-sensitive content, raw S3 keys, or endpoint raw content.
- Privileged DR trigger, if implemented, risks becoming a normal operator workflow.

### Test types expected

- Unit: Yes.
- Integration: Yes, with mocked/local storage and internal event/orchestrator boundaries.
- Contract/internal event tests: Yes.
- Security/sanitization tests: Yes.
- IAM/resource policy review: Yes where infrastructure/policies are included.
- Regression tests: Yes, focused on Phase 1 raw evidence and Phase 3 lifecycle/finalization behavior.
- Concurrency/reliability tests: Yes, for duplicate triggers, retries, conflicts, and idempotency.
- Fixture-based deterministic tests: Yes, with manual oracles for aggregate counts, latency, endpoint distributions, failure buckets, manifests, and forbidden-string sanitization.
- UI tests: No, frontend is out of scope.

## 7. Risks / Open Questions

- Architecture review is Approved with Concerns; implementation must provide evidence that the concerns were preserved and resolved or accepted without weakening lineage, immutability, or scope boundaries.
- Security review is Approved with Concerns; implementation must provide evidence for IAM least privilege, internal-only invocation, endpoint/input sanitization, sanitized errors/logs, no raw key logging, no sensitive raw content exposure, and residual S3 versioning risk handling.
- Durable `audit_execution_id` does not currently exist in earlier raw evidence; unsafe assignment or substitution would break lineage guarantees and must fail closed.
- Missing or inconsistent `config_version` may expose upstream metadata gaps and block aggregation.
- Large lineage or aggregate sets may fail under MVP fail-before-write behavior until a separately reviewed chunking/S3 manifest protocol exists.
- S3 version id may be unavailable; lineage must explicitly represent this limitation rather than claiming object-version immutability.
- Administrative disaster recovery aggregation could expand into normal operator/customer behavior unless access, auditing, and scope boundaries are enforced.
- Future phases may attempt to introduce scoring/reporting/recommendation semantics early; Phase 4 must remain aggregation-only.
- Open questions: None blocking at planning time; implementation-time evidence requirements remain.

## 8. Definition of Done

- Product spec, technical design, ADR, QA test plan, and release issue artifact are present and aligned.
- Backend implementation introduces internal-only lifecycle-triggered aggregation with no public/customer/operator normal aggregation action.
- Aggregation runs only for successfully finalized, nonzero-execution audits with valid evidence, durable `audit_execution_id`, and mandatory `config_version`.
- Missing/invalid `audit_execution_id` or `config_version` fails closed before raw evidence processing or aggregate creation; no `run_id`/`audit_id` substitution occurs.
- Raw evidence remains immutable and is read-only throughout success and failure paths.
- Audit-level and endpoint-level aggregate records are deterministic, versioned, immutable, and reproduce correctly for `agg_v1`.
- Every aggregate includes complete lineage fields and a bounded immutable sanitized lineage manifest/reference that resolves to exact source raw result references.
- Duplicate raw references fail before writes; duplicate triggers, retries, and concurrent attempts create no duplicate records or double counting.
- Oversized aggregate/manifest cases fail before aggregate creation unless a separately reviewed design is approved.
- Aggregate records, job metadata, lineage, errors, and logs exclude sensitive raw content and raw key leakage.
- IAM/internal trigger/admin DR controls are evidenced where applicable.
- Architecture and security review concerns are carried forward in implementation evidence and QA validation.
- Phase 4 does not implement frontend behavior, dashboards, reports, scoring, AI insights, reliability conclusions, release gates, CI/CD decisions, or Phase 5/6/7 triggers.
- Required unit, integration, contract, security, concurrency, and regression tests pass with documented QA evidence.
- QA sign-off is granted only after critical acceptance criteria pass and no blockers, major regressions, unresolved critical security findings, or unclassified flaky failures remain.
