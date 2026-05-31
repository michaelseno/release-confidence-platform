# Technical Design

## 1. Feature Overview

This note resolves the HITL blocker reported on branch `bugfix/scheduled_execution_orchestration_rca` where `rcp audit create --force` is rejected for an existing audit in `FINALIZING`, and `rcp audit list` shows duplicate/minimal audit entries caused by child DynamoDB records being included in audit discovery.

The scope is backend/operator CLI corrective work only. It does not introduce production code in this document, a branch, a commit, or a PR.

## 2. Product Requirements Summary

Traceable requirements:

- Phase 3 product spec requires `FINALIZING` as the audit-window finalization boundary and states that Phase 3 finalization records metadata and must not auto-transition to `ANALYZING`, `REPORTING`, or `COMPLETED`.
- Phase 3 product spec keeps analytics, reporting, scoring, and completion workflows out of scope.
- Zero-execution finalization must transition `FINALIZING -> FAILED`.
- Operator discovery must list audit metadata for a client without loading raw evidence or run metadata.
- Force recreate is currently guarded to `DRAFT`/`FAILED` audit metadata and must not mutate live/in-progress/finalized audit records without a product-approved recovery workflow.

## 3. Requirement-to-Architecture Mapping

| Requirement / Evidence | Architecture Decision |
| --- | --- |
| Phase 3 stops at finalization boundary | Keep successful nonzero-execution audits in `FINALIZING`; do not auto-complete in the current product phase. |
| Zero-execution finalization must fail | Preserve `FINALIZING -> FAILED` behavior when `execution_count == 0`. |
| Operator discovery excludes run metadata | `audit list` must return only canonical audit metadata rows with `SK == AUDIT#<audit_id>` shape and exclude `#RUN#`, `#OCCURRENCE#`, schedules, lifecycle child rows, and future child suffixes. |
| Force recreate is a destructive replacement path | Keep force recreate eligibility restricted to `DRAFT` and `FAILED`; improve CLI guidance instead of changing recovery semantics. |

## 4. Technical Scope

### Current Technical Scope

- Clarify finalization lifecycle semantics for the HITL blocker.
- Fix `audit list` filtering to return canonical audit metadata only.
- Improve `FORCE_RECREATE_BLOCKED` operator guidance.
- Add/update tests that lock the intended behavior.

### Out of Scope

- Automatic `FINALIZING -> ANALYZING -> REPORTING -> COMPLETED` progression.
- Direct `FINALIZING -> COMPLETED` shortcut.
- Admin reset/reopen/recreate workflow for non-`DRAFT`/`FAILED` audits.
- Manual DynamoDB mutation or schedule deletion as part of this design.

### Future Technical Considerations

- A Phase 4 analysis/reporting worker may own `FINALIZING -> ANALYZING -> REPORTING -> COMPLETED`.
- A separate product-approved admin repair command may safely reset stuck dev/test audits after schedule and in-flight execution checks.

## 5. Architecture Overview

The current Phase 3 lifecycle model treats `FINALIZING` as the durable boundary after the audit window closes and finalization metadata is recorded. For nonzero executions, this is an externally visible stable state until a later analytics/reporting phase is implemented. For zero executions, `FINALIZING` is transient because Phase 3 explicitly owns the failure path to `FAILED`.

The HITL failure is therefore not a signal to force direct completion. The direct blocker is that the operator attempted destructive recreation of a record in a non-eligible lifecycle state, while CLI output did not explain safe recovery. The duplicate `audit list` rows are a separate discovery bug caused by querying a shared sort-key namespace and shaping child records as audits.

## 6. System Components

### AuditFinalizationHandler

- Preserve current nonzero-execution success behavior: transition eligible `SCHEDULED`/`RUNNING` audits to `FINALIZING`, record finalization metadata, return `lifecycle_state = FINALIZING`.
- Preserve zero-execution behavior: transition to `FINALIZING`, record finalization metadata, then transition to `FAILED`.
- Treat repeat delivery for `FINALIZING` or terminal states as idempotent skip.

### AuditMetadataRepository / DiscoveryListService

- The repository or service must filter query results to canonical audit metadata rows only.
- Canonical audit metadata row shape: `PK = CLIENT#<client_id>`, `SK = AUDIT#<audit_id>` with no additional `#` suffix after the audit ID.
- Do not rely on excluding known suffixes only; future child records must not leak into discovery.

### Operator CLI Renderer

- Add dedicated `FORCE_RECREATE_BLOCKED` next-step guidance.
- Guidance should state that `--force` is allowed only for `DRAFT`/`FAILED`, recommend `rcp audit list --client-id <client_id> --stage <stage> --output json`, recommend a fresh audit ID/config bundle as safest recovery, and warn against manual lifecycle mutation except controlled dev/test remediation.

## 7. Data Models

No schema migration is required.

### Audit Metadata Item

#### Purpose

Canonical audit summary and lifecycle source for discovery and creation guards.

#### Primary Key

- `PK = CLIENT#<client_id>`
- `SK = AUDIT#<audit_id>`

#### Fields

- Existing lifecycle/config fields only; no new required fields.

#### Ownership Model

Scoped by `client_id` partition key.

#### Lifecycle

Successful Phase 3 finalization with executions remains `FINALIZING`. Zero-execution finalization becomes `FAILED`. Force recreate may replace metadata only from `DRAFT` or `FAILED`.

### Child Records Excluded From Audit List

- Run metadata: `SK = AUDIT#<audit_id>#RUN#<run_id>`
- Occurrence claims: `SK = AUDIT#<audit_id>#OCCURRENCE#<schedule_occurrence_id>`
- Any future audit child records with additional suffixes after `AUDIT#<audit_id>`

## 8. API Contracts

No HTTP API changes.

CLI behavior changes:

- `rcp audit list --client-id ...` returns only canonical audit metadata rows.
- `rcp audit create --force` remains rejected for `FINALIZING`, `SCHEDULED`, `RUNNING`, `ANALYZING`, `REPORTING`, `COMPLETED`, and `CANCELLED`.
- `FORCE_RECREATE_BLOCKED` text output receives actionable next-step guidance.

## 9. Frontend Impact

None.

## 10. Backend Logic

### Responsibilities

- Finalization handler enforces current Phase 3 lifecycle boundary.
- Repository/discovery service enforces canonical-row filtering.
- CLI renderer explains force-recreate lifecycle preconditions.

### Validation Flow

- Validate identifiers through existing validators.
- For audit list, include an item only when `SK` is exactly two segments: `AUDIT` and `<audit_id>`, and the derived/persisted `audit_id` is present and valid.

### Business Rules

- `FINALIZING` is stable for successful Phase 3 finalization.
- `--force` must not override audits outside `DRAFT`/`FAILED`.
- Discovery must not expose run/raw evidence records as audits.

### Persistence Flow

- No new writes for list/guidance changes.
- Existing finalization writes remain unchanged.

### Error Handling

- `FORCE_RECREATE_BLOCKED` remains the error code for force-ineligible lifecycle states.
- The renderer supplies lifecycle-specific next steps.

## 11. File Structure

Expected implementation files:

- `src/release_confidence_platform/storage/audit_metadata_client.py`
- `src/release_confidence_platform/operator_cli/discovery_service.py`
- `src/release_confidence_platform/operator_cli/result.py`
- Relevant tests under `tests/unit/` and `tests/integration/`

## 12. Security

- Keep destructive force recreate restricted to known safe states.
- Do not expose raw run evidence, payloads, secrets, or child run metadata in `audit list`.
- Do not recommend manual metadata mutation as a normal operator path.

## 13. Reliability

- Canonical-row filtering must be future-proof against new child suffixes.
- If filtering is done after DynamoDB query, implementation must consider pagination: a page filled with child rows must not incorrectly imply no canonical audits if additional pages remain and the requested limit has not been satisfied.
- Idempotent finalization skip behavior for `FINALIZING`/terminal states remains valid.

## 14. Dependencies

No new runtime dependencies.

## 15. Assumptions

- Phase 3 product requirements remain authoritative for finalization boundary semantics.
- The active HITL audit can be recovered operationally by using a fresh audit ID/config bundle unless a separate repair workflow is approved.

## 16. Risks / Open Questions

- Product/user confirmation is required before implementing any behavior that auto-transitions successful audits beyond `FINALIZING` or expands force-recreate eligibility.
- Live recovery of the specific dev audit ID may require read-only AWS checks for schedules, finalization metadata, and in-flight executions before any manual repair.

## 17. Implementation Notes

- Do not change `TRANSITIONS` to allow `FINALIZING -> COMPLETED` as a shortcut; that would contradict the current product spec.
- Keep or rename the existing test that asserts nonzero finalization remains `FINALIZING`, but make the test name explicit that `FINALIZING` is the Phase 3 success boundary.
- Add list filtering tests with canonical, `#RUN#`, and `#OCCURRENCE#` items and assert exactly one audit is returned.
- Add `render_error("audit create", ..., "FORCE_RECREATE_BLOCKED", ...)` tests for actionable guidance.
