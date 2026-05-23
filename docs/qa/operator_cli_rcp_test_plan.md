# Test Plan

## 1. Feature Overview

Feature: Operator CLI `rcp` for internal Release Confidence Platform audit operations.

Primary invocation under test:

```bash
python scripts/rcp.py audit <validate|create|schedule|run|cancel> ...
```

The CLI must provide safe, repeatable operator workflows for validating local audit configs, creating draft audit metadata, scheduling audits from persisted source-of-truth config, manually invoking orchestrator smoke runs, and cancelling audits. The implementation must remain a thin CLI layer over shared validation, lifecycle, storage, scheduling, run ID, production safety, and sanitization modules.

QA scope for this plan is automated unit-level validation only. All AWS dependencies must be mocked or faked; tests must not construct real boto3 clients, read real AWS credentials, or call AWS services.

Upstream references:

- Product spec: `docs/product/operator_cli_rcp_spec.md`
- Technical design: `docs/architecture/operator_cli_rcp_technical_design.md`
- CLI UX spec: `docs/uiux/operator_cli_rcp_design_spec.md`

Confirmed requirement constraints to preserve in tests:

- `--stage` must be accepted only for `dev`, `staging`, and `prod`.
- Cleanup partial failure must persist operator intent by transitioning the audit to `CANCELLED`, retain schedule metadata, persist sanitized `cleanup_errors` in DynamoDB, print an operator-visible warning summary, and exit with code `3`.
- `--output json` is optional. If implemented, tests must include equivalent sanitization, shape, and exit-code assertions for JSON output; if not implemented, parser/help tests must not require it.
- `rcp audit create --force` is allowed only for existing audit metadata in lifecycle state `DRAFT` or `FAILED`; it must overwrite persisted S3 config objects and update DynamoDB metadata, append lifecycle history reason `force_recreate`, still enforce validation and safety checks, and must not overwrite or delete run evidence or `raw-results/*` artifacts.
- `rcp audit create --force` must fail for existing audits in lifecycle state `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, or `CANCELLED` before any overwrite or metadata mutation.
- Stage config environment overrides are explicitly named: `RCP_AWS_REGION`, `RCP_AWS_PROFILE`, `RCP_CONFIG_BUCKET`, `RCP_AUDIT_METADATA_TABLE`, `RCP_ORCHESTRATOR_FUNCTION_NAME`, `RCP_SCHEDULER_GROUP_NAME`, and `RCP_SCHEDULE_NAME_PREFIX`; non-empty override values take precedence over stage config file values.

## 2. Acceptance Criteria Mapping

| ID | Acceptance Criteria / Requirement | Planned Test Coverage |
| --- | --- | --- |
| AC-001 | Validate succeeds for valid configs and performs no AWS calls. | Unit tests for `audit validate` command using valid temp config fixtures, fake stage config, mocked AWS factory; assert exit `0`, success output, no S3/DynamoDB/EventBridge/Lambda calls and no boto3 construction. |
| AC-002 | Validate fails on audit window >48h with no mutation/invocation. | Validation unit tests for 48h + 1 second window; assert non-zero exit, controlled/sanitized window error, zero AWS calls. |
| AC-003 | Create dry-run reports intended S3/DynamoDB actions and performs no mutation. | Create dry-run command/service unit test; assert planned three S3 keys and DRAFT metadata summary, no S3 writes, no DynamoDB writes, no schedules, no Lambda invocation. |
| AC-004 | Create success uploads three deterministic S3 keys and writes DRAFT metadata, no schedules. | Non-dry-run create service unit test with mock S3 and DynamoDB; assert exact keys, payloads are validated config objects, `PK`, `SK`, `lifecycle_state=DRAFT`, config hash/version when available, and no EventBridge/Lambda calls. |
| AC-005 | Existing audit without `--force` fails without overwriting. | Conflict unit tests with existing S3 config objects and existing DynamoDB metadata; assert non-zero, no S3 upload, no metadata write/update, no evidence deletion. |
| AC-005F | Existing audit with `--force` follows confirmed overwrite rules. | Force create tests for eligible `DRAFT`/`FAILED`, ineligible active/terminal states, validation/safety failures, lifecycle history reason `force_recreate`, S3 config overwrite, DynamoDB metadata update, and run evidence/raw-results preservation. |
| AC-006 | Schedule dry-run reports schedules/metadata updates without EventBridge/DynamoDB mutation. | Schedule dry-run unit test using mocked S3 config and metadata in eligible lifecycle; assert planned enabled schedules and SCHEDULED transition summary, no schedule create/delete/disable, no metadata update. |
| AC-007 | Schedule success creates only enabled schedules, stores metadata, transitions SCHEDULED. | Schedule service unit test with enabled baseline/burst/repeated/finalization blocks; assert EventBridge calls use stage scheduler group/name prefix convention, DynamoDB schedule metadata persisted, lifecycle transition to `SCHEDULED`. |
| AC-008 | Missing/disabled schedule block is skipped; no inferred replacement. | Parameterized schedule tests for missing and `enabled=false` blocks; assert absent schedule type has no EventBridge call and no replacement metadata. |
| AC-009 | Production scheduling without `--allow-production` is blocked. | Schedule unit test for `--stage prod` and/or production target without flag; assert non-zero, `PRODUCTION_APPROVAL_REQUIRED`/controlled safety error, no EventBridge or DynamoDB mutation. |
| AC-010 | Partial schedule failure rolls back, records sanitized failure metadata, transitions FAILED, never persists SCHEDULED_WITH_ERRORS. | Mock second schedule create failure after first success; assert rollback delete/disable attempted for created schedules, DynamoDB transition to `FAILED`, sanitized failure metadata, non-zero exit, no `SCHEDULED_WITH_ERRORS`. |
| AC-011 | Manual run without supplied run ID invokes orchestrator with `triggered_by=manual` and omits `run_id`. | Run command/service test with mock Lambda; assert payload has client/audit/scenario and `triggered_by=manual`, no `run_id`, stage function name used, exit `0`. |
| AC-012 | Invalid supplied run ID fails before Lambda invocation. | Run validation test with unsafe run ID; assert shared run ID validator failure, sanitized message, non-zero exit, no Lambda invocation. |
| AC-013 | Cancel success cleans schedules, retains schedule metadata, records reason, transitions CANCELLED. | Cancel service unit test with schedule metadata; assert delete or disable calls, DynamoDB retains existing schedule metadata, writes reason, lifecycle `CANCELLED`. |
| AC-014 | Cancel cleanup failure records sanitized `cleanup_errors`, retains metadata, transitions CANCELLED, reports problem. | Mock cleanup partial failure; assert fallback disable if applicable, sanitized `cleanup_errors`, retained schedules, `CANCELLED` transition, warning summary, and exit code `3`. |
| AC-015 | Missing required stage config field fails before AWS client construction. | Stage loader/CLI tests for missing required fields and malformed/empty explicit `RCP_*` env overrides; assert controlled error, no client factory/boto3 construction. |
| AC-016 | No secrets in output. | Sanitization tests across validation, AWS provider error, invocation error, cleanup failure, dry-run output; assert no tokens, Authorization headers, cookies, credentials, raw payloads, or raw provider exception text. |
| FR-001 / UX | Parser supports `audit` group and all subcommands/options. | Argument parsing unit tests for required arguments, choices, help behavior, parser error exit `2`, invalid command, invalid `--stage`, invalid scenario/schedule type, optional flags. |
| FR-002 | Stage resolution for dev/staging/prod and required fields. | Stage config unit tests for valid stages, invalid stage, missing/malformed files, required fields, explicit `RCP_*` env override names/precedence, empty/invalid env overrides, fail-fast sequencing. |
| FR-003 | CLI remains thin and delegates rules to shared modules. | Command dispatch tests using service mocks; assert handlers pass request objects and do not directly call AWS wrappers/business validators except service boundary. |
| FR-004 | Validate checks JSON syntax, schemas/required fields, ID consistency, audit window, endpoint methods, payload strategy/safety, production restrictions, auth_ref. | Validation service parameterized unit tests covering each validation dimension independently with deterministic failure messages and no side effects. |
| FR-010 | Dry-run validates and does not mutate for create, schedule, run, cancel. | Dry-run tests for create/schedule/cancel required by task plus run dry-run regression coverage; assert validation still occurs and mutations/invocations do not occur. |
| FR-011 / UX | Clear sanitized output and exit codes. | CLI renderer/error-mapping tests for success, dry-run, controlled error, parser error, cleanup partial failure warning with exit code `3`, optional JSON shape if implemented. |

## 3. Test Scenarios

### 3.1 Argument Parsing Unit Tests

Target location: `tests/operator_cli/` or `tests/unit/operator_cli/` depending on repository convention. If a strict path must be selected for this feature, use `tests/api/operator_cli/` to align with the QA artifact structure for non-UI CLI tests.

1. `test_parser_lists_audit_commands`
   - Purpose: Verify top-level CLI exposes only supported command group and subcommands.
   - Input: `python scripts/rcp.py --help`, `audit --help` through parser entry point.
   - Expected: Help includes `audit`, `validate`, `create`, `schedule`, `run`, `cancel`; unavailable commands are not advertised.
   - Validation logic: Capture parser output; assert deterministic command names and exit behavior.

2. `test_each_command_requires_stage`
   - Purpose: Prevent ambiguous environment targeting.
   - Input: Each subcommand with otherwise valid required args but missing `--stage`.
   - Expected: Parser exits `2` with usage; no service dispatch.
   - Validation logic: Mock command services and assert not called.

3. `test_stage_choices_are_dev_staging_prod_only`
   - Purpose: Verify supported stage boundary.
   - Input: `--stage dev|staging|prod|qa|production`.
   - Expected: First three parse; unsupported choices exit `2`.
   - Validation logic: Assert namespace stage values and parser error for invalid values.

4. `test_command_required_and_optional_flags_parse_correctly`
   - Purpose: Verify command contracts.
   - Input: Valid argument vectors for validate/create/schedule/run/cancel including `--dry-run`, `--force`, `--allow-production`, `--run-id`, `--schedule-type`, `--reason`.
   - Expected: Namespace/request object contains correct booleans and values.
   - Validation logic: Assert parsed fields or service request passed to mock service.

5. `test_run_scenario_and_schedule_type_choices`
   - Purpose: Enforce allowed manual run inputs.
   - Input: Valid scenario types `baseline_health`, `burst_stability`, `repeated_stability`, `response_consistency`; invalid scenario; valid/invalid schedule types.
   - Expected: Valid parse; invalid choices exit `2` or controlled validation failure before Lambda.
   - Validation logic: Assert parser/service boundary behavior.

### 3.2 Validate Command Unit Tests

1. `test_validate_valid_configs_success_no_aws_calls`
   - Maps to: AC-001, FR-004.
   - Input: Valid client, audit, endpoints JSON fixtures and valid stage config.
   - Expected: Exit `0`, success output, no S3/DynamoDB/EventBridge/Lambda calls.
   - Validation logic: Mock AWS factory/wrappers; assert zero construction/mutation/invocation calls.

2. `test_validate_rejects_invalid_json_syntax`
   - Maps to: FR-004 edge case.
   - Input: Malformed JSON in each config file, parameterized.
   - Expected: Non-zero controlled config error; file category identified; no raw file contents printed.

3. `test_validate_rejects_schema_and_required_field_errors`
   - Maps to: FR-004.
   - Input: Configs missing required client/audit/endpoints fields.
   - Expected: Non-zero with deterministic path-specific validation errors.

4. `test_validate_rejects_client_id_and_audit_id_mismatch`
   - Maps to: FR-004 edge case.
   - Input: Mismatched `client_id` or `audit_id` across files.
   - Expected: Non-zero; safe expected/found IDs if allowed; no side effects.

5. `test_validate_allows_exactly_48_hour_window_and_rejects_over_48h`
   - Maps to: AC-002, FR-009.
   - Input: Audit windows exactly 48 hours and 48 hours + 1 second.
   - Expected: Exact boundary succeeds; over-boundary fails.

6. `test_validate_rejects_invalid_audit_window_order`
   - Maps to: edge case.
   - Input: `start_at` after `end_at`.
   - Expected: Non-zero controlled audit window error.

7. `test_validate_endpoint_methods_against_client_safety_config`
   - Maps to: FR-004, FR-009.
   - Input: Endpoint method not in allowed methods and destructive method without approval.
   - Expected: Non-zero production/safety validation error.

8. `test_validate_payload_strategy_and_payload_safety`
   - Maps to: FR-004.
   - Input: Unsupported payload strategy and invalid payload safety configuration.
   - Expected: Non-zero controlled validator errors from shared payload validation.

9. `test_validate_auth_ref_presence_when_required`
   - Maps to: FR-004.
   - Input: Endpoint requiring authentication without `auth_ref`; endpoint not requiring auth without `auth_ref`.
   - Expected: Required-auth case fails; no-auth case succeeds if otherwise valid.

10. `test_validate_production_restrictions`
    - Maps to: FR-009, AC-009 support.
    - Input: Production target without `allow_production_execution`, destructive operation without `allow_destructive_operation`, excessive caps/concurrency.
    - Expected: Non-zero controlled production safety errors.

### 3.3 Create Command Unit Tests

1. `test_create_dry_run_reports_expected_actions_no_mutation`
   - Maps to: AC-003, FR-010.
   - Input: Valid configs, no existing metadata, `--dry-run`.
   - Expected: Dry-run output lists exact S3 keys and DRAFT metadata write; no mutation.
   - Validation logic: Assert mock S3 `write_json`/put not called; DynamoDB put/update not called; EventBridge/Lambda not called.

2. `test_create_non_dry_run_uploads_three_s3_keys_and_writes_draft_metadata`
   - Maps to: AC-004.
   - Input: Valid configs, no existing metadata.
   - Expected: Upload to `configs/{client_id}/client_config.json`, `configs/{client_id}/audits/{audit_id}/audit_config.json`, `configs/{client_id}/audits/{audit_id}/endpoints.json`; metadata `PK`, `SK`, `lifecycle_state=DRAFT`, config hash/version when available.
   - Validation logic: Assert exact mock call order if sequencing is required after conflict check; assert no schedule or Lambda calls.

3. `test_create_existing_s3_configs_without_force_blocks_before_overwrite`
   - Maps to: AC-005.
   - Input: S3 config object existence check returns one or more existing config keys, metadata may be absent, `force=false`.
   - Expected: Non-zero conflict error; no config object overwrite, no DynamoDB put/update, no schedule or Lambda calls.
   - Validation logic: Assert S3 write mocks are not called after conflict detection and output identifies existing config conflict without leaking object payloads.

4. `test_create_existing_metadata_without_force_blocks_before_overwrite`
   - Maps to: AC-005.
   - Input: DynamoDB metadata repository returns existing audit in any lifecycle state, `force=false`.
   - Expected: Non-zero conflict error; no S3 config overwrite, no DynamoDB metadata mutation, no run evidence/raw-results mutation.
   - Validation logic: Assert repository update/put and S3 write/delete methods are not called.

5. `test_create_force_allows_draft_and_failed_only`
   - Maps to: AC-005F.
   - Input: Existing metadata lifecycle state parameterized as `DRAFT` and `FAILED`, existing S3 config objects, `--force`.
   - Expected: Command succeeds; S3 config objects are overwritten with validated current input; DynamoDB metadata is updated; lifecycle remains or is reset to `DRAFT` according to shared lifecycle policy; lifecycle history includes reason `force_recreate`.
   - Validation logic: Assert exact config key write calls, metadata update content, and lifecycle history append; assert no schedule/Lambda invocation.

6. `test_create_force_rejects_ineligible_lifecycle_states_before_mutation`
   - Maps to: AC-005F.
   - Input: Existing metadata lifecycle state parameterized as `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, and `CANCELLED`, existing S3 configs, `--force`.
   - Expected: Non-zero lifecycle conflict error; no S3 overwrite, no DynamoDB update, no deletes, no schedule/Lambda calls.
   - Validation logic: Assert failure occurs after metadata read but before any mutation; assert controlled lifecycle-state message.

7. `test_create_force_does_not_bypass_validation_or_safety_checks`
   - Maps to: edge case.
   - Input: Invalid JSON/schema/window/payload/production safety configuration and `--force`.
   - Expected: Validation or safety failure; no conflict overwrite, no metadata mutation, no evidence/raw-results mutation.

8. `test_create_force_preserves_run_evidence_and_raw_results_artifacts`
   - Maps to: AC-005F regression/safety.
   - Input: Existing audit with run evidence keys and `raw-results/{client_id}/{audit_id}/...` artifacts in fake S3 plus eligible lifecycle and `--force`.
   - Expected: Only the three config object keys are overwritten; no delete/put/copy operations target run evidence or `raw-results/*`; metadata update does not remove evidence references if present.
   - Validation logic: Assert S3 operation list excludes evidence/raw-results prefixes and no delete APIs are called for artifact prefixes.

9. `test_create_sanitizes_storage_errors`
    - Maps to: AC-016.
    - Input: Mock S3/DynamoDB throws provider exception containing token/header/cookie/credential/raw payload.
    - Expected: Controlled sanitized CLI error; no secret substrings in stdout/stderr/log capture.

### 3.4 Schedule Command Unit Tests

1. `test_schedule_dry_run_loads_config_and_metadata_but_does_not_mutate`
   - Maps to: AC-006, FR-010.
   - Input: Mock S3 audit config with enabled schedules; metadata `DRAFT`; `--dry-run`.
   - Expected: Loads config and metadata, reports planned schedules and transition, no EventBridge create/delete/disable and no DynamoDB update.

2. `test_schedule_success_creates_only_enabled_schedule_blocks`
   - Maps to: AC-007, AC-008.
   - Input: Audit config with enabled baseline/repeated/finalization, disabled/missing burst.
   - Expected: EventBridge creates only enabled schedule types; no inferred burst; stored schedule metadata matches created schedules.

3. `test_schedule_respects_lifecycle_eligibility`
   - Maps to: FR-006.
   - Input: Metadata in `DRAFT`, `SCHEDULED`, `CANCELLED`, `FAILED` states, parameterized.
   - Expected: Eligible state schedules; ineligible/terminal states fail before EventBridge mutation.

4. `test_schedule_prod_requires_allow_production_flag`
   - Maps to: AC-009.
   - Input: `stage=prod` or production target; config is otherwise production-safe; no `--allow-production`.
   - Expected: Non-zero production approval error; no schedule or metadata mutation.

5. `test_schedule_prod_with_allow_production_still_enforces_config_safety`
   - Maps to: FR-009.
   - Input: `--allow-production` but config lacks production allow or violates caps/method/safety.
   - Expected: Non-zero shared safety error; no mutation.

6. `test_schedule_partial_failure_rolls_back_and_marks_failed`
   - Maps to: AC-010.
   - Input: First EventBridge create succeeds; second create raises sanitized exception.
   - Expected: Rollback attempted for first schedule, failure metadata sanitized, lifecycle transition to `FAILED`, non-zero exit, no `SCHEDULED_WITH_ERRORS` persisted.

7. `test_schedule_rollback_cleanup_error_is_sanitized`
   - Maps to: AC-010, AC-016.
   - Input: Create failure and rollback delete/disable failure with secret-bearing provider message.
   - Expected: Sanitized rollback/cleanup metadata and output; lifecycle `FAILED` attempted.

8. `test_schedule_uses_stage_scheduler_group_and_resource_names`
   - Maps to: FR-002, technical design.
   - Input: Stage config with scheduler group and schedule prefix.
   - Expected: EventBridge calls include group name; schedule naming follows shared convention with deterministic truncation when needed.

### 3.5 Manual Run Command Unit Tests

1. `test_run_invokes_orchestrator_with_triggered_by_manual_without_run_id`
   - Maps to: AC-011.
   - Input: Valid IDs, scenario `baseline_health`, no `--run-id`.
   - Expected: Lambda invoked with stage-configured function and payload containing `triggered_by=manual`; `run_id` absent.

2. `test_run_validates_supplied_run_id_before_invocation`
   - Maps to: AC-012.
   - Input: Unsafe run ID containing invalid characters/path traversal/overlength per shared policy.
   - Expected: Non-zero validation failure; Lambda not invoked.

3. `test_run_includes_valid_supplied_run_id_and_optional_schedule_type`
   - Maps to: FR-007.
   - Input: Valid run ID and schedule type.
   - Expected: Lambda payload includes supplied values and `triggered_by=manual`.

4. `test_run_dry_run_reports_intended_invocation_no_lambda_call`
   - Maps to: FR-010 regression coverage.
   - Input: Valid run command with `--dry-run`.
   - Expected: Dry-run output, no Lambda invocation, payload summary sanitized.

5. `test_run_sanitizes_lambda_errors`
   - Maps to: AC-016.
   - Input: Mock Lambda raises provider exception with secret-bearing text.
   - Expected: Controlled sanitized error output and logs.

### 3.6 Cancel Command Unit Tests

1. `test_cancel_dry_run_reports_cleanup_and_cancel_transition_no_mutation`
   - Maps to: FR-010 and task requirement.
   - Input: Metadata with schedules in eligible state, `--dry-run`.
   - Expected: Planned schedule cleanup and `CANCELLED` transition shown; no delete/disable or metadata update.

2. `test_cancel_success_deletes_or_disables_schedules_retains_metadata_and_transitions_cancelled`
   - Maps to: AC-013.
   - Input: Metadata with multiple schedules and reason text.
   - Expected: Cleanup calls executed, schedule metadata retained in DynamoDB item, reason sanitized/stored, lifecycle `CANCELLED`.

3. `test_cancel_delete_failure_attempts_disable`
   - Maps to: technical reliability design.
   - Input: Mock delete failure followed by successful disable.
   - Expected: Disable called, cleanup result recorded without raw provider details, `CANCELLED` persisted.

4. `test_cancel_cleanup_partial_failure_records_intent_and_exits_three`
   - Maps to: AC-014.
   - Input: Operator requests cancel with reason text; at least one schedule cleanup succeeds and delete/disable both fail for one schedule.
   - Expected: Operator intent is recorded by persisting lifecycle `CANCELLED`; `cleanup_errors` persisted in DynamoDB with controlled fields only; schedule metadata retained; warning summary printed; process exits with code `3`.
   - Validation logic: Assert DynamoDB update includes `lifecycle_state=CANCELLED`, sanitized reason, retained schedule metadata, and sanitized `cleanup_errors`; assert stdout/stderr includes warning summary; assert exit code `3`.

5. `test_cancel_respects_lifecycle_transition_rules`
   - Maps to: FR-008.
   - Input: Eligible and terminal lifecycle states.
   - Expected: Eligible states can cancel; ineligible states fail before cleanup mutation.

### 3.7 Stage Config and AWS Mocking Tests

1. `test_stage_config_required_fields_fail_before_client_construction`
   - Maps to: AC-015.
   - Input: Stage config missing each required field, parameterized.
   - Expected: Non-zero controlled missing-field error; AWS client factory not called.

2. `test_stage_config_env_overrides_apply_with_explicit_names_and_precedence`
    - Maps to: FR-002.
    - Input: Stage config file provides baseline values; environment provides non-empty values for `RCP_AWS_REGION`, `RCP_AWS_PROFILE`, `RCP_CONFIG_BUCKET`, `RCP_AUDIT_METADATA_TABLE`, `RCP_ORCHESTRATOR_FUNCTION_NAME`, `RCP_SCHEDULER_GROUP_NAME`, and `RCP_SCHEDULE_NAME_PREFIX`.
    - Expected: Each explicit environment variable overrides the corresponding file value and is propagated to the AWS/session/resource configuration used by command services.
    - Validation logic: Assert resolved stage config contains env values, not file values; assert AWS factory receives overridden region/profile and resource clients use overridden bucket/table/function/group/prefix.

3. `test_stage_config_empty_or_invalid_env_overrides_fail_before_client_construction`
    - Maps to: AC-015, FR-002.
    - Input: Each explicit `RCP_*` override set to empty string, whitespace, or invalid resource name as applicable.
    - Expected: Controlled config error before AWS client factory/boto3 construction; invalid override does not silently fall back to file value.
    - Validation logic: Patch AWS construction to fail if called; assert no construction and deterministic override-name-specific error.

4. `test_unit_tests_block_real_aws_client_construction`
   - Maps to: test environment constraint.
   - Input: Patch `boto3.client`, `boto3.Session`, and/or AWS factory constructors to raise if called unexpectedly.
   - Expected: All command/service unit tests pass with injected fake clients only.

### 3.8 Output, Exit Code, and Sanitization Tests

1. `test_exit_codes_success_dry_run_controlled_failure_parser_failure_cleanup_warning`
    - Maps to: FR-011 UX.
    - Input: Simulated command results/errors.
    - Expected: `0` for success/dry-run, `1` for controlled validation/config/lifecycle/storage/invocation failure, `2` for parser errors, `3` for cancel cleanup partial failure warning.

2. `test_text_output_patterns_are_deterministic`
   - Maps to: CLI UX spec.
   - Input: Success, dry-run, error, warning result objects.
   - Expected: First line has `SUCCESS`, `DRY-RUN`, `ERROR`, or `WARNING`; includes stage/IDs/action summary/next step when applicable.

3. `test_no_secrets_in_outputs_logs_or_persisted_failure_metadata`
   - Maps to: AC-016.
   - Input: Errors containing `Authorization: Bearer secret`, `Cookie=`, `X-Api-Key`, AWS access key patterns, credentials, raw payload with token/password.
   - Expected: Captured stdout/stderr/logs and persisted failure/cleanup metadata contain none of the secret substrings; sanitized placeholders or controlled codes are used.

4. `test_json_output_if_implemented_is_single_sanitized_object`
   - Maps to: optional UX.
   - Input: `--output json` for success/dry-run/error.
   - Expected: One JSON object, stable snake_case fields, no ANSI/prose outside JSON, sanitized errors.

## 4. Edge Cases

The automated suite must explicitly include the following edge/boundary cases:

- Invalid JSON syntax in each provided config file.
- Missing required fields in client, audit, endpoints, and stage configs.
- Config files contain mismatched `client_id` or `audit_id` values.
- Required config file path does not exist or is unreadable.
- Stage value outside `dev|staging|prod`.
- Stage config file missing, malformed, or missing each required resource field.
- Environment override set to an empty or invalid value.
- Environment override precedence for `RCP_AWS_REGION`, `RCP_AWS_PROFILE`, `RCP_CONFIG_BUCKET`, `RCP_AUDIT_METADATA_TABLE`, `RCP_ORCHESTRATOR_FUNCTION_NAME`, `RCP_SCHEDULER_GROUP_NAME`, and `RCP_SCHEDULE_NAME_PREFIX` over stage config file values.
- Audit window start equals end, start after end, exactly 48 hours, and over 48 hours by one second.
- Unsupported endpoint methods and destructive methods without explicit approval.
- Invalid payload strategy and invalid payload safety.
- Authentication-required endpoint/config missing `auth_ref`.
- Production scheduling without `--allow-production`.
- Production config missing `allow_production_execution=true` even when CLI flag is present.
- Production destructive operation without `allow_destructive_operation=true`.
- Production concurrency/request caps above shared safe limits.
- Schedule block missing, disabled, malformed, or enabled with boundary timing values.
- Audit metadata missing during schedule/run/cancel.
- Lifecycle state is terminal or otherwise ineligible for schedule/cancel.
- Existing S3 config object conflict during create without `--force`.
- Existing DynamoDB audit metadata conflict during create without `--force`.
- `--force` supplied while validation or safety checks fail.
- `--force` supplied for eligible lifecycle states `DRAFT` and `FAILED`.
- `--force` supplied for ineligible lifecycle states `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, and `CANCELLED`.
- `--force` create preserving run evidence and `raw-results/*` artifacts.
- `--force` create lifecycle history append reason `force_recreate`.
- Schedule name deterministic truncation boundary.
- EventBridge schedule creation partial failure and rollback failure.
- Cancellation cleanup partial failure with `CANCELLED` transition, persisted `cleanup_errors`, warning summary, and exit code `3`.
- Manual run with unsupported scenario type.
- Manual run with unsafe supplied `run_id`.
- Dry-run command with invalid config/lifecycle must fail validation rather than reporting planned mutation.
- AWS/provider exceptions containing secrets must be sanitized in output, logs, and persisted metadata.

## 5. Test Types Covered

| Test Type | In Scope | Notes |
| --- | --- | --- |
| Unit - parser | Yes | Covers argparse command tree, required flags, choices, parser exits, request construction. |
| Unit - validation service | Yes | Covers JSON syntax, schema, required fields, ID consistency, audit window, endpoints, payloads, production safety, auth refs. |
| Unit - command/service behavior | Yes | Covers validate/create/schedule/run/cancel success, dry-run, failure paths using fake dependencies. |
| Unit - AWS boundary mocks | Yes | All S3, DynamoDB, EventBridge Scheduler, Lambda, and boto3 construction mocked/faked. Real AWS is explicitly out of scope. |
| Unit - output/sanitization | Yes | Covers text renderer, optional JSON renderer, no secrets, controlled messages, exit code mapping. |
| Integration - real AWS | No | Out of scope per product and technical design. Future ephemeral AWS integration tests may be added separately. |
| UI/browser | No | Not applicable; CLI-only feature. |
| Performance/load | No | Not required for CLI MVP; no long-running or high-throughput behavior specified. |
| Security | Limited unit security coverage | Sanitization and no-secret-output assertions included; no auth/RBAC in scope. |
| Regression | Yes | Existing Phase 1 run ID/orchestrator behavior, Phase 2 payload/safety validators, and Phase 3 lifecycle/scheduling/cancellation semantics are protected through targeted regression tests. |

## 6. Coverage Justification

This plan covers every product acceptance criterion AC-001 through AC-016 and the explicit task coverage requirements:

- Unit tests for argument parsing are covered in section 3.1.
- Unit tests for validation command are covered in section 3.2.
- Unit tests for create dry-run are covered in section 3.3.
- Unit tests for schedule dry-run are covered in section 3.4.
- Unit tests for cancel dry-run are covered in section 3.6.
- Mock AWS clients and no real AWS calls are covered in sections 3.7 and across command/service scenarios.
- Validation command checks JSON syntax, schemas/required fields, client/audit ID consistency, audit window <=48h, endpoint methods, payload strategy, payload safety, production restrictions, and auth refs in section 3.2.
- Create non-dry-run mocked S3 and DynamoDB behavior, including non-force S3/DynamoDB conflict blocking, force recreation eligibility, S3 config overwrite, DynamoDB metadata update, lifecycle history reason `force_recreate`, validation/safety enforcement, and evidence/raw-results preservation, is covered in section 3.3.
- Schedule loading, lifecycle enforcement, enabled-block-only creation, metadata persistence, SCHEDULED transition, partial failure rollback, and FAILED transition are covered in section 3.4.
- Manual run orchestrator invocation with `triggered_by=manual` and run ID validation is covered in section 3.5.
- Cancel cleanup behavior, metadata retention, CANCELLED transition, cleanup error recording, cleanup partial failure warning summary, and exit code `3` are covered in section 3.6.
- No-secret output/logging, sanitization, clear exit codes, `--stage` support for dev/staging/prod, and explicit `RCP_*` environment override precedence are covered in sections 3.1, 3.7, and 3.8.

Regression risks to protect:

- CLI command handlers accidentally duplicate or diverge from shared validation, lifecycle, production-safety, run-ID, and naming rules.
- Dry-run paths skip validation or accidentally mutate AWS-backed dependencies.
- Stage config failures occur after AWS client construction, causing credential/profile lookups or real client creation in tests.
- Scheduling code infers schedules when blocks are missing/disabled, especially finalization behavior from existing Phase 3 builders.
- Partial schedule failures persist an unsupported `SCHEDULED_WITH_ERRORS` state or fail to rollback created schedules.
- Create command starts scheduling/execution or overwrites existing metadata before conflict checks.
- Force create accidentally bypasses validation/safety checks, overwrites active/terminal audits, omits lifecycle history reason `force_recreate`, or deletes/overwrites run evidence and `raw-results/*` artifacts.
- Stage config environment variables use undocumented names, fail to take precedence over file values, or silently ignore invalid override values.
- Manual run includes unsafe run IDs or mistakenly generates a run ID in the CLI instead of leaving it to the orchestrator when omitted.
- Cancellation removes schedule metadata instead of retaining it for traceability.
- Cancellation cleanup partial failure fails to persist `CANCELLED`, loses operator intent, omits sanitized `cleanup_errors`, returns the wrong exit code, or fails to print an operator warning summary.
- Provider exceptions, raw payloads, auth headers, cookies, credentials, or tokens leak into stdout/stderr/logs/persisted error metadata.
- Production scheduling proceeds without explicit `--allow-production` or without config-level production approvals.
- Existing Phase 1 orchestrator run ID policy, Phase 2 payload safety, and Phase 3 lifecycle/schedule/cancellation behavior regress due to CLI-specific adapters.

Planned evidence when tests are later implemented/executed:

- Test command output from the repository test runner.
- Per-test pass/fail counts.
- Captured stdout/stderr/log assertions for output and sanitization tests.
- Mock call assertions proving no real AWS calls and no unintended mutations.
- Failure classification in `docs/qa/operator_cli_rcp_test_report.md` if any execution fails.
