# ADR: Phase 4 Evidence Lineage, Audit Execution Identity, and Immutable Aggregation

## Status

Accepted

## Context

Phase 4 must transform finalized raw audit execution evidence into deterministic aggregate datasets for future internal analytical phases. Product requirements require raw evidence immutability, reproducibility, lineage on every aggregate, idempotent duplicate/retry handling, bounded sensitive-data exposure, and explicit exclusion of scoring, reports, dashboards, AI insights, CI/CD gates, and operator/customer-facing behavior.

Repository and review evidence established that:

- Successful finalization is currently indicated by `lifecycle_state = COMPLETED`, `finalization.execution_count > 0`, `finalization.zero_execution = false`, and finalization completion transition metadata.
- Existing raw evidence uses `run_id`, raw-result S3 keys, optional S3 version ids, `raw_result_version`, `endpoint_id`, timestamps, and derived `result_index` references.
- There is no existing durable `audit_execution_id` field.
- `config_version` exists on audit creation metadata but is not consistently present on finalization/raw results.
- Raw Result Schema v1 has no explicit skipped field.
- Raw result references have no persisted checksum/hash, and S3 version id may be unavailable.
- Endpoint ids are syntactically safe but not semantically guaranteed opaque.

## Decision

Phase 4 will introduce a durable first-class `audit_execution_id` and use it as the canonical execution identifier for raw evidence linkage, aggregate-set identity, reliability intelligence, reports, CI/CD integration, commercialization, support tooling, and future multi-tenancy. `run_id` remains an implementation detail for individual raw-result runs and is not the long-term primary lineage key.

Phase 4 will validate and persist mandatory `config_version` before processing. Missing or invalid `audit_execution_id` or `config_version` fails closed with a deterministic sanitized validation outcome and no aggregate creation. Phase 4 may persist/propagate these values in Phase 4-owned metadata, aggregation jobs, lineage manifests, and aggregate records, but must not mutate raw S3 evidence to retrofit fields.

Phase 4 aggregate records will be immutable child records in the existing metadata table under the client/audit partition, keyed by execution identity, configuration version, aggregation version, and aggregate scope. The initial aggregation version is `agg_v1`. Future semantic changes must write a new aggregation version rather than updating existing records.

Phase 4 will not embed unbounded raw reference arrays on aggregate records. Every aggregate will contain bounded lineage metadata plus a `lineage_manifest_ref`, `source_ref_count`, and manifest hash. The immutable sanitized lineage manifests resolve deterministically to exact canonical raw result references. Audit-level aggregates reference audit-scoped lineage. Endpoint-level aggregates must reference endpoint-scoped manifest records or manifest entries whose source set is exactly the canonical raw result references used for that endpoint aggregate. If the manifest or aggregate set would exceed safe MVP item/transaction limits, aggregation fails before manifest/aggregate/completion-marker writes unless a separately reviewed chunking/S3 manifest design is approved.

Aggregation eligibility is limited to canonical audit metadata with `lifecycle_state = COMPLETED`, `finalization.execution_count > 0`, `finalization.zero_execution = false`, and successful finalization completion transition. A separate evidence integrity validation gate must run before aggregate computation, lineage manifest writes, aggregate writes, or aggregate-set completion writes. The gate must reconcile expected finalization execution count with persisted completed run count and loaded raw evidence count; validate no duplicate raw source references; validate resolved `audit_execution_id` and `config_version`; and validate lineage completeness. Non-finalized, in-progress, cancelled, failed, execution-failed, zero-execution, metadata-inconsistent, count-mismatched, missing-evidence, duplicate-reference, or lineage-incomplete audits create controlled ineligible/failure job outcomes and no aggregate records, lineage manifests, or aggregate-set completion marker.

For `agg_v1`, skipped counts are derived only from explicit skipped indicators. Raw Result Schema v1 has none, so `skipped_requests = 0`; `PAYLOAD_VALIDATION_ERROR` remains an execution failure. Duplicate raw result references fail deterministic validation before aggregate creation.

Aggregation is a system-managed lifecycle stage automatically triggered after successful finalization. Phase 3 finalization must persist a durable aggregation job intent before asynchronous invocation so a finalized audit cannot silently lack aggregation lifecycle evidence if invocation fails. Normal operator/customer invocation is not provided. Privileged administrative disaster-recovery invocation/reaggregation is deferred from Phase 4 and requires a separate reviewed operational contract before implementation.

Phase 4 will persist a canonical immutable `AggregateSetCompletion` marker for each completed aggregate set. The audit aggregate is the audit-level metrics record, but the aggregate-set completion marker is the authoritative downstream-consumable proof that all required manifests and aggregate records were written and validated.

Aggregation job metadata will durably distinguish `EVIDENCE_PRODUCING` failures from `EVIDENCE_TRANSFORMING` failures. Evidence-producing failures include missing raw evidence, count mismatch, incomplete execution, duplicate source references, and lineage corruption; they block aggregation and require a new audit execution or approved upstream evidence repair. Evidence-transforming failures include timeout, storage conflict, worker failure, trigger invocation failure after intent persistence, and transient infrastructure issues; they may be retried deterministically without rerunning the audit when no complete aggregate set exists.

## Alternatives Considered

### Use `run_id` as the long-term execution lineage key

Rejected. `run_id` identifies individual raw-result runs and is not durable enough as the canonical cross-phase execution identity for aggregates, reliability intelligence, reports, CI/CD, support, commercialization, and future multi-tenancy.

### Substitute `audit_id` when `audit_execution_id` is missing

Rejected. Product requirements prohibit silent substitution unless explicitly approved. Phase 4 instead introduces a first-class durable execution identity and fails closed if it cannot be resolved or assigned safely.

### Embed all raw result references inline on every aggregate

Rejected. Inline arrays risk DynamoDB item-size limits, denial-of-service behavior, repeated storage bloat, and accidental sensitive-data exposure. Bounded immutable manifests preserve complete traceability without unbounded aggregate records.

### Chunk aggregate persistence in MVP

Rejected for current scope. Chunking requires a complete protocol for manifest chunks, aggregate-set completion markers, partial retry reconciliation, and QA validation. MVP behavior is fail-before-write when limits would be exceeded.

### Treat `PAYLOAD_VALIDATION_ERROR` as skipped

Rejected. Raw Result Schema v1 has no explicit skipped indicator; product requirements require failed execution outcomes to remain failed unless a distinct skipped indicator exists.

### Allow normal manual/operator aggregation

Rejected. Phase 4 is a system-managed lifecycle stage. Normal manual/operator aggregation remains excluded. Privileged disaster recovery is deferred from Phase 4 rather than partially implemented without a complete operational/security contract.

### Use only an audit-wide lineage manifest for endpoint aggregates

Rejected for Phase 4 remediation. Although audit-wide lineage can support broad reconstructability, it does not give each endpoint aggregate a direct exact source set. Endpoint-scoped manifest records or entries better satisfy the requirement that every aggregate resolve to the exact raw references used to produce that aggregate.

### Treat the audit aggregate as the only canonical completion proof

Rejected. The audit aggregate contains metrics, but downstream phases need an unambiguous immutable marker proving the aggregate set is complete. A separate `AggregateSetCompletion` marker avoids accidental consumption of partial child records.

### Add a new durable queue/DLQ for trigger recovery in Phase 4

Rejected for current remediation. A durable queue/DLQ remains viable later, but persisting a job intent before async invocation aligns with the existing metadata-table job orchestration pattern and avoids adding new infrastructure during a blocked HITL remediation.

## Consequences

Benefits:

- Establishes a stable execution identity for Phase 4 and downstream phases.
- Preserves raw evidence as the source of truth while enabling complete aggregate lineage.
- Avoids unbounded aggregate item size and sensitive raw content exposure through lineage manifests.
- Makes duplicate triggers and retries safe through deterministic aggregate-set identity and conditional writes.
- Prevents partial-evidence aggregation through an explicit fail-closed integrity gate.
- Gives downstream phases a canonical aggregate-set completion proof.
- Preserves exact endpoint-level lineage without relying on broad audit-wide inference.
- Keeps Phase 4 backend/internal and prevents premature reporting/scoring/operator behavior.

Costs and risks:

- Requires a new durable `audit_execution_id` propagation/persistence path.
- Requires strict fail-closed handling for missing `config_version`, which may expose upstream metadata gaps.
- Large audits may fail aggregation until a chunked or S3 manifest design is separately approved.
- Endpoint-scoped manifests increase write count/transaction pressure and may expose MVP size limits sooner.
- Deferred administrative DR means recovery outside automatic intent retry/reconciliation requires governance/engineering intervention until a separate DR workflow is approved.
- If S3 versioning is unavailable, lineage records key/run/index and explicitly flags object-version lineage as unavailable rather than proving object-version identity.
- IAM/resource policies must be precise enough to allow Phase 4 writes without broad raw evidence mutation permissions.

## Traceability

- Product spec: `docs/product/phase_4_aggregation_layer_product_spec.md`
- Technical design: `docs/architecture/phase_4_aggregation_layer_technical_design.md`
- QA plan: `docs/qa/phase_4_aggregation_layer_test_plan.md`
- Phase 1 raw evidence design: `docs/architecture/phase_1_core_engine_foundation_technical_design.md`
- Phase 3 lifecycle design: `docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md`
- Phase 3 finalization cleanup ADR: `docs/architecture/adr_phase_3_finalization_completion_cleanup.md`
