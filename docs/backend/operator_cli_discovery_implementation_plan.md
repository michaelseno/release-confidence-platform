# Implementation Plan

## 1. Feature Overview
Implement read-only Operational Discovery commands for the internal `rcp` Operator CLI: client discovery, audit metadata discovery, config artifact metadata inspection, and safe local config downloads.

## 2. Technical Scope
- Extend the existing src-layout operator CLI parser and dispatch.
- Add shared discovery services for DynamoDB/S3-backed read-only workflows.
- Add bounded read-only storage wrapper methods.
- Add JSON/text rendering support for list and config download results.
- Add mocked unit tests and update operator CLI docs.
- Ensure `.local-configs/` is gitignored.

## 3. Source Inputs
- `docs/architecture/operator_cli_discovery_technical_design.md`
- `docs/product/operator_cli_discovery_spec.md`
- `docs/uiux/operator_cli_discovery_design_spec.md`
- `docs/qa/operator_cli_discovery_test_plan.md`
- `docs/release/operator_cli_discovery_issue.md`
- Existing `src/release_confidence_platform/operator_cli` and storage wrapper patterns.

## 4. API Contracts Affected
No HTTP API contract changes.

CLI contracts affected:
- `rcp client list --stage <dev|staging|prod> [--limit n] [--output json]`
- `rcp audit list --client-id <client_id> --stage <stage> [--limit n] [--output json]`
- `rcp config list --client-id <client_id> --audit-id <audit_id> --stage <stage> [--output json]`
- `rcp config download --client-id <client_id> --audit-id <audit_id> --output-dir <path> --stage <stage> [--overwrite] [--output json]`

`--version-id` will not be added. `--next-token` is not implemented in this PR because the user scope and UX spec exclude active pagination tokens.

## 5. Data Models / Storage Affected
No new persisted AWS data model.

Read-only access only:
- DynamoDB audit metadata table items with `PK=CLIENT#{client_id}` and `SK=AUDIT#{audit_id}`.
- Temporary bounded DynamoDB scan fallback for `client list` when no registry/index exists.
- S3 config objects at existing deterministic config paths.

Local filesystem writes only for `config download`.

## 6. Files Expected to Change
- `.gitignore`
- `src/release_confidence_platform/operator_cli/main.py`
- `src/release_confidence_platform/operator_cli/services.py`
- `src/release_confidence_platform/operator_cli/result.py`
- `src/release_confidence_platform/operator_cli/discovery_service.py`
- `src/release_confidence_platform/storage/audit_metadata_client.py`
- `src/release_confidence_platform/storage/s3_client.py`
- `tests/unit/test_operator_cli_discovery.py`
- `docs/operator-cli/README.md`
- `packages/operator_cli/README.md`
- `docs/backend/operator_cli_discovery_implementation_report.md`

## 7. Security / Authorization Considerations
- AWS authentication/authorization remains IAM-based via existing stage config and `AwsClientFactory`.
- Validate `client_id`, `audit_id`, limits, and output directory safety.
- Never access Secrets Manager.
- Never list or read `raw-results/` or raw evidence.
- `config list` uses metadata/head operations only.
- `config download` prints/returns file paths only, not config contents.
- Output continues through the existing sanitizer.

## 8. Dependencies / Constraints
- No new dependencies planned.
- No hardcoded buckets, tables, profiles, regions, ARNs, or account IDs.
- Tests use mocked/fake AWS clients only.
- Client registry/index is not visible in the current repository; implement documented temporary bounded scan fallback.

## 9. Assumptions
- Limit values above 1000 are rejected rather than capped, matching the UX invalid-argument behavior.
- `config list` requires `--audit-id` per user scope and CLI UX spec.
- Download partial cleanup will remove files written during the failed operation where possible before raising a controlled error.

## 10. Validation Plan
- `python -m pytest tests/unit/test_operator_cli_discovery.py tests/unit/test_operator_cli_rcp.py tests/api/test_operator_cli_rcp_contract.py`
- `python -m ruff check src/release_confidence_platform/operator_cli src/release_confidence_platform/storage tests/unit/test_operator_cli_discovery.py`
