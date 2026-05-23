# Test Plan

## 1. Feature Overview

Feature: `rcp config init`

Sources:
- Product spec: `docs/product/config_init_product_spec.md`
- Architecture design: `docs/architecture/config_init_technical_design.md`

Goal: validate that `rcp config init` generates a local-only starter audit configuration set under `<output-dir>/<client_id>/` with safe IDs, safe defaults, schema-valid JSON, deterministic directory semantics, overwrite protection, human/JSON output, git safety guidance, and no AWS/network side effects.

QA gate result for planning: acceptance criteria are testable and non-contradictory. No QA execution is included in this planning phase.

System boundaries:
- In scope: local CLI parsing, generation service, ID/slug utilities, JSON template generators, local-template validation behavior, filesystem writes, output rendering, no-AWS safety checks.
- Out of scope: AWS uploads, DynamoDB metadata, EventBridge schedules, Lambda invocations, secrets resolution, automatic `.gitignore` mutation, customer-facing UI/API.

## 2. Acceptance Criteria Mapping

| Acceptance Criterion | Validation approach | Required automated coverage |
| --- | --- | --- |
| AC-001 Required Argument Generation | Invoke command/service with required args and assert three files are created. | Unit/API CLI tests using `tmp_path`. |
| AC-001A Output Directory Semantics | Force deterministic IDs and assert root is `<output-dir>/<client_id>/`, not `--output-dir`. | Filesystem test with deterministic short ID/date. |
| AC-002 Generated IDs | Assert same `client_id` and `audit_id` appear in output and applicable generated files. | Generation + CLI output tests. |
| AC-003 ID Safety | Fuzz representative unsafe client names and assert safe slug/ID regex or clean failure. | Unit tests for slug/id utilities and end-to-end path safety. |
| AC-004 Default Endpoint Template | Generate without sample flag and assert `endpoints: []`, metadata present, no secrets. | Generator + validation tests. |
| AC-005 Sample Endpoint Template | Generate with sample flag for dev/staging/prod/production and assert exactly one safe GET placeholder endpoint, no auth refs/secrets/production URL. | Generator + CLI integration tests. |
| AC-006 Safe Defaults | Inspect `client_config.json` and `audit_config.json` for disabled production/destructive execution, conservative caps, no AWS refs. | Schema/content assertions and secret/AWS string scans. |
| AC-006A Production-Oriented Template Safety | Run for `prod` and `production`; assert local success with safe gates disabled and conservative schedules/caps. | Parametrized generation and validation tests. |
| AC-007 Schema Validity | Run project config validation against generated default, sample, prod, and production templates without AWS credentials/network. | Unit/API validation contract tests. |
| AC-008 Overwrite Protection | Existing final generated client root fails non-zero without modifying sentinel files. | Filesystem conflict tests. |
| AC-009 Explicit Overwrite | Existing final generated client root succeeds with `--overwrite`, only expected files replaced, output reports overwritten target. | Filesystem overwrite tests. |
| AC-010 No AWS Calls | Monkeypatch AWS client construction/loaders to fail if touched for success and local-failure paths. | Security tests and import-boundary tests. |
| AC-011 JSON Output | `--output json` stdout parses as JSON and includes IDs, root, files, warning; no stray text/secrets. | CLI renderer/API tests. |
| AC-012 Git Safety Warning | Text and JSON output include warning recommending `.local-configs/` and adding `.local-configs/` to `.gitignore`; no automatic mutation. | Output tests plus repository file mutation guard. |

## 3. Test Scenarios

### CLI argument parsing and command dispatch

1. `test_config_init_parser_accepts_required_args`
   - Purpose: prove `rcp config init` is registered under existing `config` group.
   - Input: `config init --client-name "Demo Client" --target-environment dev --output-dir <tmp>`.
   - Expected: parser sets `config_command == "init"`, captures required args, no `--stage` required.
   - Maps to: AC-001.

2. `test_config_init_parser_accepts_optional_args`
   - Input: required args plus `--timezone America/New_York --include-sample-endpoints --overwrite --output json`.
   - Expected: optional flags/values captured correctly; output choices include `text` default and `json`.
   - Maps to: AC-001, AC-011.

3. `test_config_init_parser_rejects_missing_required_args`
   - Inputs: omit each required argument individually.
   - Expected: argparse exits `2`; no dispatch/filesystem writes.
   - Maps to: FR-001, CLI contract.

4. `test_config_init_parser_target_environment_choices`
   - Inputs: `dev`, `staging`, `prod`, `production`, unsupported values, empty/whitespace where reachable.
   - Expected: supported values accepted; unsupported values fail before writes.
   - Maps to: AC-006A, edge cases.

### ID generation and slug safety

5. `test_generate_client_id_matches_safe_format`
   - Input: deterministic short ID `a8f3c2d1`, client name `Demo Client`.
   - Expected: `client_demo_client_a8f3c2d1`; lowercase; regex `^client_[a-z0-9]+(?:_[a-z0-9]+)*_[a-f0-9]{8,}$`.
   - Maps to: AC-002, AC-003.

6. `test_generate_audit_id_matches_date_format`
   - Input: date `2026-05-23`, deterministic short ID `ef56ab78`.
   - Expected: `audit_20260523_ef56ab78`; regex `^audit_\d{8}_[a-f0-9]{8,}$`.
   - Maps to: AC-002.

7. `test_slug_generation_removes_unsafe_path_and_shell_chars`
   - Inputs: names with spaces, uppercase, punctuation, unicode punctuation, `/`, `\\`, `..`, `;`, `&`, `|`, `$()`, quotes.
   - Expected: generated slug/ID contains only safe lowercase tokens and cannot create traversal or path separators.
   - Maps to: AC-003.

8. `test_empty_slug_client_name_fails_before_write`
   - Inputs: names that slugify to empty, e.g. `!!!`, whitespace-only, path separators only.
   - Expected: clear invalid argument error; output dir remains unchanged.
   - Maps to: edge cases.

### Directory generation and local filesystem behavior

9. `test_config_init_creates_expected_directory_tree`
   - Input: deterministic `client_id` and `audit_id`, `--output-dir <tmp>/.local-configs/demo-client`.
   - Expected files:
     - `<output-dir>/<client_id>/client_config.json`
     - `<output-dir>/<client_id>/audits/<audit_id>/audit_config.json`
     - `<output-dir>/<client_id>/audits/<audit_id>/endpoints.json`
   - Validation: all paths are under final generated root and no files are written directly to `--output-dir` except the generated client root directory.
   - Maps to: AC-001, AC-001A.

10. `test_output_dir_existing_file_fails_before_write`
    - Input: `--output-dir` points to an existing file.
    - Expected: non-zero local validation error; file unchanged.
    - Maps to: edge cases.

11. `test_partial_write_failure_does_not_report_success`
    - Input: monkeypatch file write/mkdir to fail after first path calculation or first file write.
    - Expected: local write error, non-zero, no success output, best-effort cleanup of invocation-created files where implemented.
    - Maps to: edge cases, reliability.

### Overwrite protection

12. `test_existing_generated_root_fails_without_overwrite_and_preserves_files`
    - Setup: create deterministic final root and sentinel files.
    - Input: same deterministic IDs without `--overwrite`.
    - Expected: non-zero `LOCAL_FILE_EXISTS`-class error; sentinel contents and mtimes unchanged.
    - Maps to: AC-008.

13. `test_existing_generated_root_succeeds_with_overwrite`
    - Setup: existing deterministic final root with old generated files and unrelated sentinel file.
    - Input: same deterministic IDs with `--overwrite`.
    - Expected: success, `overwritten=true`, only the three expected generated files replaced; unrelated sentinel remains unchanged.
    - Maps to: AC-009.

### Generated JSON schema and content validity

14. `test_generated_client_config_required_fields_and_safe_defaults`
    - Expected fields: `client_id`, `client_name`, execution environment/target environment, request defaults, payload safety defaults, allowed HTTP methods, sanitization, operational caps.
    - Expected defaults: `allow_production_execution=false`, `allow_destructive_operation=false`, `max_concurrency=5`, `timeout_seconds=10`.
    - Negative checks: no literal secrets, auth tokens, passwords, API keys, cookies, private keys, credentials, AWS ARNs/resource names.
    - Maps to: AC-006, AC-007.

15. `test_generated_audit_config_required_fields_and_safe_defaults`
    - Expected fields: `audit_id`, `client_id`, timezone, 48-hour max audit window placeholder, baseline/burst/repeated/finalization schedules, operational caps.
    - Expected defaults: baseline enabled at 15 minutes, burst disabled/minimal, repeated enabled with `runs_per_day=1`, conservative caps, no active runtime timestamps, no AWS references.
    - Maps to: AC-006, AC-007.

16. `test_generated_endpoints_default_empty_array_is_valid`
    - Input: omit `--include-sample-endpoints`.
    - Expected: `endpoints.json` has identifying metadata and `endpoints: []`; config validation succeeds in local-template mode.
    - Maps to: AC-004, AC-007.

17. `test_generated_sample_endpoint_is_safe_placeholder`
    - Input: include sample endpoints for `dev` and `staging`.
    - Expected: exactly one endpoint, `method=GET`, `url=https://example.com/health`, target env metadata, static payload strategy, destructive flags false, `auth_required=false`, empty headers/no `auth_ref`.
    - Maps to: AC-005.

18. `test_production_oriented_templates_are_safe_by_default`
    - Input: `--target-environment prod` and `production`, with and without sample endpoints.
    - Expected: local generation succeeds; production/destructive gates disabled; sample URL remains `https://example.com/health`; no real production hostnames/auth refs; caps are conservative; dangerous schedules not enabled.
    - Maps to: AC-006A, AC-007.

19. `test_generated_configs_pass_project_validation_without_aws`
    - Input: generated config sets for default empty endpoints, sample endpoints, prod, production.
    - Expected: `AuditConfigValidationService.validate_configs(..., template_mode=True or equivalent local-template mode)` succeeds without AWS credentials/network; execution-time validation remains strict where applicable.
    - Maps to: AC-007, regression protection.

### Output rendering

20. `test_text_output_includes_operator_required_information`
    - Input: successful command in default output mode.
    - Expected stdout includes generated `client_id`, `audit_id`, final generated root, each generated file path, and git safety warning.
    - Maps to: AC-002, AC-010, AC-012.

21. `test_json_output_is_parseable_and_complete`
    - Input: successful command with `--output json`.
    - Expected stdout is valid JSON only; contains `command`, `stage: null`, `status`, `client_id`, `audit_id`, `output_dir`, `generated_files`, `overwritten`, `warning`; contains no secrets; stderr has no required JSON fragments.
    - Maps to: AC-011, AC-012.

22. `test_json_error_output_is_parseable_for_local_failures`
    - Input: `--output json` plus existing root without overwrite, invalid timezone, or invalid client name.
    - Expected error payload is JSON-parseable and sanitized; exit non-zero.
    - Maps to: architecture error contract.

23. `test_gitignore_is_not_modified`
    - Input: successful generation in a temporary copied or isolated repo root.
    - Expected `.gitignore` is not created or modified automatically; output still recommends `.local-configs/` and `.gitignore` exclusion.
    - Maps to: AC-012 and out-of-scope constraint.

### No AWS calls / side-effect isolation

24. `test_config_init_success_does_not_touch_aws_or_stage_loader`
    - Setup: monkeypatch `StageConfigLoader.load`, `AwsClientFactory.__init__`, `boto3.client`, `boto3.Session`, and constructors/clients for S3, DynamoDB, Secrets Manager, Lambda, Scheduler to raise `AssertionError` if called.
    - Input: successful local generation.
    - Expected: test passes with no patched function called.
    - Maps to: AC-010.

25. `test_config_init_local_failure_does_not_touch_aws_or_stage_loader`
    - Setup: same fail-fast monkeypatches.
    - Inputs: invalid client name, invalid timezone, existing root conflict.
    - Expected: local failure occurs without AWS/stage calls.
    - Maps to: AC-010.

26. `test_config_init_import_boundary_excludes_aws_modules`
    - Input: inspect/import `release_confidence_platform.operator_cli.config_init` and generators.
    - Expected: no imports/references to `config.stage_config`, `storage.aws_client_factory`, S3, Secrets Manager, DynamoDB, EventBridge Scheduler, Lambda clients, or direct `boto3` usage.
    - Maps to: AC-010, security.

### Regression checks against existing validation/lifecycle assumptions

27. `test_local_template_validation_does_not_weaken_execution_validation`
    - Purpose: ensure allowing empty endpoint arrays/prod local templates does not permit unsafe execution flows.
    - Input: generated prod template with `allow_production_execution=false` through any execution-time validation/scheduling path, if available.
    - Expected: local-template validation succeeds, but execution-time validation or scheduling still blocks unsafe production execution/non-executable endpoints.
    - Maps to: architecture risk, AC-007.

28. `test_existing_cli_commands_still_require_stage_where_applicable`
    - Purpose: protect current CLI assumptions while `config init` remains stage-free.
    - Input: existing commands such as `audit run`, `audit cancel`, `config list/download` without required `--stage`.
    - Expected: existing requirements unchanged; only `config init` requires no stage/AWS config.
    - Maps to: regression.

29. `test_existing_scheduling_lifecycle_tests_still_pass`
    - Purpose: detect regressions in lifecycle/schedule validation caused by local-template validation changes.
    - Expected: existing phase 3 lifecycle/scheduling tests pass unchanged.
    - Maps to: regression.

## 4. Edge Cases

- Client names that slugify to empty fail with a clear validation error and no writes.
- Client names containing path separators, traversal sequences, shell metacharacters, quotes, whitespace, or uppercase characters cannot influence filesystem paths beyond the sanitized generated ID.
- `--target-environment prod` and `--target-environment production` are accepted but remain local safe templates with production execution disabled.
- Unsupported or empty target environments fail before writes.
- Invalid timezone values fail before writes; valid IANA zones and explicit `UTC` pass.
- Existing final generated root fails by default without modifying contents.
- `--overwrite` replaces only expected generated files under `<output-dir>/<client_id>/`.
- Default `endpoints: []` remains schema-valid in local-template validation.
- Sample endpoint generation never emits real production endpoints, `auth_ref`, headers containing auth, tokens, credentials, cookies, passwords, API keys, or private keys.
- JSON output is parseable with warning text represented as a JSON field only.
- Human-readable output is clear and includes root and generated file paths.
- `.gitignore` is recommended but not modified.
- No `StageConfigLoader`, AWS factory, boto3, S3, DynamoDB, Secrets Manager, Lambda, EventBridge Scheduler, or network calls are touched in success or local-failure paths.
- Simulated filesystem failures return non-zero and do not report success.

## 5. Test Types Covered

- Unit tests:
  - Parser behavior, slug/id utilities, config generators, safe defaults, validation error paths.
  - Recommended files: `tests/unit/test_config_init_cli.py`, `tests/unit/test_config_init_generation.py`.
- API/contract tests:
  - CLI command contract, output rendering, JSON output, schema validation against generated files.
  - Recommended file: `tests/api/test_config_init_contract.py`.
- Security tests:
  - No AWS client construction/API calls, no secrets in generated configs/output, import-boundary restrictions.
  - Recommended file: `tests/security/test_config_init_no_aws.py`.
- Regression tests:
  - Existing operator CLI command behavior, validation/lifecycle/scheduling assumptions, production execution safeguards.
  - Existing suites plus targeted regression tests in unit/API files.
- Performance tests:
  - Not required for this local generator feature; generation is small local filesystem work. If later required, add a smoke perf guard under `tests/perf/` to ensure generation completes within a reasonable local threshold without network calls.

Discoverable commands to run during QA execution phase after implementation:

```bash
python -m pytest tests/unit/test_config_init_cli.py tests/unit/test_config_init_generation.py tests/api/test_config_init_contract.py tests/security/test_config_init_no_aws.py
python -m pytest tests/unit/test_operator_cli_rcp.py tests/api/test_operator_cli_rcp_contract.py
python -m pytest tests/unit tests/api tests/security
python -m pytest tests/integration/test_phase3_scheduling_lifecycle.py tests/integration/test_phase3_cancellation_finalization.py tests/integration/test_phase3_scheduled_execution.py tests/integration/test_phase3_duplicate_delivery.py
```

Manual/diagnostic commands to use only after implementation if the package is installed or runnable in the active environment:

```bash
rcp config init --client-name "Demo Client" --target-environment dev --output-dir .local-configs/demo-client
rcp config init --client-name "Acme Payments" --target-environment production --timezone UTC --include-sample-endpoints --output-dir .local-configs/acme-payments --output json
```

## 6. Coverage Justification

The planned coverage directly traces every product acceptance criterion and architecture risk to automated tests. The plan emphasizes failure-before-write behavior, deterministic ID injection for repeatable assertions, schema validation of generated artifacts, and strict no-AWS guardrails. Production-oriented templates receive dedicated positive and negative coverage because they are allowed as local templates but must not weaken execution safety.

Failure classification guidance for QA loop:

- Application Bug:
  - Missing/incorrect CLI args, unsafe ID/slug output, wrong directory root semantics, schema-invalid generated JSON, unsafe defaults, generated secrets/auth refs, missing git warning, AWS/stage/boto3 touched, overwrite protection modifies files, JSON output not parseable, regression in execution-time production safeguards.
  - Severity: blocking if it violates AC-001 through AC-012, data safety, no-AWS, overwrite, schema validity, or production safety.
- Test Bug:
  - Test assumes undocumented field ordering where schema does not require it, brittle text matching beyond required output content, incorrect monkeypatch target after implementation path differs but behavior is compliant.
  - Severity: fix test and re-run before sign-off.
- Environment Issue:
  - Missing Python 3.11 environment, dependency installation problem, filesystem permission issue unrelated to product behavior, unavailable console script before package install.
  - Severity: block sign-off until reproducible execution evidence is available.
- Flaky Test:
  - Non-deterministic ID/date assertions not properly injected, timing/mtime checks unstable, tests depend on global working directory or pre-existing `.local-configs/` state.
  - Severity: stabilize before sign-off; do not approve with unresolved flakiness.

QA sign-off requirements for the later execution phase:
- All critical tests for AC-001 through AC-012 pass.
- Evidence includes pytest output and any relevant CLI stdout/stderr samples.
- No blocking defects, major regressions, unresolved failures, or unexplained flakiness remain.
