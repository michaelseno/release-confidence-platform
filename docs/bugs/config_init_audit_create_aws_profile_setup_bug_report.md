# Bug Report

## 1. Summary

During HITL validation on `feature/profile_driven_config_init`, `rcp audit create --stage dev` reached AWS setup after local config validation and failed with structured `AWS_PROFILE_ERROR` because the configured dev AWS profile could not be loaded.

This is not evidence that `config init` generated missing stage config. The failure path uses existing runtime stage configuration (`config/stages/dev.json`) and AWS profile/session setup, which `config init` intentionally does not create or touch. The remaining issue is that the operator-facing UX and setup guidance are not actionable enough for a user moving from local config generation to non-dry-run audit creation.

## 2. Investigation Context

- Source of report: HITL manual validation.
- Branch context: `feature/profile_driven_config_init` remains the active correction branch; no new branch should be created.
- Related workflow: Enhanced `rcp config init` Default Profile System -> generated local config bundle -> `rcp audit create --stage dev`.
- Reported command:

```bash
rcp audit create \
  --client-config .local-configs/client_layer_1_validation_client_b5817642/client_config.json \
  --audit-config .local-configs/client_layer_1_validation_client_b5817642/audits/audit_20260524_ec3f2d9b/audit_config.json \
  --endpoints-config .local-configs/client_layer_1_validation_client_b5817642/audits/audit_20260524_ec3f2d9b/endpoints.json \
  --stage dev
```

## 3. Observed Symptoms

Observed output:

```text
ERROR: audit create failed
stage: dev
code: AWS_PROFILE_ERROR
message: AWS profile could not be loaded for stage
next_step: correct the error and retry
```

Expected behavior:

- If local generated configs are invalid/incomplete, `audit create` should fail before AWS setup with `CONFIG_VALIDATION_ERROR`.
- If local generated configs are executable-valid, non-dry-run `audit create` is expected to require valid runtime stage/AWS setup.
- The error should tell the operator which setup input to check, such as `config/stages/dev.json` `aws_profile` or `RCP_AWS_PROFILE`, rather than only `correct the error and retry`.

Reproducibility from available evidence:

- The exact user machine was not available, so the command was not re-run locally.
- The reported structured `AWS_PROFILE_ERROR` directly matches the current code path for a missing/unloadable boto profile after local config validation succeeds.

## 4. Evidence Collected

Files inspected:

- `src/release_confidence_platform/operator_cli/services.py`
- `src/release_confidence_platform/config/stage_config.py`
- `src/release_confidence_platform/storage/aws_client_factory.py`
- `src/release_confidence_platform/operator_cli/main.py`
- `src/release_confidence_platform/operator_cli/result.py`
- `src/release_confidence_platform/operator_cli/config_init.py`
- `config/stages/dev.json`
- `config/defaults/dev.json`
- `tests/unit/test_operator_cli_rcp.py`
- `docs/qa/enhanced_config_init_default_profile_system_test_report.md`
- `docs/backend/enhanced_config_init_default_profile_system_implementation_report.md`
- `docs/uiux/enhanced_config_init_default_profile_system_design_spec.md`
- `docs/operator-cli/README.md`

Key evidence:

- `services.create_command()` now loads stage config, validates local config files, then constructs AWS clients only for non-dry-run create: `src/release_confidence_platform/operator_cli/services.py:152-168`.
- Runtime stage config loading resolves `aws_profile` from `config/stages/{stage}.json` with `RCP_AWS_PROFILE` override support: `src/release_confidence_platform/config/stage_config.py:26-37` and `:70-102`.
- The repo dev stage config declares `aws_profile: "rcp-dev"`: `config/stages/dev.json:2-4`.
- `AwsClientFactory.__init__()` creates `boto3.Session(profile_name=stage_config.aws_profile, region_name=stage_config.region)`: `src/release_confidence_platform/storage/aws_client_factory.py:17-24`.
- Known boto/botocore `ProfileNotFound` is mapped to `ConfigError("AWS profile could not be loaded for stage", "AWS_PROFILE_ERROR")`: `src/release_confidence_platform/storage/aws_client_factory.py:67-73`.
- `main.main()` renders `EngineError` values as structured CLI errors, so `AWS_PROFILE_ERROR` is now expected structured error handling rather than the previous generic `UNEXPECTED_ERROR`: `src/release_confidence_platform/operator_cli/main.py:158-170`.
- The rendered error next step is generic for all errors: `next_step: correct the error and retry`: `src/release_confidence_platform/operator_cli/result.py:255-271`.
- `ConfigInitService.init()` validates generated files locally in template mode and returns local-only/no-AWS safety metadata; it does not accept/pass `--stage` or generate runtime stage configuration: `src/release_confidence_platform/operator_cli/config_init.py:112-118` and `:198-210`.
- Current config-init next steps say to review files, add real endpoints, run `rcp audit validate`, then run `rcp audit create`/`rcp audit run` only after validation passes: `src/release_confidence_platform/operator_cli/config_init.py:38-43`.
- QA explicitly validated that empty generated endpoints fail before AWS setup, and that valid sample/populated configs can reach the create path: `docs/qa/enhanced_config_init_default_profile_system_test_report.md:70-75` and `:93-95`.
- Implementation notes list known AWS setup failures as expected structured errors, including `AWS_PROFILE_ERROR`: `docs/backend/enhanced_config_init_default_profile_system_implementation_report.md:68-77`.
- The UX design's next-step template is local-only and does not currently mention AWS/stage profile setup before non-dry-run upload workflows: `docs/uiux/enhanced_config_init_default_profile_system_design_spec.md:131-135`.

## 5. Execution Path / Failure Trace

Likely path for the reported command:

1. CLI parses `audit create` with `--stage dev` and dispatches to `services.create_command()`.
2. `create_command()` calls `_stage(args)`, which loads `config/stages/dev.json` and applies any `RCP_*` environment overrides.
3. `create_command()` runs `AuditConfigValidationService.validate_files(..., template_mode=False)` before AWS construction.
4. Because the observed failure is `AWS_PROFILE_ERROR` rather than `CONFIG_VALIDATION_ERROR`, local runtime validation likely passed for the supplied files.
5. Non-dry-run create constructs `AwsClientFactory(stage_config)`.
6. `AwsClientFactory` calls `boto3.Session(profile_name=<resolved aws_profile>, region_name=<resolved region>)`.
7. Boto/botocore cannot load the resolved profile (`rcp-dev` by default, unless overridden by `RCP_AWS_PROFILE`).
8. `_raise_structured_aws_setup_error()` maps that profile setup failure to `AWS_PROFILE_ERROR`.
9. The CLI renders the structured error with a generic `next_step`.

## 6. Failure Classification

- Primary classification: Environment / Configuration Issue.
- Contributing classification: Application Bug / insufficient actionable UX for stage/AWS setup errors.
- Severity: Medium.

Severity justification: The failure blocks this HITL user from completing a non-dry-run create, but it is not a regression in local config generation or validation ordering. The command is behaving consistently with existing runtime requirements: persisting an audit draft requires AWS stage/profile setup. Impact is limited to operator setup/onboarding clarity unless the profile actually exists and cannot be loaded for another reason.

## 7. Root Cause Analysis

Confidence label: Most Likely Root Cause

Immediate failure point:

- `AwsClientFactory.__init__()` fails during `boto3.Session(profile_name=stage_config.aws_profile, ...)` and maps the boto/botocore profile failure to `AWS_PROFILE_ERROR`.

Underlying root cause:

- The operator environment does not have the AWS profile resolved for `--stage dev` available to boto, or `RCP_AWS_PROFILE` points to a profile that cannot be loaded.
- By default, the repo's dev stage config expects a local AWS profile named `rcp-dev`.

Contributing factor:

- The CLI error renderer uses a generic next step for all errors, and config-init next-step guidance says to run create/run after validation passes without explicitly stating that non-dry-run commands additionally require configured runtime stage AWS resources and a loadable AWS profile.

Not root cause:

- Missing stage config generated by `config init`. The feature is intentionally local-only and must not read/write stage config or construct AWS clients.
- The previous `UNEXPECTED_ERROR` regression. Current output is a structured expected AWS setup error.

## 8. Confidence Level

High.

The exact reported code/message is produced by the current `AwsClientFactory` profile error mapping. The stage/profile resolution path is clear from source. Full confirmation of the profile name used on the user's machine requires the user's `RCP_AWS_PROFILE` environment value and local AWS config, but those are not needed to identify the likely failure class or hand off the UX/setup issue.

## 9. Recommended Fix

Likely owner: full-stack/backend operator CLI, with QA documentation validation.

Recommended code/UX change:

1. Keep `audit create` behavior: non-dry-run create should continue requiring stage config and AWS credentials/profile after local validation passes.
2. Improve actionable error rendering for `AWS_PROFILE_ERROR` in `src/release_confidence_platform/operator_cli/result.py` (or an error metadata mapping near the CLI renderer):
   - Suggested next step: `check config/stages/<stage>.json aws_profile or set RCP_AWS_PROFILE to a loadable AWS profile, then retry`.
   - Avoid printing the raw boto exception or secret-bearing paths.
3. Improve `config init` next steps in `src/release_confidence_platform/operator_cli/config_init.py` so the transition from local validation to non-dry-run create is explicit:
   - Keep current guidance to add real endpoints before runtime validation.
   - Add that non-dry-run `audit create`/`audit run` require deployed stage resources and AWS profile/credentials configured for `--stage`; use `--dry-run` for local create planning without AWS mutation.
4. Optionally add/update operator docs (`docs/operator-cli/README.md`) with setup troubleshooting for `AWS_PROFILE_ERROR`, including `config/stages/{stage}.json`, `RCP_AWS_PROFILE`, and `RCP_AWS_REGION` override behavior.
5. Add a focused renderer/CLI regression test that `AWS_PROFILE_ERROR` includes the stage/profile setup next-step guidance and does not regress to generic `UNEXPECTED_ERROR`.

No application-side persistence or stage config generation change is recommended. Do not make `config init` create or modify AWS profiles/stage files; that would violate the local-only feature boundary.

QA/user guidance if no code change is made:

- Confirm local runtime validation first with `rcp audit validate ... --stage dev`.
- For non-dry-run create, configure the dev AWS profile expected by stage config (`rcp-dev` by default) or set `RCP_AWS_PROFILE=<loadable-profile>` before retrying.
- Use `rcp audit create --dry-run ... --stage dev` to validate the create plan without constructing AWS clients or writing S3/DynamoDB.

## 10. Suggested Validation Steps

- Generate a config-init bundle and add at least one real or safe sample endpoint so runtime validation passes.
- Run `rcp audit create --dry-run ... --stage dev` and confirm it succeeds without AWS profile dependency.
- Run non-dry `rcp audit create ... --stage dev` with `RCP_AWS_PROFILE` set to a deliberately missing profile and confirm:
  - exit code is non-zero;
  - code is `AWS_PROFILE_ERROR`;
  - message remains sanitized;
  - next step points to `config/stages/dev.json`/`RCP_AWS_PROFILE` setup rather than generic retry advice.
- Run non-dry create with a valid AWS profile and stage resources in an authorized environment and confirm audit draft persistence succeeds.
- Verify `config init` text and JSON outputs still state local-only/no-AWS behavior and now distinguish local validation from non-dry-run AWS setup.

## 11. Open Questions / Missing Evidence

- What is the user's effective `RCP_AWS_PROFILE` value, if any?
- Does the user have a local AWS profile named `rcp-dev`, or should HITL validation use a different profile via `RCP_AWS_PROFILE`?
- Were the supplied endpoint configs generated with `--include-sample-endpoints` or manually populated? The `AWS_PROFILE_ERROR` implies local runtime validation passed, but the file contents were not provided.
- Are deployed dev resources and real bucket/table names configured, or are `config/stages/dev.json` placeholders still present in the user's environment?

## 12. Final Investigator Decision

Ready for developer fix.

This is primarily an expected operator environment/setup failure surfaced through a structured error, not a missing generated stage config or validation-ordering regression. A small UX/documentation code change is recommended so the next step is actionable during HITL onboarding.
