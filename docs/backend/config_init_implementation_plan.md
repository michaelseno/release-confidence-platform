# Implementation Plan

## 1. Feature Overview
Implement `rcp config init` as a local-only operator CLI command that generates safe starter JSON runtime configuration files for a new audit.

## 2. Technical Scope
Add CLI parsing/dispatch, safe slug and ID helpers, pure config generators, local filesystem generation with overwrite protection, local-template validation support, and required unit/API/security tests.

## 3. Source Inputs
- `docs/architecture/config_init_technical_design.md`
- `docs/product/config_init_product_spec.md`
- `docs/qa/config_init_test_plan.md`
- `docs/release/config_init_issue.md`
- Existing `src/release_confidence_platform` CLI and validation patterns

## 4. API Contracts Affected
No HTTP API contract changes.

CLI contract added: `rcp config init --client-name <name> --target-environment <dev|staging|prod|production> --output-dir <path> [--timezone <zone>] [--include-sample-endpoints] [--overwrite] [--output text|json]`.

Success returns process exit `0` with text or JSON containing `client_id`, `audit_id`, generated root `output_dir`, generated file paths, overwrite flag, and git safety warning. Local validation, conflict, or filesystem failures return exit `1`; argparse errors return exit `2`.

## 5. Data Models / Storage Affected
No database persistence changes. Local filesystem JSON output only:
- `<output-dir>/<client_id>/client_config.json`
- `<output-dir>/<client_id>/audits/<audit_id>/audit_config.json`
- `<output-dir>/<client_id>/audits/<audit_id>/endpoints.json`

Validation gains explicit local-template mode for starter configs with empty endpoint arrays and production-oriented templates with production execution disabled.

## 6. Files Expected to Change
- `src/release_confidence_platform/operator_cli/main.py`
- `src/release_confidence_platform/operator_cli/services.py`
- `src/release_confidence_platform/operator_cli/result.py`
- `src/release_confidence_platform/operator_cli/config_init.py`
- `src/release_confidence_platform/config/audit_validation_service.py`
- `src/release_confidence_platform/config/validators.py`
- `src/release_confidence_platform/audit_scheduling/safeguards.py`
- `src/release_confidence_platform/config/generators/*`
- `src/release_confidence_platform/core/id_generation.py`
- `src/release_confidence_platform/core/slug_utils.py`
- Config init tests under `tests/unit`, `tests/api`, and `tests/security`

## 7. Security / Authorization Considerations
The command is local-only and requires no authentication or authorization. It must not import or instantiate AWS/stage/storage clients. Inputs are validated before writing, generated IDs are filesystem-safe, generated files contain no secrets/auth refs/credentials, and overwrite behavior is constrained to the expected generated files.

## 8. Dependencies / Constraints
Use only Python standard library and existing project validators. No new dependencies. Timezone validation uses `zoneinfo.ZoneInfo`. Generated production-oriented templates remain non-executable by default.

## 9. Assumptions
- `prod` and `production` are both accepted CLI target environment values; generated configs preserve the exact supplied value while local-template validation treats both as production-oriented safe templates.
- Existing execution-time validation remains strict unless `template_mode=True` is explicitly supplied.

## 10. Validation Plan
- `python -m pytest tests/unit/test_config_init_cli.py tests/unit/test_config_init_generation.py tests/api/test_config_init_contract.py tests/security/test_config_init_no_aws.py`
- `python -m pytest tests/unit/test_operator_cli_rcp.py tests/api/test_operator_cli_rcp_contract.py`
