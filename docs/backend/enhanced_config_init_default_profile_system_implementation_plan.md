# Implementation Plan

## 1. Feature Overview
Implement profile-driven, local-only `rcp config init` default initialization for starter client/audit config workspaces.

## 2. Technical Scope
Update the existing operator CLI init path to resolve bundled or path-based defaults profiles, merge profile defaults with explicit CLI overrides, generate validation-compatible local config files, and preserve overwrite/no-AWS safety.

QA loop scope: align `config init` success rendering with the CLI UX spec by adding the production warning block in text output and the enhanced structured JSON success shape.

HITL blocker scope: fix `rcp audit create` error ordering for generated config-init bundles so runtime config validation runs before AWS client construction, empty starter endpoints fail with actionable structured validation errors, and valid configs continue into the create path.

HITL AWS setup guidance scope: improve operator-facing `AWS_PROFILE_ERROR` next-step guidance and `config init` next steps so non-dry-run `audit create`/`audit run` are clearly gated behind edited endpoints, local validation, deployed stage resources, and a loadable stage AWS profile/credential setup.

HITL S3 stage diagnostic scope: add safe local diagnostic visibility for resolved stage resources so operators can confirm whether exported `RCP_*` overrides are visible to the `rcp` subprocess before retrying non-dry-run `audit create`.

## 3. Source Inputs
- `docs/architecture/enhanced_config_init_default_profile_system_technical_design.md`
- `docs/product/enhanced_config_init_default_profile_system_product_spec.md`
- `docs/uiux/enhanced_config_init_default_profile_system_design_spec.md`
- `docs/qa/enhanced_config_init_default_profile_system_test_plan.md`
- `docs/release/enhanced_config_init_default_profile_system_issue.md`
- `docs/bugs/config_init_audit_create_unexpected_error_bug_report.md`
- `docs/bugs/config_init_audit_create_aws_profile_setup_bug_report.md`
- `docs/bugs/config_init_audit_create_s3_write_failure_bug_report.md`

## 4. API Contracts Affected
CLI contract only: `rcp config init` requires `--client-name`; supports optional `--defaults`, `--output-dir`, `--timezone`, `--include-sample-endpoints`, `--overwrite`, and `--output text|json`. Exit code `0` on success and `1` on local/profile/validation/write errors.

HITL blocker affects existing `rcp audit create` behavior without changing arguments or response schema: local config validation failures return existing structured `CONFIG_VALIDATION_ERROR`/`CONFIG_LOAD_ERROR` before AWS setup; dry-run behavior remains validation-only/no-mutation; non-dry-run valid configs proceed to S3/metadata create after validation.

HITL AWS setup guidance affects CLI text/error guidance only: `AWS_PROFILE_ERROR` still fails non-dry-run commands when the resolved stage AWS profile cannot be loaded, but text rendering points operators to `config/stages/<stage>.json` `aws_profile` or `RCP_AWS_PROFILE`. `config init` text/JSON next steps clarify that non-dry-run create/run require endpoint edits, local validation, deployed stage resources, and loadable AWS credentials.

HITL S3 diagnostics add a CLI-only command: `rcp config stage-info --stage <dev|staging|prod> --output text|json`. It resolves local stage config through `StageConfigLoader`, performs no live AWS calls, and prints sanitized non-secret values: stage, region, aws_profile, config_bucket, audit_metadata_table, scheduler_group, and export guidance.

## 5. Data Models / Storage Affected
No persistent backend storage changes. Adds local defaults profile JSON files under `config/defaults/` and writes local generated files only under `<output_dir>/<client_id>/`.

## 6. Files Expected to Change
- `config/defaults/dev.json`
- `config/defaults/staging.json`
- `config/defaults/prod.json`
- `src/release_confidence_platform/operator_cli/default_profiles.py`
- `src/release_confidence_platform/operator_cli/config_init.py`
- `src/release_confidence_platform/operator_cli/main.py`
- `src/release_confidence_platform/operator_cli/services.py`
- `src/release_confidence_platform/operator_cli/result.py`
- `tests/api/test_s3_storage_error_guidance.py`
- `src/release_confidence_platform/config/generators/*.py`
- `src/release_confidence_platform/storage/aws_client_factory.py`
- Config init tests under `tests/unit`, `tests/api`, and `tests/security`
- Operator CLI audit create regression tests under `tests/unit/test_operator_cli_rcp.py`

## 7. Security / Authorization Considerations
No authentication or AWS authorization is used. Validate profile paths/content, reject secret-bearing profile keys, sanitize client names via generated IDs, use safe non-executable production defaults, and avoid logging/outputting secrets.

For `audit create`, preserve stage config loading but ensure local JSON validation and endpoint execution-safety checks occur before AWS client/session/client setup, so invalid local files cannot be masked by AWS profile/session errors.

## 8. Dependencies / Constraints
No new third-party dependencies. Uses standard library JSON/path/zoneinfo and existing validation, ID, rendering, and exception patterns. Command remains local-only and must not construct AWS clients.

AWS setup errors should be translated into existing structured backend error types without adding botocore-specific dependency requirements beyond existing boto3 usage.

The AWS profile setup guidance must not create stage config, suppress the setup error, perform live AWS calls, or weaken dry-run/local-only guarantees.

The stage-info diagnostic must not create AWS clients, check resources, generate credentials, mutate stage files, or change placeholder stage values. It is a local config resolution view only.

## 9. Assumptions
- `profile_schema_version: v1` is included in bundled profiles per technical design.
- Existing validation accepts profile-derived generated config fields such as `retention_defaults`.
- For installed usage outside a repo checkout, bundled profile discovery remains a future packaging concern per design.
- Empty `endpoints: []` remains valid only for generated starter/template validation, not for executable `audit validate` or `audit create` runtime validation.
- Existing stage config and AWS credential provisioning remain operator/environment responsibilities outside `config init`.
- Stage resource identifiers such as bucket names, table names, AWS profile names, and scheduler group names are treated as non-secret operational diagnostics for the explicit `stage-info` command.
- Environment overrides only affect subprocesses when exported; shell-local `RCP_*` assignments are intentionally not visible to `StageConfigLoader` through `os.environ`.

## 10. Validation Plan
- `python -m pytest tests/unit/test_config_init_generation.py tests/unit/test_config_init_cli.py tests/api/test_config_init_contract.py tests/api/test_config_init_profiles.py tests/security/test_config_init_no_aws.py -q`
- Broader practical regression with `python -m pytest tests/api -q` if focused tests pass.
- QA loop focused validation: `python3.11 -m pytest tests/unit/test_config_init_cli.py tests/api/test_config_init_contract.py tests/api/test_config_init_profiles.py tests/security/test_config_init_no_aws.py -q`
- QA loop full regression as practical: `python3.11 -m pytest -q`
- HITL blocker focused regression: `python3.11 -m pytest tests/unit/test_operator_cli_rcp.py tests/unit/test_config_init_cli.py tests/api/test_config_init_contract.py tests/security/test_config_init_no_aws.py -q`
- HITL AWS setup guidance focused regression: `python3.11 -m pytest tests/unit/test_operator_cli_rcp.py tests/unit/test_config_init_cli.py -q`
- HITL S3 stage diagnostic focused regression: `python3.11 -m pytest tests/unit/test_config_init_cli.py tests/api/test_s3_storage_error_guidance.py -q`
