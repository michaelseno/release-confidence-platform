# Implementation Plan

## 1. Feature Overview
Implement the approved HITL audit create/list blocker fixes for canonical audit discovery and clearer force-recreate operator guidance.

## 2. Technical Scope
- Filter `audit list` results to canonical audit metadata rows only.
- Make audit metadata listing pagination-aware when DynamoDB pages contain child rows.
- Add dedicated `FORCE_RECREATE_BLOCKED` next-step guidance.
- Preserve existing force-recreate and finalization lifecycle semantics.

## 3. Source Inputs
- `docs/architecture/hitl_audit_create_blocker_technical_design.md`
- `docs/bugs/hitl_audit_create_lambda_permissions.md`
- Existing backend/operator CLI code and test patterns.

## 4. API Contracts Affected
No HTTP API contract changes.

CLI behavior affected:
- `rcp audit list --client-id ...` returns only canonical `PK=CLIENT#<client_id>`, `SK=AUDIT#<audit_id>` rows.
- `rcp audit create --force` remains limited to `DRAFT`/`FAILED`; text error guidance is more actionable for `FORCE_RECREATE_BLOCKED`.

## 5. Data Models / Storage Affected
No data model or storage changes. Existing DynamoDB row shapes are preserved; read filtering excludes audit child sort-key suffixes.

## 6. Files Expected to Change
- `src/release_confidence_platform/storage/audit_metadata_client.py`
- `src/release_confidence_platform/operator_cli/discovery_service.py`
- `src/release_confidence_platform/operator_cli/result.py`
- Focused tests under `tests/unit/` and `tests/api/`

## 7. Security / Authorization Considerations
- Preserve tenant/client partition boundary by requiring `PK=CLIENT#<client_id>` for canonical audit rows.
- Avoid exposing child run/occurrence/future child metadata through operator discovery.
- Preserve destructive force-recreate allowlist of `DRAFT`/`FAILED` only.

## 8. Dependencies / Constraints
No new dependencies. Implementation must not introduce lifecycle transitions beyond the approved Phase 3 boundary.

## 9. Assumptions
- Existing identifier validation remains the caller-level validation path for `client_id` and `audit_id`.
- Pagination-aware repository filtering is sufficient because `DiscoveryListService` consumes repository pages.

## 10. Validation Plan
- Run focused discovery tests.
- Run focused operator CLI result/force-recreate tests.
- Run focused finalization/cancellation tests to confirm lifecycle semantics remain unchanged.
