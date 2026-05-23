# Test Report

## 1. Execution Summary

- Feature under test: Operational Discovery CLI commands on `feature/operator_cli_discovery`
- Validation scope: re-run of previously failing DynamoDB unmarshalling contract tests, discovery unit tests, relevant/full unit suite, core Operator CLI regression tests, and CLI help smoke checks.
- Pytest command groups executed: 4
- Test executions observed across command groups: 104 passed, 0 failed
- Unique automated coverage confirmed by final broad run: 76 unique tests passed (`74` unit tests + `2` discovery contract tests)
- QA decision: **Approved**. The previously blocking DynamoDB unmarshalling defects are fixed, and no targeted/core regressions were observed.

Executed commands and outcomes:

| Command | Result |
| --- | --- |
| `python3.11 -m pytest tests/api/test_operator_cli_discovery_contract.py` | 2 passed |
| `python3.11 -m pytest tests/unit/test_operator_cli_discovery.py` | 14 passed |
| `python3.11 -m pytest tests/unit/test_operator_cli_rcp.py tests/api/test_operator_cli_rcp_contract.py` | 14 passed |
| `python3.11 -m pytest tests/unit` | 74 passed |
| CLI help smoke checks via `python3.11 scripts/rcp.py ... --help` and `rcp client --help` | Help rendered successfully; `--version-id` rejected |

## 2. Detailed Results

| Test / Check | Acceptance Criteria Covered | Outcome | Evidence |
| --- | --- | --- | --- |
| Added QA contract: `test_audit_list_unmarshals_dynamodb_client_items_and_filters_occurrences` | AC-006, AC-007 | Pass | Included in `tests/api/test_operator_cli_discovery_contract.py`: `2 passed in 0.02s`. Confirms low-level DynamoDB AttributeValue audit items are normalized, `audit_id` is derived from `SK`, and occurrence records are filtered. |
| Added QA contract: `test_client_list_unmarshals_dynamodb_client_summary_fields` | AC-001, AC-002, metadata shape correctness | Pass | Included in `tests/api/test_operator_cli_discovery_contract.py`: `2 passed in 0.02s`. Confirms client summary fields are unwrapped to plain scalar values. |
| Existing discovery unit suite | Parser support, default/max limits, bounded scan fallback, config metadata-only listing, exact three-file download, overwrite protection, JSON/human rendering | Pass | `14 passed in 0.18s` |
| Core Operator CLI regression suite | Existing `audit` CLI behavior and API contract regression | Pass | `14 passed in 0.18s` |
| Full unit suite | Relevant unit-suite regression coverage beyond discovery CLI | Pass | `74 passed in 0.33s` |
| Help smoke: `client --help`, `client list --help`, `audit list --help`, `config --help`, `config list --help`, `config download --help` | Command exposure, required options, no `--version-id` exposure | Pass | Help output rendered expected command/option groups. `config download --help` includes `--client-id`, `--audit-id`, `--output-dir`, `--overwrite`, `--stage`, `--output`; no `--version-id`. |
| Smoke: `config download ... --version-id v1` | AC-020 | Pass | Parser rejected unsupported flag: `rcp: error: unrecognized arguments: --version-id v1`. |
| Installed entry point smoke: `rcp client --help` | CLI entry point compatibility | Pass | Help rendered successfully: `usage: rcp client [-h] {list} ...`. |

## 3. Failed Tests

No failed tests were observed in this validation cycle.

Previously blocking failures from the prior QA run are now resolved:

- `tests/api/test_operator_cli_discovery_contract.py::test_audit_list_unmarshals_dynamodb_client_items_and_filters_occurrences` now passes.
- `tests/api/test_operator_cli_discovery_contract.py::test_client_list_unmarshals_dynamodb_client_summary_fields` now passes.

## 4. Failure Classification

No active failures require classification.

Resolved defect classification from prior run:

| Prior Failure | Prior Classification | Current Status | Evidence |
| --- | --- | --- | --- |
| Audit list retained DynamoDB AttributeValue maps and included occurrence records. | Application Bug / Blocking | Resolved | Discovery contract suite passed: `2 passed in 0.02s`. |
| Client list retained DynamoDB AttributeValue maps for summary fields. | Application Bug / Blocking | Resolved | Discovery contract suite passed: `2 passed in 0.02s`. |

## 5. Observations

- DynamoDB low-level AttributeValue normalization is now covered by explicit API contract tests.
- Discovery unit tests continue to pass, indicating compatibility with existing plain-dict fake item shapes and behavior coverage.
- Core Operator CLI parser/contract tests remain passing after the discovery fix.
- CLI help output remains concise and exposes only the intended discovery commands/options.
- `--version-id` remains deferred and is not accepted by `config download`.
- No live AWS execution was performed; validation used mocked/fake dependencies as required by AC-021.

## 6. Regression Check

- Previously failing contract coverage is now passing with deterministic fake low-level DynamoDB responses.
- Full unit suite passed: `74 passed`, confirming no detected regression in related foundation, engine, lifecycle, safeguards, config validation, and Operator CLI unit coverage.
- Core Operator CLI regression tests passed: `tests/unit/test_operator_cli_rcp.py` and `tests/api/test_operator_cli_rcp_contract.py` reported `14 passed`.
- Help smoke checks confirm `client`, `audit list`, and `config` command groups remain available without exposing deferred `--version-id` behavior.

---

## HITL Documentation Addendum: macOS editable-install `.pth` troubleshooting

### 1. Execution Summary

- Scope: documentation-only HITL validation for Operator CLI README troubleshooting content on branch `feature/operator_cli_discovery`.
- Files inspected: `docs/operator-cli/README.md`, `packages/operator_cli/README.md`, `docs/backend/operator_cli_discovery_implementation_plan.md`, `docs/backend/operator_cli_discovery_implementation_report.md`.
- Checks executed: 3
- Passed: 3
- Failed: 0

### 2. Detailed Results

| Test / Check | Expected Result | Outcome | Evidence |
| --- | --- | --- | --- |
| README content inspection | Both Operator CLI READMEs document the symptom, macOS hidden `.pth` cause, remediation commands, clean venv rebuild fallback, and Python 3.11 constraint. | Pass | `python3.11 - <<'PY' ...` reported `docs/operator-cli/README.md: required troubleshooting content present` and `packages/operator_cli/README.md: required troubleshooting content present`. Manual inspection confirmed the symptom text `ModuleNotFoundError: No module named 'release_confidence_platform'`, cause statement for macOS hidden file flags causing Python to skip editable-install `.pth` files, commands `chflags -R nohidden .venv`, `.venv/bin/python -m pip install -e .`, `hash -r`, `rcp --help`, `rcp audit --help`, clean rebuild commands, and `>=3.11,<3.12`. |
| Docs-only change boundary | HITL addition must not change CLI runtime behavior. | Pass | `git diff --name-status f8583bb..HEAD` listed only documentation files: `docs/backend/operator_cli_discovery_implementation_plan.md`, `docs/backend/operator_cli_discovery_implementation_report.md`, `docs/operator-cli/README.md`, `packages/operator_cli/README.md`. No `src/`, `scripts/`, or test runtime implementation files changed in the HITL docs commits. |
| Lightweight CLI help smoke | Existing CLI help should still render. | Pass | `python3.11 scripts/rcp.py --help && python3.11 scripts/rcp.py audit --help` rendered usage successfully for top-level `rcp` and `rcp audit` command group. |

### 3. Failed Tests

No failed tests were observed for the HITL documentation validation.

### 4. Failure Classification

No active failures require classification.

### 5. Observations

- The primary `docs/operator-cli/README.md` troubleshooting section is explicit and operator-actionable.
- The package-local compatibility README mirrors the same guidance concisely.
- The clean rebuild fallback uses `python3.11 -m venv .venv`, matching the repository Python constraint documented from `pyproject.toml`.
- Existing untracked workspace artifacts are present outside this validation scope; no application code changes were made by QA.

### 6. Regression Check

- Git diff inspection confirms the HITL addition is documentation-only.
- CLI help smoke checks confirm the top-level and audit help paths still render after the documentation update.

## 7. QA Decision

[QA SIGN-OFF APPROVED]
