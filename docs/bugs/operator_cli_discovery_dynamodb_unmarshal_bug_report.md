# Bug Report

## 1. Summary

Operational Discovery CLI list commands do not normalize low-level DynamoDB `boto3.client("dynamodb")` AttributeValue response shapes before building CLI output. As a result, `rcp audit list` emits metadata values such as `{ "S": "DRAFT" }`, fails to derive `audit_id`, and fails to filter occurrence records when `SK` is returned as `{ "S": "..." }`. `rcp client list` similarly emits AttributeValue maps for summary fields such as `client_name` and `created_at`.

## 2. Investigation Context

- Source of report: QA automated contract testing on active branch `feature/operator_cli_discovery`.
- Related feature/workflow: Operational Discovery CLI commands `rcp audit list` and `rcp client list`.
- QA report: `docs/qa/operator_cli_discovery_test_report.md`.
- Added contract tests: `tests/api/test_operator_cli_discovery_contract.py`.
- Failing command/test group: `python3.11 -m pytest tests/api/test_operator_cli_discovery_contract.py`.

## 3. Observed Symptoms

### Failure 1: `rcp audit list` DynamoDB client item handling

- Failing test: `tests/api/test_operator_cli_discovery_contract.py::test_audit_list_unmarshals_dynamodb_client_items_and_filters_occurrences`.
- QA error excerpt from `docs/qa/operator_cli_discovery_test_report.md:39-43`:

```text
E       AssertionError: assert [{'config_ver...: 'RUNNING'}}] == [{'audit_id':...'DRAFT', ...}]
E         At index 0 diff: {'lifecycle_state': {'S': 'DRAFT'}, 'created_at': {'S': '2026-05-23T00:00:00Z'}, 'target_environment': {'S': 'staging'}, 'config_version': {'S': 'v1'}} != {'audit_id': 'audit1', 'lifecycle_state': 'DRAFT', 'created_at': '2026-05-23T00:00:00Z', 'target_environment': 'staging', 'config_version': 'v1'}
E         Left contains one more item: {'lifecycle_state': {'S': 'RUNNING'}}
```

- Observed behavior: Audit summary fields remain AttributeValue maps, `audit_id` is omitted from the primary audit item, and the occurrence item is included.
- Expected behavior: Return one metadata-only audit summary with plain scalar values and exclude occurrence records.

### Failure 2: `rcp client list` DynamoDB client item handling

- Failing test: `tests/api/test_operator_cli_discovery_contract.py::test_client_list_unmarshals_dynamodb_client_summary_fields`.
- QA error excerpt from `docs/qa/operator_cli_discovery_test_report.md:55-58`:

```text
E       AssertionError: assert [{'active_aud...T00:00:00Z'}}] == [{'active_aud...3T00:00:00Z'}]
E         At index 0 diff: {'client_id': 'client1', 'client_name': {'S': 'Client One'}, 'created_at': {'S': '2026-05-23T00:00:00Z'}, 'active_audit_count': 1} != {'client_id': 'client1', 'client_name': 'Client One', 'created_at': '2026-05-23T00:00:00Z', 'active_audit_count': 1}
```

- Observed behavior: Client summary fields remain AttributeValue maps.
- Expected behavior: Client summary fields are plain JSON/human-renderable scalar values.

## 4. Evidence Collected

- `src/release_confidence_platform/storage/aws_client_factory.py:27-30` constructs `AuditMetadataRepository` with `self._session.client("dynamodb")`. Low-level DynamoDB client `query`/`scan` responses use AttributeValue maps.
- `src/release_confidence_platform/storage/audit_metadata_client.py:57-64` returns raw `response.get("Items", [])` from `query` without unmarshalling.
- `src/release_confidence_platform/storage/audit_metadata_client.py:112-124` extracts `client_id` through `_client_id_from_item`, but copies `client_name`, `created_at`, and `updated_at` directly from the raw item into client summaries.
- `src/release_confidence_platform/storage/audit_metadata_client.py:295-308` has `_ddb_scalar`, but it is only used by `_client_id_from_item`; it is not applied to copied summary fields or full audit items.
- `src/release_confidence_platform/operator_cli/discovery_service.py:51-55` filters occurrences only when `SK` is a plain string containing `#OCCURRENCE#`.
- `src/release_confidence_platform/operator_cli/discovery_service.py:184-207` derives `audit_id` only when `SK` is a plain string and uses `_pick` to copy metadata fields unchanged.
- `src/release_confidence_platform/operator_cli/discovery_service.py:210-211` `_pick` returns raw field values from the item.
- Existing unit coverage in `tests/unit/test_operator_cli_discovery.py:165-179` covers occurrence filtering only with plain string `SK` values, which explains why unit tests passed while the DynamoDB client contract test failed.
- Contract expectations are encoded in `tests/api/test_operator_cli_discovery_contract.py:7-40` and `tests/api/test_operator_cli_discovery_contract.py:43-68` with low-level AttributeValue-shaped fake DDB responses.
- Technical design expects clean JSON output shapes with scalar fields for `client list` and `audit list` (`docs/architecture/operator_cli_discovery_technical_design.md:301-315`, `358-375`) and says audit listing must exclude occurrence items defensively (`docs/architecture/operator_cli_discovery_technical_design.md:167-168`).

## 5. Execution Path / Failure Trace

1. CLI adapters create `AwsClientFactory` and call `factory.audit_metadata_repository()` from `src/release_confidence_platform/operator_cli/services.py:58-75`.
2. `AwsClientFactory.audit_metadata_repository()` uses the low-level DynamoDB client from `boto3.Session(...).client("dynamodb")` (`src/release_confidence_platform/storage/aws_client_factory.py:27-30`).
3. `AuditMetadataRepository.list_audits_for_client()` returns raw DynamoDB `Items` from `query` (`src/release_confidence_platform/storage/audit_metadata_client.py:57-64`).
4. `DiscoveryListService.list_audits()` reads `item.get("SK")`; if `SK` is `{ "S": "AUDIT#audit1#OCCURRENCE#001" }`, the `isinstance(sk, str)` check fails and the occurrence is not filtered (`src/release_confidence_platform/operator_cli/discovery_service.py:51-55`).
5. `_safe_audit()` also cannot derive `audit_id` from AttributeValue-shaped `SK` and copies metadata fields unchanged through `_pick` (`src/release_confidence_platform/operator_cli/discovery_service.py:184-211`).
6. For `client list`, `scan_clients_bounded()` can derive `client_id` because `_client_id_from_item()` unwraps `PK`, but it copies safe summary fields directly without `_ddb_scalar`, preserving `{ "S": "..." }` values (`src/release_confidence_platform/storage/audit_metadata_client.py:112-124`, `295-308`).
7. Renderer receives already-malformed payloads and serializes/displays AttributeValue maps.

## 6. Failure Classification

- Primary classification: Application Bug.
- QA classification context: Implementation Defect.
- Severity: Blocker.
- Severity justification: QA sign-off is explicitly not approved (`docs/qa/operator_cli_discovery_test_report.md:91-93`), and the issue violates the discovery CLI output contract for two primary read-only workflows. `rcp audit list` also includes occurrence records that should not be visible in metadata-only audit summaries.
- Reproducibility: Always reproducible with the added contract tests, based on deterministic fake DynamoDB responses.

## 7. Root Cause Analysis

- Confidence label: Confirmed Root Cause.
- Immediate failure point: `DiscoveryListService.list_audits()` and `_safe_audit()` treat `SK` and metadata fields as plain Python values; `AuditMetadataRepository.scan_clients_bounded()` copies client summary fields without unwrapping AttributeValue maps.
- Underlying root cause: The repository/service boundary is inconsistent with the AWS client selected by `AwsClientFactory`. The factory supplies a low-level DynamoDB client, but discovery list code is written mostly against document-style/plain-Python item shapes. Only `_client_id_from_item()` partially compensates by unwrapping `PK`/`client_id`.
- Supporting evidence:
  - Low-level client construction: `src/release_confidence_platform/storage/aws_client_factory.py:27-30`.
  - Raw query items returned: `src/release_confidence_platform/storage/audit_metadata_client.py:57-64`.
  - Raw scan summary field copy: `src/release_confidence_platform/storage/audit_metadata_client.py:121-124`.
  - Plain-string-only occurrence filter and audit ID derivation: `src/release_confidence_platform/operator_cli/discovery_service.py:51-55`, `184-188`.
  - Raw `_pick`: `src/release_confidence_platform/operator_cli/discovery_service.py:210-211`.

## 8. Confidence Level

High. The failing contract tests directly construct the same AttributeValue response shapes produced by the low-level DynamoDB client used by `AwsClientFactory`, and the inspected code paths directly show raw item values being copied or string-checked without unmarshalling.

## 9. Recommended Fix

- Likely owner: Backend / full-stack developer responsible for operator CLI storage/service integration.
- Primary files/modules likely affected:
  - `src/release_confidence_platform/storage/audit_metadata_client.py`
  - `src/release_confidence_platform/operator_cli/discovery_service.py`
  - Optional: `src/release_confidence_platform/storage/aws_client_factory.py` if choosing a document-style DynamoDB resource/table approach instead of unmarshalling.
- Recommended remediation:
  1. Normalize DynamoDB items at the repository boundary before returning list/scan results, or centralize scalar/item unmarshalling in a shared helper used by both repository and discovery service.
  2. Ensure `list_audits_for_client()` returns items where `PK`, `SK`, and safe metadata fields are plain Python values before `DiscoveryListService` filters and shapes output.
  3. Ensure `scan_clients_bounded()` unwraps `client_name`, `created_at`, and `updated_at` before copying them into client summaries.
  4. Ensure occurrence filtering and audit ID derivation operate on normalized `SK`, so `AUDIT#...#OCCURRENCE#...` records are excluded even when the source response used AttributeValue maps.
  5. If using `boto3.dynamodb.types.TypeDeserializer`, apply it consistently to all DynamoDB response items and maintain compatibility with existing plain-dict fakes used by unit tests.
  6. Do not broaden output fields beyond the existing safe metadata allowlist.

## 10. Suggested Validation Steps

- Re-run the blocking contract suite:

```bash
python3.11 -m pytest tests/api/test_operator_cli_discovery_contract.py
```

- Re-run existing discovery unit coverage to confirm plain-shape fakes still work:

```bash
python3.11 -m pytest tests/unit/test_operator_cli_discovery.py
```

- Re-run relevant CLI regression coverage:

```bash
python3.11 -m pytest tests/unit/test_operator_cli_rcp.py tests/api/test_operator_cli_rcp_contract.py
```

- Manual/contract validation expectation:
  - `rcp audit list --output json` emits plain scalar fields and excludes occurrence records.
  - `rcp client list --output json` emits plain scalar summary fields.
  - Human text output does not show DynamoDB AttributeValue maps.

## 11. Open Questions / Missing Evidence

- No live AWS run output was provided. The contract tests are sufficient for this diagnosis because they model the exact low-level client response shape selected by `AwsClientFactory`.
- Confirm whether the team prefers repository-boundary unmarshalling or switching discovery reads to a document-style DynamoDB resource/table. The current codebase already uses low-level client methods in the repository, so repository-boundary unmarshalling is the lowest-scope remediation.

## 12. Final Investigator Decision

Ready for developer fix.
