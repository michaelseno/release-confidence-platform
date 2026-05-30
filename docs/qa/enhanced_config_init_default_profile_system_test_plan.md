# Test Plan

## 1. Feature Overview

Feature: Enhanced `rcp config init` Default Profile System
Workflow classification: New Feature
Primary validation target: operator CLI local configuration initialization.

The feature enhances `rcp config init` to generate validation-safe local starter workspaces from reusable defaults profiles. The command must resolve omitted, named, and explicit-path defaults profiles; merge profile/operator defaults with CLI overrides using deterministic precedence; generate schema-valid local config files under an isolated client workspace; protect existing output directories; support text and JSON output; and guarantee no AWS interactions.

Source artifacts:

- Product spec: `docs/product/enhanced_config_init_default_profile_system_product_spec.md`
- Technical design: `docs/architecture/enhanced_config_init_default_profile_system_technical_design.md`
- CLI UX spec: `docs/uiux/enhanced_config_init_default_profile_system_design_spec.md`

Test artifact scope:

- Unit tests for profile resolution, profile validation, merge/precedence, ID generation, slug/path safety, and no-AWS enforcement.
- CLI/API contract tests for command behavior, generated files, overwrite behavior, output rendering, and validation integration.
- Regression tests for existing config validation and CLI behavior impacted by the new command contract.
- No application code implementation is included in this plan.

## 2. Acceptance Criteria Mapping

| AC ID | Requirement Summary | Planned Test Coverage | Priority |
| --- | --- | --- | --- |
| AC-001 | Omitted `--defaults` uses `dev` and generates all local files. | CLI contract test: `rcp config init --client-name "Acme"`; assert selected profile `dev`, exit `0`, workspace and three files exist. | Critical |
| AC-002 | Named profile `staging` loads staging defaults unless overridden. | Unit profile resolver tests for `dev`, `staging`, `prod`; CLI/service test asserting staging-derived target environment, timezone/rate/schedule defaults. | Critical |
| AC-003 | Explicit defaults JSON path is treated as file path. | Unit resolver tests for values containing `/`, `\`, or ending `.json`; service test using temp custom profile and asserting profile values appear in output/configs. | Critical |
| AC-004 | CLI overrides take precedence over profile `operator_defaults`. | Unit precedence tests and CLI JSON-mode test for `--output-dir ./tmp-configs --timezone Asia/Hong_Kong --output json`; assert output dir, timezone, and parseable JSON. | Critical |
| AC-005 | Required nested directory structure is generated. | Filesystem assertions for `.local-configs/<client_id>/client_config.json`, `.local-configs/<client_id>/audits/<audit_id>/audit_config.json`, and `endpoints.json`. | Critical |
| AC-006 | No flat `.local-configs/client_config.json`. | Negative filesystem assertion after default run and custom output-dir run. | Critical |
| AC-007 | Generated IDs match safe formats. | Unit/service tests with mixed-case, spaces, punctuation, path-like names; assert regex, lowercase, no whitespace/separators. | Critical |
| AC-008 | Missing/invalid profiles fail before writes. | Unit/profile validation tests for missing file, invalid JSON, unsupported named profile, missing required fields; assert non-zero/no generated files. | Critical |
| AC-009 | Generated configs pass schema and audit validation without AWS. | Integration/service tests invoking project validation on generated `client_config`, `audit_config`, `endpoints` with `template_mode=True`; monkeypatch AWS clients to fail if touched. | Critical |
| AC-010 | Empty endpoints by default. | File content assertion: `endpoints` array exists and is empty; no secrets/real URLs. | High |
| AC-011 | Sample endpoints are mock-only and safe. | CLI/service test with `--include-sample-endpoints`; assert example/mock hosts only, safe methods, no auth/secrets/tokens/destructive operations. | High |
| AC-012 | Production profile remains safe. | Prod profile tests with and without sample endpoint flag; assert `allow_production_execution=false`, `allow_destructive_operation=false`, conservative caps, safe schedules, no real endpoints, warning output. | Critical |
| AC-013 | Existing target directory fails without `--overwrite`. | Deterministic shortid/today service test or pre-created output root; assert non-zero and file mtimes/content unchanged. | Critical |
| AC-014 | `--overwrite` replaces and reports target path. | Pre-existing workspace test with `--overwrite`; assert files replaced only under expected paths and output includes overwritten path/flag. | High |
| AC-015 | No AWS calls. | Monkeypatch `AwsClientFactory.__init__`, `boto3.client`, `boto3.resource`, and AWS service/upload/scheduler call sites to raise; run success and failure paths. | Critical |
| AC-016 | Output includes operator guidance. | Text output assertions for IDs, workspace path, files, profile, local-only/no-upload/no-schedule safety, next steps; JSON output schema assertions for equivalent non-secret fields. | High |

Additional UX acceptance criteria from the CLI UX spec are covered by output-rendering tests: stable text headings, JSON-only stdout in JSON mode, stable error codes/reasons/next steps, production warning copy, and readable no-color output.

HITL S3 storage guidance correction coverage added after the S3 write failure report:

| HITL ID | Requirement Summary | Planned Test Coverage | Priority |
| --- | --- | --- | --- |
| HITL-S3-001 | S3 `NoSuchBucket` / missing bucket failures produce actionable structured storage config guidance, not generic-only retry guidance. | API/unit test with synthetic botocore `ClientError(Code=NoSuchBucket)` on `put_object`; assert `STORAGE_CONFIG_ERROR`, sanitized diagnostic context, and CLI next step referencing `config/stages/dev.json config_bucket`, `RCP_CONFIG_BUCKET=<real-dev-bucket>`, bucket existence/region, and S3 permissions. | Critical |
| HITL-S3-002 | S3 `AccessDenied` / permission failures produce actionable structured permission guidance. | API/unit test with synthetic `ClientError(Code=AccessDenied)`; assert `STORAGE_PERMISSION_ERROR`, permission-denied message, and CLI renderer includes `s3:PutObject` and `s3:HeadObject` permissions for `configs/<client_id>/*`. | Critical |
| HITL-S3-003 | Generic S3 failures remain structured with sanitized bounded diagnostic context. | API/unit test with synthetic generic S3 code/message containing bearer-token text; assert `STORAGE_ERROR`, sanitized `aws_error_code`, redacted message, no payload secret leakage, and storage-specific next step. | Critical |
| HITL-S3-004 | Diagnostics do not leak secrets, credentials, full client/audit object keys, or payload secret values. | Negative assertions in S3 guidance tests for injected token/password/bearer values and full key segments. | Critical |

## 3. Test Scenarios

### 3.1 Unit Test Scenarios: Profile Resolution and Validation

Target suggested file: `tests/api/test_config_init_profiles.py` or narrower unit path if the repository has a unit-test convention.

| Test ID | Purpose | Input | Expected Output / Validation Logic | Maps To |
| --- | --- | --- | --- | --- |
| UT-PR-001 | Omitted defaults resolves to bundled `dev`. | Service/loader call with defaults omitted/`None`. | Resolved profile name `dev`; source path `config/defaults/dev.json`; no writes during resolution. | AC-001, FR-002 |
| UT-PR-002 | Named `dev`, `staging`, `prod` resolve as bundled profiles. | `--defaults dev`, `staging`, `prod`. | Each maps to `config/defaults/<name>.json`; not treated as relative path. | AC-002 |
| UT-PR-003 | Values with POSIX path separator resolve as explicit file path. | `config/defaults/high-volume-staging.json`, `./dev.json`. | Resolver marks source as path and reads exact file. | AC-003 |
| UT-PR-004 | Values with Windows separator resolve as explicit file path. | `config\\defaults\\custom.json`. | Resolver treats as path-like, not named profile. | AC-003 |
| UT-PR-005 | `.json` value without separator resolves as explicit file path. | `custom_profile.json`. | Resolver treats as file path, not unsupported named profile. | AC-003 |
| UT-PR-006 | Unsupported non-path profile fails. | `--defaults qa`. | Stable invalid profile error; no generated files. | AC-008 |
| UT-PR-007 | Missing explicit profile file fails before writes. | Temp path not present. | Non-zero/config load error; output includes corrective guidance; output root absent/unchanged. | AC-008 |
| UT-PR-008 | Invalid JSON profile fails before writes. | Temp profile with malformed JSON. | Invalid JSON error; no generated files. | AC-008 |
| UT-PR-009 | Non-object JSON profile fails. | Profile file containing `[]` or string. | Profile schema validation error; no writes. | AC-008 |
| UT-PR-010 | Missing required profile fields fails. | Profile missing `profile_name`, `target_environment`, `operator_defaults`, schedule/request/rate/payload safety fields. | Validation error names missing fields; no generated files. | AC-008, FR-003 |
| UT-PR-011 | Secret-bearing profile fields are rejected. | Profile contains keys/values such as `password`, `api_key`, `authorization`, `cookie`, `private_key`, literal token. | Unsafe profile validation error; no writes; no secret echoed in output. | AC-009, security |
| UT-PR-012 | Production unsafe profile values are rejected or normalized safe. | Prod/production profile with executable/destructive flags or aggressive caps. | Fails validation or generated configs force safe values per spec; no unsafe success. | AC-012 |

### 3.2 Unit Test Scenarios: `operator_defaults` and Override Precedence

Target suggested file: `tests/api/test_config_init_profiles.py` or `tests/api/test_config_init_contract.py`.

| Test ID | Purpose | Input | Expected Output / Validation Logic | Maps To |
| --- | --- | --- | --- | --- |
| UT-PREC-001 | Profile `operator_defaults` apply when CLI values omitted. | Custom profile with `operator_defaults.output_dir`, `timezone`, `output`. | Workspace root, generated timezone, and output format reflect profile values. | AC-002, FR-004 |
| UT-PREC-002 | CLI explicit output dir overrides profile output dir. | Profile output dir `.profile-configs`; CLI `--output-dir ./tmp-configs`. | Files are written under `./tmp-configs/<client_id>`, not profile dir. | AC-004 |
| UT-PREC-003 | CLI explicit timezone overrides profile timezone. | Profile `UTC`; CLI `--timezone Asia/Hong_Kong`. | `audit_config.timezone` and audit window timezone are `Asia/Hong_Kong`. | AC-004 |
| UT-PREC-004 | CLI explicit output format overrides profile output. | Profile `output: text`; CLI `--output json`. | Stdout parseable JSON only; output payload records `output_format=json`. | AC-004, AC-016 |
| UT-PREC-005 | Hardcoded safe fallback used only for unresolved values. | Minimal custom profile omits optional `operator_defaults.output_dir/timezone/output` if validator permits. | Defaults resolve to `.local-configs`, `UTC`, `text`; test asserts profile values were absent and fallback used. | FR-004 |
| UT-PREC-006 | Invalid timezone override fails before writes. | CLI `--timezone Not/AZone`. | Stable invalid timezone error; no generated files. | Edge cases |
| UT-PREC-007 | Invalid profile timezone fails before writes. | Profile `operator_defaults.timezone: Invalid/Zone`; no CLI override. | Profile/config validation error; no writes. | FR-011 |

### 3.3 Generated Config Validity and Safety

| Test ID | Purpose | Input | Expected Output / Validation Logic | Maps To |
| --- | --- | --- | --- | --- |
| INT-CFG-001 | Generated `client_config.json` is schema-valid. | Successful minimal dev run. | Load JSON; validate with project client/config validation path; required fields present; target env from profile. | AC-009 |
| INT-CFG-002 | Generated `audit_config.json` is schema-valid and audit-validation compatible. | Successful dev/staging/prod runs. | Validate via `AuditConfigValidationService.validate_configs(..., template_mode=True)`; baseline, burst, repeated, finalization schedules present. | AC-009 |
| INT-CFG-003 | Generated `endpoints.json` is schema-valid. | Default run. | Endpoints array present/empty; metadata IDs match generated IDs. | AC-009, AC-010 |
| INT-CFG-004 | No secrets in any generated config or output. | All successful modes, including samples. | Recursive key/value scan for `password`, `token`, `secret`, `api_key`, `authorization`, `cookie`, `private_key`, credential-like values; none present except approved non-secret placeholders/references if schema requires. | AC-009, AC-010, AC-011 |
| INT-CFG-005 | Local-only safety flags are present and false. | Dev/staging/prod successful runs. | Assert `allow_production_execution=false`, `allow_destructive_operation=false`; output states no AWS/upload/schedules. | AC-012, AC-016 |
| INT-CFG-006 | Generated configs do not imply schedules were registered. | Successful run. | Config contains schedule defaults as data only; output states no schedules created. | FR-008, AC-016 |
| INT-CFG-007 | Partial validation failure is not reported as success. | Monkeypatch validation service to return/fail invalid generated config. | Command exits non-zero; no success language; no final generated files. | FR-011 |

### 3.4 Directory Structure and Filesystem Behavior

| Test ID | Purpose | Input | Expected Output / Validation Logic | Maps To |
| --- | --- | --- | --- | --- |
| FS-001 | Default workspace structure is isolated by client ID. | `rcp config init --client-name "Acme"`. | `.local-configs/<client_id>/client_config.json` and nested `audits/<audit_id>/...` exist. | AC-005 |
| FS-002 | Flat root-level client config is never generated. | Default run. | `.local-configs/client_config.json` does not exist. | AC-006 |
| FS-003 | Custom output dir remains nested under client ID. | `--output-dir ./tmp-configs`. | `./tmp-configs/<client_id>/client_config.json`, not `./tmp-configs/client_config.json`. | AC-005, AC-006 |
| FS-004 | Raw client name cannot affect filesystem path. | Client names containing spaces, uppercase, punctuation, path separators, traversal sequences. | Path uses sanitized `client_id` only; no directories created from raw name segments. | AC-007 |
| FS-005 | Existing workspace fails without overwrite and does not mutate. | Deterministic IDs with pre-created files. | Non-zero; file content/mtime unchanged; no additional generated files. | AC-013 |
| FS-006 | `--overwrite` replaces expected generated files only. | Same deterministic workspace with `--overwrite`. | Success; output reports overwritten target path; unrelated files under output parent are untouched. | AC-014 |
| FS-007 | Write failure rollback. | Monkeypatch file write to fail after first file. | Command fails; cleanup result verified; no misleading success. | Reliability |

### 3.5 ID Generation and Safe Slug Handling

| Test ID | Purpose | Input | Expected Output / Validation Logic | Maps To |
| --- | --- | --- | --- | --- |
| ID-001 | Client ID format is validation-compatible. | `client-name="Acme Corp"`, injected shortid if available. | Regex `^client_[a-z0-9]+(?:_[a-z0-9]+)*_[a-z0-9]+$`; lowercase; no whitespace/separators. | AC-007 |
| ID-002 | Audit ID format includes current date. | Injected date `2026-05-24`. | Regex `^audit_20260524_[a-z0-9]+$`; lowercase; no whitespace/separators. | AC-007 |
| ID-003 | Empty slug client names fail. | Names containing only symbols/emoji if slugifies empty. | Invalid client name error; no writes. | Edge cases |
| ID-004 | Path traversal client names are sanitized or rejected safely. | `../Acme`, `Acme/../../x`, `Acme\\x`. | Generated path remains under output parent and uses safe `client_id`; no traversal directories. | AC-007, security |

### 3.6 Sample Endpoint Behavior

| Test ID | Purpose | Input | Expected Output / Validation Logic | Maps To |
| --- | --- | --- | --- | --- |
| END-001 | Empty endpoints are generated by default. | Minimal dev run. | `endpoints=[]`; output describes empty endpoints array. | AC-010 |
| END-002 | Safe mock samples only when requested. | `--include-sample-endpoints`. | Endpoints use example/mock domains such as `example.com`; methods limited to safe methods; no auth, credentials, tokens, destructive payloads. | AC-011 |
| END-003 | Production samples remain safe or omitted. | `--defaults prod --include-sample-endpoints`. | No real endpoints; safe mock-only or empty; production safeguards remain false/non-executable. | AC-012 |

### 3.7 Text and JSON Output Expectations

| Test ID | Purpose | Input | Expected Output / Validation Logic | Maps To |
| --- | --- | --- | --- | --- |
| OUT-001 | Text success includes required operator guidance. | Minimal dev run. | Output includes `SUCCESS`, IDs, profile source/name/target env, workspace root, generated files, resolution order, local-only/no-AWS/no-upload/no-schedule safety, next steps. | AC-016 |
| OUT-002 | JSON success is valid JSON only. | `--output json`. | `json.loads(stdout)` succeeds; no prose before/after; fields include status, command, IDs, profile, effective_settings, generated_files, safety, warnings/next_steps. | AC-004, AC-016 |
| OUT-003 | JSON output contains no secrets and equivalent non-secret data. | `--output json`. | JSON payload paths/IDs match generated files; safety flags false; no secret-bearing keys/values. | AC-016 |
| OUT-004 | Production text includes warning. | `--defaults prod`. | Text contains production selected warning and non-executable safety copy. | AC-012, AC-016 |
| OUT-005 | Error output has stable code, reason, next step, no success language. | Missing profile, invalid JSON, existing dir, invalid timezone. | Non-zero; error format matches UX spec; no generated/modified files claim unless accurate. | AC-008, AC-013 |
| OUT-006 | Invalid `--output` fails before writes. | `--output yaml`. | Argparse/service error; non-zero; no generated files. | Edge cases |

### 3.8 Production Profile Safety

| Test ID | Purpose | Input | Expected Output / Validation Logic | Maps To |
| --- | --- | --- | --- | --- |
| PROD-001 | Bundled prod profile can be selected. | `--defaults prod`. | Success if profile valid; target environment prod/production; warning included. | AC-012 |
| PROD-002 | Prod generated configs are non-executable. | `--defaults prod`. | `allow_production_execution=false`; `allow_destructive_operation=false` in generated files and output. | AC-012 |
| PROD-003 | Prod caps and schedules are conservative. | `--defaults prod`. | `max_concurrency` and request caps within approved conservative thresholds; no unsafe schedules enabled. | AC-012 |
| PROD-004 | Production custom profile receives same safety enforcement. | Custom profile with `target_environment=production`. | Same safeguards/warnings as bundled prod; unsafe values fail. | AC-012 |

### 3.9 No-AWS Interaction Assurance

Target: success and local failure paths must prove no AWS construction/API/upload/scheduler calls occur.

| Test ID | Purpose | Input | Expected Output / Validation Logic | Maps To |
| --- | --- | --- | --- | --- |
| AWS-001 | Success path does not instantiate project AWS factory. | Monkeypatch `release_confidence_platform.storage.aws_client_factory.AwsClientFactory.__init__` to raise; run minimal init. | Command succeeds; monkeypatch not triggered. | AC-015 |
| AWS-002 | Success path does not call boto3 client/resource. | Monkeypatch `boto3.client` and `boto3.resource` to raise; run init. | Command succeeds; no boto3 call recorded. | AC-015 |
| AWS-003 | Failure path missing/invalid profile does not call AWS. | Same monkeypatches; run with missing/invalid profile. | Command fails for local reason only; no AWS call recorded. | AC-015 |
| AWS-004 | Failure path overwrite protection does not call AWS. | Same monkeypatches; pre-existing target without `--overwrite`. | Command fails with output-dir exists; no AWS call recorded. | AC-015 |
| AWS-005 | No upload/scheduler/Lambda/Secrets/DynamoDB/S3 call sites are reached. | Monkeypatch known upload, scheduler, Lambda, Secrets, DynamoDB, and S3 helper methods to raise if imported/called. | Init success/fail paths do not trigger them. | AC-015, FR-013 |
| AWS-006 | AWS credentials are not required. | Run with empty/invalid AWS env vars and monkeypatch credential providers if present. | Local init succeeds/fails based only on local validation, not credentials. | AC-015 |

### 3.10 Regression Tests

| Test ID | Purpose | Input | Expected Output / Validation Logic |
| --- | --- | --- | --- |
| REG-001 | Existing `rcp config init` still requires `--client-name`. | Run without `--client-name`. | Non-zero usage/required argument error; no files. |
| REG-002 | Existing CLI result rendering remains compatible. | Run representative non-init CLI tests and config init text/json modes. | No render regressions; errors are parseable where applicable. |
| REG-003 | Existing validation services still validate generated starter configs. | Invoke project validation commands/services on generated files. | Validation succeeds without AWS/network. |
| REG-004 | Existing config-init contract tests are updated, not deleted. | Run `tests/api/test_config_init_contract.py`. | Old unsupported requirements (`--target-environment`, required `--output-dir`) no longer asserted for enhanced init; all current contract tests pass. |
| REG-005 | Existing safe generated endpoints validation behavior remains intact. | Validate empty endpoints and safe sample endpoints. | Empty endpoints allowed in template mode; unsafe samples rejected. |
| REG-006 | Other operator CLI commands are not broken by parser changes. | Run existing operator CLI discovery/contract tests. | Commands outside `config init` preserve expected behavior. |

## 4. Edge Cases

The following edge cases are mandatory coverage and must fail safely when invalid:

- `--defaults` omitted resolves to `dev`.
- `--defaults dev`, `staging`, and `prod` resolve as named profiles, not relative paths.
- `--defaults ./dev.json`, `config/defaults/dev.json`, Windows-style paths, and any value ending `.json` resolve as explicit file paths.
- Unsupported profile names such as `qa` fail with no writes.
- Missing explicit profile path fails with no writes.
- Invalid JSON fails with no writes.
- Profile missing required top-level or nested fields fails with no writes.
- Secret-bearing profile keys/values fail without exposing secret values in output.
- Invalid timezone from CLI or profile fails with no writes.
- Invalid output format fails with no writes.
- Client names that slugify to empty fail before path construction.
- Client names containing path separators or traversal sequences cannot escape the generated client workspace.
- Generated IDs are lowercase, safe, and validation-compatible.
- Generated default endpoints remain empty.
- Sample endpoints are safe mock-only, non-authenticated, non-destructive, and do not include real production hostnames.
- Production profile and production target environment remain local-only and non-executable by default.
- Existing output directories are protected unless `--overwrite` is supplied.
- Partial write/validation failures do not report success and do not leave approved partial outputs.
- JSON output mode emits parseable JSON only on stdout.
- No AWS clients, resources, uploads, schedules, Lambda invocations, Secrets Manager, DynamoDB, S3, or EventBridge interactions occur on success or local failure paths.

## 5. Test Types Covered

- **Functional:** profile resolution, CLI contract, generated file creation, output rendering, custom profile path, production profile handling.
- **Unit:** resolver/loader validation, precedence rules, slug/ID generation, safe endpoint generation, profile safety validation.
- **Negative:** missing/invalid/unsafe profiles, invalid timezone, invalid output, unsafe client names, existing directory without overwrite, forced generated-config validation failure.
- **Edge Case:** path-like defaults, `.json` defaults without separators, empty slug, traversal-like names, JSON-only stdout, production sample behavior.
- **Integration:** CLI/service invocation through generated files and existing audit/config validation services.
- **Security:** no secrets in profiles/output/generated files, path traversal protection, no AWS/credential/network dependency.
- **Regression:** existing CLI parser behavior, existing validation services, existing config-init contract tests, non-init operator CLI command behavior.

## 6. Coverage Justification

This plan provides full traceability from every product acceptance criterion AC-001 through AC-016 to at least one concrete automated test scenario, with critical paths covered at both unit and CLI/service integration levels. The highest-risk areas receive redundant coverage:

- **Profile resolution and precedence** are covered through direct unit tests and end-to-end CLI assertions.
- **Generated config correctness** is verified by file-content assertions and existing schema/audit validation services.
- **Safety and security** are verified through recursive secret scans, local-only flag checks, production safeguards, path-safety assertions, and explicit no-AWS monkeypatch tests.
- **Filesystem correctness** is verified by exact path assertions, negative flat-path checks, overwrite protection, and rollback behavior.
- **Output contract stability** is verified in both human-readable and JSON modes, including error cases and production warnings.
- **Regression protection** ensures the new parser/service changes do not break existing validation, rendering, or unrelated operator CLI behaviors.

## Suggested QA Commands

Run focused tests first, then broader regression. Commands should be executed from the repository root.

```bash
python -m pytest tests/api/test_config_init_contract.py -q
python -m pytest tests/api/test_config_init_profiles.py -q
python -m pytest tests/api -q
python -m pytest -q
```

Manual/CLI smoke commands for evidence collection after implementation:

```bash
rcp config init --client-name "Acme"
rcp config init --client-name "Acme" --defaults staging
rcp config init --client-name "Enterprise Client" --defaults config/defaults/high-volume-staging.json
rcp config init --client-name "Acme" --defaults staging --output-dir ./tmp-configs --timezone Asia/Hong_Kong --output json
rcp config init --client-name "Acme" --defaults prod --include-sample-endpoints
rcp config init --client-name "Acme" --defaults missing-profile
rcp config init --client-name "Acme" --output yaml
```

Evidence expected during execution:

- Test runner output with pass/fail counts.
- Captured stdout/stderr for text and JSON output modes.
- Generated file tree listings for successful runs.
- Parsed JSON contents of generated `client_config.json`, `audit_config.json`, and `endpoints.json`.
- Validation-service output confirming generated configs pass local audit validation.
- Monkeypatch/call-count evidence proving no boto3, AWS factory, S3, DynamoDB, Secrets Manager, Lambda, scheduler, upload, or credential calls occurred.
