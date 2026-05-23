# Pull Request

## 1. Feature Name

Operator CLI Discovery

## 2. Summary

Adds internal, read-only operational discovery commands to the existing `rcp` Operator CLI for listing clients, listing client audits, inspecting persisted config artifact metadata, and downloading the expected runtime config artifacts safely.

## 3. Related Documents

- Product Spec: docs/product/operator_cli_discovery_spec.md
- Technical Design: docs/architecture/operator_cli_discovery_technical_design.md
- UI/UX Spec: docs/uiux/operator_cli_discovery_design_spec.md
- QA Test Plan: docs/qa/operator_cli_discovery_test_plan.md
- QA Report: docs/qa/operator_cli_discovery_test_report.md
- Release Issue: docs/release/operator_cli_discovery_issue.md
- Bug Report: docs/bugs/operator_cli_discovery_dynamodb_unmarshal_bug_report.md

## 4. Changes Included

- Adds `rcp client list`, `rcp audit list`, `rcp config list`, and `rcp config download` discovery workflows.
- Adds shared discovery service behavior for bounded DynamoDB/S3 read-only access and safe config downloads.
- Extends Operator CLI parsing, service adapters, result rendering, storage wrappers, and `.local-configs/` ignore handling.
- Adds mocked unit coverage and API contract coverage for discovery behavior, including DynamoDB AttributeValue unmarshalling.
- Adds discovery planning, UI/UX, QA, bug, release, and implementation documentation artifacts.
- Adds operator troubleshooting documentation for editable-install `.pth` visibility issues observed during HITL validation.

## 5. QA Status

- Approved: YES
- QA sign-off phrase confirmed in `docs/qa/operator_cli_discovery_test_report.md`: `[QA SIGN-OFF APPROVED]`
- HITL validation phrase provided by requester: `HITL validation successful`

## 6. Test Coverage

- `python3.11 -m pytest tests/api/test_operator_cli_discovery_contract.py` — 2 passed
- `python3.11 -m pytest tests/unit/test_operator_cli_discovery.py` — 14 passed
- `python3.11 -m pytest tests/unit/test_operator_cli_rcp.py tests/api/test_operator_cli_rcp_contract.py` — 14 passed
- `python3.11 -m pytest tests/unit` — 74 passed
- CLI help smoke checks for discovery commands and installed `rcp` entry point passed

## 7. Risks / Notes

- No live AWS execution was performed; validation used mocked/fake dependencies as required.
- `client list` may rely on a bounded DynamoDB scan fallback until a first-class client registry/index exists.
- Downloaded config files may contain sensitive operational details; operators should use ignored `.local-configs/` paths and handle files carefully.
- `--version-id` remains intentionally deferred and is not exposed.
- Suspicious duplicate untracked files named like `* 2.py` and `README 2.md` were excluded/removed before release commit.

## 8. Linked Issue

- Closes #13
