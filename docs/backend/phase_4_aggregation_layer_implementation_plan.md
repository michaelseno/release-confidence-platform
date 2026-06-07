# Implementation Plan

## 1. Feature Overview
Implement the backend-only Phase 4 aggregation layer that transforms successfully finalized raw audit evidence into deterministic immutable aggregate records with bounded lineage.

## 2. Technical Scope
- Add internal aggregation event validation, handler, orchestrator, eligibility, identity resolution, raw evidence loading, deterministic aggregation, lineage manifest creation, and aggregate persistence.
- Enforce fail-closed guards for missing/invalid `audit_execution_id`, `config_version`, ineligible finalization, duplicate raw refs, oversized manifests, and unsupported versions.
- Keep raw S3 evidence read-only and avoid public/customer/operator aggregation APIs.

## 3. Source Inputs
- `docs/architecture/phase_4_aggregation_layer_technical_design.md`
- `docs/architecture/adr_phase_4_evidence_lineage_aggregation.md`
- `docs/product/phase_4_aggregation_layer_product_spec.md`
- `docs/qa/phase_4_aggregation_layer_test_plan.md`
- Existing Phase 1/3 backend storage, lifecycle, validation, and logging patterns.

## 4. API Contracts Affected
No public API contract changes.

Internal event `aggregate_audit` is added with body fields `event_type`, `schema_version`, `client_id`, `audit_id`, `aggregation_version`, and optional `aggregation_job_id`. Controlled outcomes include `COMPLETED`, `INELIGIBLE`, `DUPLICATE_COMPLETED`, `FAILED`, and `CONFLICT` with sanitized reason codes.

## 5. Data Models / Storage Affected
- Existing metadata table child items under `PK = CLIENT#{client_id}`.
- Adds Phase 4 child sort-key prefixes for `#AGGJOB#`, `#EXECUTION_ID`, `#LINEAGE#`, `#AGG#`, and endpoint/failure aggregate children.
- Reads existing run metadata `AUDIT#{audit_id}#RUN#{run_id}` and raw S3 result objects without mutation.

## 6. Files Expected to Change
- `src/release_confidence_platform/aggregation/*`
- `packages/aggregation/*`
- `apps/backend/handlers/aggregation_handler.py`
- `infra/serverless.yml`
- `tests/unit/aggregation/*`

## 7. Security / Authorization Considerations
- No public HTTP route is added.
- Event validation rejects unexpected fields and unsafe identifiers.
- Aggregates and manifests use strict allowlisted fields and sanitized endpoint identifiers.
- Logs and errors contain controlled reason codes and safe IDs only.
- Raw S3 writes are not used by aggregation.

## 8. Dependencies / Constraints
No new runtime dependencies. DynamoDB conditional writes and existing S3/DynamoDB wrappers are used. Serverless packaging must include the new internal handler/module.

## 9. Assumptions
- Existing Phase 3 finalization history entries with transition to `COMPLETED` and reason starting with `finalization_` are the successful completion transition metadata.
- `config_version` is valid when it passes the existing safe identifier pattern.
- Phase 4 assignment may create a child `#EXECUTION_ID` item using a generated opaque ID when canonical audit metadata lacks one; it does not mutate raw evidence.

## 10. Validation Plan
- Run targeted aggregation unit tests.
- Run existing Phase 3 lifecycle tests where safe.
- Run ruff on changed backend files if available.
