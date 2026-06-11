# Implementation Plan

## 1. Feature Overview
Implement the backend-only Phase 4 aggregation layer that transforms successfully finalized raw audit evidence into deterministic immutable aggregate records with bounded lineage.

## 2. Technical Scope
- Add internal aggregation event validation, handler, orchestrator, eligibility, identity resolution, raw evidence loading, deterministic aggregation, lineage manifest creation, and aggregate persistence.
- Remediate HITL compliance blockers only: evidence integrity validation gate, durable failure taxonomy, endpoint-scoped lineage, controlled duplicate/conflict handling, durable trigger intent, and aggregate-set completion marker.
- Enforce fail-closed guards for missing/unresolved `audit_execution_id`, missing `config_version`, ineligible finalization, execution-count mismatches, partial/missing raw evidence, duplicate raw refs, lineage incompleteness, unsafe raw-result S3 keys, oversized manifests/transactions, and unsupported versions.
- Keep raw S3 evidence read-only for aggregation and avoid public/customer/operator aggregation APIs.

## 3. Source Inputs
- `docs/architecture/phase_4_aggregation_layer_technical_design.md`
- `docs/architecture/adr_phase_4_evidence_lineage_aggregation.md`
- `docs/product/phase_4_aggregation_layer_product_spec.md`
- `docs/qa/phase_4_aggregation_layer_test_plan.md`
- `docs/qa/phase_4_aggregation_layer_qa_report.md`
- `docs/review/phase_4_architecture_compliance_review.md`
- `docs/bugs/phase_4_aggregation_compliance_blockers.md`
- Existing Phase 1/3 backend storage, lifecycle, validation, and logging patterns.

## 4. API Contracts Affected
No public API contract changes.

Internal event `aggregate_audit` uses body fields `event_type`, `schema_version`, `client_id`, `audit_id`, `aggregation_version`, and optional `aggregation_job_id`. Controlled outcomes include `COMPLETED`, `INELIGIBLE`, `DUPLICATE_COMPLETED`, `FAILED`, and `CONFLICT` with sanitized reason codes and durable failure category where applicable.

Successful Phase 3 finalization now invokes this internal event asynchronously through the configured aggregation Lambda only; no HTTP/customer/operator trigger is added.

## 5. Data Models / Storage Affected
- Existing metadata table child items under `PK = CLIENT#{client_id}`.
- Adds/uses Phase 4 child sort-key prefixes for `#AGGJOB#`, `#EXECUTION_ID`, `#LINEAGE#`, `#AGG#`, endpoint/failure aggregate children, and aggregate-set completion `#SET` markers.
- Reads existing run metadata `AUDIT#{audit_id}#RUN#{run_id}` and raw S3 result objects without mutation.
- Uses one DynamoDB transaction for each complete audit manifest, endpoint manifests, aggregate records, and aggregate-set completion marker when within approved item/count/transaction limits; oversized sets fail before manifest/aggregate/completion writes.

## 6. Files Expected to Change
- `src/release_confidence_platform/aggregation/*`
- `apps/backend/handlers/audit_finalization_handler.py`
- `apps/backend/handlers/aggregation_handler.py`
- `infra/serverless.yml`
- `infra/resources/phase4-aggregation-iam.yml`
- `tests/unit/aggregation/*`
- `tests/integration/test_phase3_cancellation_finalization.py`

## 7. Security / Authorization Considerations
- No public HTTP route is added.
- Event validation rejects unexpected fields and unsafe identifiers.
- Aggregates and manifests use strict allowlisted fields and sanitized endpoint identifiers.
- `raw_result_s3_key` must match the approved `raw-results/{client_id}/{audit_id}/...` safe pattern and contain no sensitive markers before S3 read or lineage persistence.
- Logs and errors contain controlled reason codes and safe IDs only.
- Evidence-producing failures are durably separated from evidence-transforming failures so retries do not mask incomplete/corrupt evidence.
- Aggregation uses a dedicated Serverless role with raw-results read-only S3 permissions; finalization uses a dedicated role with invoke permission for the aggregation Lambda.

## 8. Dependencies / Constraints
No new runtime dependencies. DynamoDB conditional transaction writes and existing S3/DynamoDB/Lambda wrappers are used. Serverless packaging must include the internal handler/module.

## 9. Assumptions
- Existing Phase 3 finalization history entries with transition to `COMPLETED` and reason starting with `finalization_` are the successful completion transition metadata.
- `config_version` is valid when it passes the existing safe identifier pattern.
- Phase 4 assignment may create a child `#EXECUTION_ID` item using a generated opaque ID when canonical audit metadata lacks one and the controlled assignment path succeeds; if unresolved, aggregation fails closed.
- Privileged administrative DR aggregation/reaggregation remains deferred; no normal/manual operator trigger is added.

## 10. Validation Plan
- Run targeted aggregation unit tests covering integrity gate, duplicate/conflict handling, endpoint lineage, completion marker, and failure taxonomy.
- Run Phase 3 finalization integration tests covering durable trigger intent and invocation failure recovery metadata.
- Run ruff on changed backend files and tests.
