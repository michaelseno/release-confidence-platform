# Test Plan

## 1. Feature Overview

Feature: Operational Discovery CLI commands extending `rcp` on branch `feature/operator_cli_discovery`.

Primary command groups under test:

```bash
python scripts/rcp.py client list ...
python scripts/rcp.py audit list ...
python scripts/rcp.py config list ...
python scripts/rcp.py config download ...
```

The feature adds read-only operational discovery workflows for operators to discover clients, audits, and persisted configuration artifacts without exposing secrets, raw evidence, or direct AWS implementation details. QA scope for this plan is automated unit-level validation only. AWS integrations must be fully mocked/faked; no live AWS calls, real credentials, real buckets, real DynamoDB tables, or real Secrets Manager access are permitted.

System boundaries:

- CLI argument parsing and dispatch for new `client`, expanded `audit`, and new `config` command groups.
- DynamoDB read paths for `client list` and `audit list`.
- S3 metadata-only list/head paths for `config list`.
- S3 object download paths for `config download`, limited to the three expected config artifacts.
- Stage configuration and `RCP_*` environment override reuse from existing operator CLI behavior.
- Human and JSON renderers, including output sanitization.

Out of scope for this plan:

- Implementing tests or application code.
- Live AWS integration testing.
- End-to-end browser/UI validation.
- `--version-id` behavior, because it must not be implemented or exposed in this PR.

## 2. Acceptance Criteria Mapping

| ID | Acceptance Criteria / Requirement | Planned Test Coverage |
| --- | --- | --- |
| AC-001 | Parser supports new `client` group. | Unit parser tests for `client --help`, `client list --help`, required/optional arguments, `--stage`, `--limit`, `--output human|json`, invalid command handling, and service dispatch request shape. |
| AC-002 | Parser supports expanded `audit` group with `audit list` without regressing existing audit commands. | Unit parser tests proving `audit list` is exposed and existing `audit validate/create/schedule/run/cancel` remain parseable; invalid list options exit with parser error and no service dispatch. |
| AC-003 | Parser supports new `config` group with `list` and `download`. | Unit parser tests for `config --help`, `config list`, `config download`, required client/audit identifiers, output directory argument, `--overwrite`, `--output human|json`, and invalid subcommands. |
| AC-004 | `client list` uses DynamoDB query/index path when available. | Unit repository/service tests with mocked DynamoDB client/resource asserting query is called with the configured table/index/key condition path and scan is not called when query succeeds. |
| AC-005 | `client list` bounded fallback scan is allowed only when query/index path is unavailable. | Unit tests simulating missing/unsupported index and asserting fallback uses bounded scan parameters only, respects requested/effective limit, handles pagination safely, and stops after the bound. |
| AC-006 | Default list limit is `100`. | Parser/service tests for omitted `--limit` on `client list` and `audit list`; assert effective limit `100` in service request and AWS request. |
| AC-007 | Hard max list limit is `1000`. | Parser or validation tests for `--limit 1000` succeeds; `--limit 1001`, very large values, zero, and negative values fail before AWS calls or are capped only if specified by implementation contract. |
| AC-008 | No unbounded scans. | Unit tests asserting all scan calls include bounded `Limit` and pagination stop conditions; failure test if fallback attempts scan without explicit bound or continues beyond hard max. |
| AC-009 | `audit list` uses DynamoDB query behavior with `client-id` and limit. | Unit tests asserting query uses client partition/key condition, applies effective limit, handles pagination up to limit, and does not scan for normal `client-id` lookups. |
| AC-010 | `config list` uses S3 metadata listing/head behavior only. | Unit tests asserting list/prefix and head/object metadata calls occur; `get_object`, body read, or object content download are never called for `config list`. |
| AC-011 | `config download` downloads exactly three config artifacts. | Unit tests asserting only client config, audit config, and endpoints config keys are requested/downloaded; no additional prefixes or wildcard downloads. |
| AC-012 | `config download` preserves filenames and creates output directory. | Filesystem-isolated unit tests using a temp output path; assert directory creation and resulting filenames match source artifact filenames exactly. |
| AC-013 | Missing config files fail safely. | Unit tests simulating one or more missing S3 objects; assert non-zero controlled error, no partial success claim, no secrets/raw content printed, and safe cleanup/retention behavior documented by implementation. |
| AC-014 | Download overwrite protection is enforced. | Unit tests with existing destination files; without `--overwrite`, assert failure before replacing files; with `--overwrite`, assert replacement occurs only for the three config artifacts. |
| AC-015 | No Secrets Manager access. | Unit tests patching/mocking AWS client factory and asserting no `secretsmanager` client/resource is constructed or called by any discovery command. |
| AC-016 | No raw-results access. | Unit tests asserting S3 list/head/get prefixes never target `raw-results/` and outputs never contain raw evidence references beyond sanitized metadata if intentionally listed elsewhere. |
| AC-017 | `--version-id` is not implemented/exposed. | Parser/help tests asserting no `--version-id` flag in `config list/download` help; passing `--version-id` exits with parser error and no AWS calls. |
| AC-018 | Human and JSON output are supported for all discovery commands. | Renderer tests for success and controlled failure responses for `client list`, `audit list`, `config list`, and `config download`; assert human-readable summaries and machine-readable JSON shapes. |
| AC-019 | Stage config/env overrides are reused; no hardcoded AWS resources. | Unit tests for each command using fake stage config and explicit `RCP_*` overrides; assert table/bucket/region/profile values come from resolved config and no literal production/dev resource names are embedded in service requests. |
| AC-020 | No secrets or raw evidence printed. | Sanitization tests injecting credentials, tokens, Authorization headers, cookies, raw object content snippets, and provider errors; assert output and JSON omit/redact sensitive values. |
| AC-021 | Mock AWS only, no live AWS. | Test harness fixtures patch boto3/session/client/resource construction; all unit tests fail if unmocked AWS construction or network access is attempted. |

## 3. Test Scenarios

Recommended test location: `tests/api/operator_cli/` for CLI/API-adjacent unit tests, consistent with QA artifact structure. Tests must use mocks/fakes only and must not require AWS credentials.

### 3.1 Command Parsing Unit Tests

1. `test_parser_exposes_client_list_group`
   - Purpose: Verify `client list` is discoverable and parseable.
   - Input: `client --help`, `client list --help`, valid `client list --stage dev`.
   - Expected output: Help includes `list`; valid args produce command dispatch request with stage and default output/limit.
   - Validation logic: Capture parser output/namespace; mock service dispatch and assert call shape.

2. `test_parser_exposes_audit_list_without_regressing_existing_audit_commands`
   - Purpose: Ensure expanded `audit` group retains existing commands.
   - Input: Help and valid minimal argument vectors for `audit list`, plus existing audit commands.
   - Expected output: `audit list` is present; existing commands remain accepted.
   - Validation logic: Parser assertions only; no AWS/service calls.

3. `test_parser_exposes_config_list_and_download_group`
   - Purpose: Verify `config` discovery commands are available.
   - Input: `config --help`, `config list --help`, `config download --help`, valid commands.
   - Expected output: Required `client-id`/`audit-id`/output directory options are enforced.
   - Validation logic: Parser namespace and service request assertions.

4. `test_parser_rejects_invalid_discovery_commands_and_options`
   - Purpose: Prevent unsupported workflows from reaching services.
   - Input: Unknown groups/subcommands, invalid `--output`, invalid `--limit`, missing required IDs.
   - Expected output: Parser exits `2`; no service dispatch.
   - Validation logic: Mock services and assert not called.

5. `test_version_id_flag_is_not_exposed_or_accepted`
   - Purpose: Verify `--version-id` is not part of this PR.
   - Input: Help for `config list/download`; command invocation with `--version-id abc`.
   - Expected output: Help excludes `--version-id`; parser rejects flag with exit `2`; no AWS calls.
   - Validation logic: Capture help text; assert AWS factory not constructed.

### 3.2 `client list` DynamoDB Unit Tests

1. `test_client_list_uses_query_index_path_when_available`
   - Purpose: Validate efficient index/query path.
   - Input: Mock table/index supports query; stage config supplies metadata table.
   - Expected output: Clients returned in human and JSON output.
   - Validation logic: Assert DynamoDB `query` called with configured table/index and effective limit; assert `scan` not called.

2. `test_client_list_default_limit_is_100`
   - Purpose: Verify safe default bound.
   - Input: Omit `--limit`.
   - Expected output: Effective limit `100` in request and rendered result metadata.
   - Validation logic: Inspect service request and DynamoDB call parameters.

3. `test_client_list_hard_max_limit_1000`
   - Purpose: Enforce upper bound.
   - Input: `--limit 1000`, `--limit 1001`, `--limit 0`, `--limit -1`.
   - Expected output: `1000` accepted; invalid values fail before AWS calls.
   - Validation logic: Parser/service validation assertions and AWS mock call count.

4. `test_client_list_fallback_scan_is_bounded_and_stops_at_limit`
   - Purpose: Allow safe fallback only when query/index unavailable.
   - Input: Mock query path unavailable; paginated scan returns more than requested limit.
   - Expected output: Returned clients are capped at effective limit.
   - Validation logic: Assert every scan call includes `Limit`; pagination stops once limit reached; no unbounded scan parameters.

5. `test_client_list_no_fallback_scan_after_successful_query`
   - Purpose: Prevent inefficient duplicate reads.
   - Input: Query returns clients and pagination token absent.
   - Expected output: Success.
   - Validation logic: Assert scan mock has zero calls.

### 3.3 `audit list` DynamoDB Unit Tests

1. `test_audit_list_queries_by_client_id_with_limit`
   - Purpose: Validate per-client audit discovery.
   - Input: `audit list --client-id client_a --limit 25` with mocked DynamoDB results.
   - Expected output: Only audits for `client_a`; effective limit `25`.
   - Validation logic: Assert query key condition/partition uses client ID and table from stage config.

2. `test_audit_list_default_and_max_limits`
   - Purpose: Share list limit policy with client discovery.
   - Input: Omitted limit, `1000`, and invalid values.
   - Expected output: Default `100`; max `1000`; invalid values fail before AWS calls.
   - Validation logic: Inspect request/call params and error behavior.

3. `test_audit_list_paginates_only_until_effective_limit`
   - Purpose: Prevent excessive DynamoDB reads.
   - Input: Query pages with more than requested records.
   - Expected output: Result count capped at limit.
   - Validation logic: Assert pagination stops at limit and no scan is used for normal client-id query.

### 3.4 `config list` S3 Metadata Unit Tests

1. `test_config_list_lists_expected_config_prefix_and_heads_artifacts`
   - Purpose: Validate metadata-only discovery.
   - Input: `config list --client-id client_a --audit-id audit_1`.
   - Expected output: Three config artifact metadata entries when present.
   - Validation logic: Assert S3 list/prefix and head calls use configured bucket and config prefixes.

2. `test_config_list_never_downloads_object_content`
   - Purpose: Prevent accidental content exposure.
   - Input: Mock S3 where `get_object` would raise if called.
   - Expected output: Success using metadata only.
   - Validation logic: Assert `get_object`, body reads, and download APIs are never invoked.

3. `test_config_list_human_and_json_output_are_sanitized`
   - Purpose: Validate renderer behavior.
   - Input: Metadata containing suspicious values or provider errors containing credentials.
   - Expected output: Human and JSON outputs include safe key names/metadata only; secrets redacted/omitted.
   - Validation logic: String and JSON assertions against sensitive token patterns.

### 3.5 `config download` S3 and Filesystem Unit Tests

1. `test_config_download_fetches_exactly_three_artifacts`
   - Purpose: Enforce strict artifact set.
   - Input: Mock S3 has client config, audit config, and endpoints config plus unrelated/raw-results objects.
   - Expected output: Only the three config artifacts are downloaded.
   - Validation logic: Assert exact S3 get/download call keys; assert no wildcard/list of raw-results or evidence prefixes.

2. `test_config_download_preserves_filenames_and_creates_output_dir`
   - Purpose: Validate operator filesystem behavior.
   - Input: Nonexistent temp output directory.
   - Expected output: Directory created; files named exactly as source artifact filenames.
   - Validation logic: Inspect temp directory file names and contents from fake S3 payloads.

3. `test_config_download_missing_file_fails_safely`
   - Purpose: Avoid misleading partial success.
   - Input: One of three artifacts returns not found.
   - Expected output: Non-zero controlled error; no success summary; partial files are either cleaned up or clearly reported according to implementation contract.
   - Validation logic: Assert safe error message, no secret/raw content output, and documented partial-file behavior.

4. `test_config_download_prevents_overwrite_by_default`
   - Purpose: Protect local operator files.
   - Input: Destination directory contains one or more target filenames.
   - Expected output: Failure before replacement; existing file content unchanged.
   - Validation logic: Hash/read temp files before and after; assert no S3 object bodies written over existing files.

5. `test_config_download_overwrite_replaces_only_expected_files`
   - Purpose: Validate explicit overwrite behavior.
   - Input: Existing target files plus `--overwrite`.
   - Expected output: Three config files replaced; unrelated local files untouched.
   - Validation logic: File content and modification assertions; exact artifact set assertion.

6. `test_config_download_does_not_use_secrets_manager_or_raw_results`
   - Purpose: Validate security boundaries.
   - Input: All AWS clients patched with strict mocks.
   - Expected output: No Secrets Manager client/resource calls; no raw-results S3 access.
   - Validation logic: Assert service names and S3 keys/prefixes.

### 3.6 Output, Sanitization, and Stage Configuration Tests

1. `test_all_discovery_commands_support_human_and_json_output`
   - Purpose: Confirm output modes for all commands.
   - Input: Success responses for `client list`, `audit list`, `config list`, `config download` with `--output human` and `--output json`.
   - Expected output: Human summaries are readable; JSON is valid, deterministic, and contains command result metadata.
   - Validation logic: Parse JSON output; assert stable keys and no Python repr/provider internals.

2. `test_discovery_errors_are_sanitized_in_human_and_json_output`
   - Purpose: Prevent leakage through failures.
   - Input: Mock DynamoDB/S3 exceptions containing access keys, tokens, Authorization headers, cookies, raw JSON bodies, and raw-results paths.
   - Expected output: Controlled sanitized errors only.
   - Validation logic: Negative string matching for secret patterns and raw evidence snippets.

3. `test_stage_config_and_env_overrides_are_reused`
   - Purpose: Ensure no hardcoded AWS resources.
   - Input: Fake stage config and `RCP_AWS_REGION`, `RCP_AWS_PROFILE`, `RCP_CONFIG_BUCKET`, `RCP_AUDIT_METADATA_TABLE` overrides.
   - Expected output: AWS calls use resolved override values.
   - Validation logic: Inspect AWS factory and repository constructor arguments.

4. `test_no_live_aws_clients_are_constructed`
   - Purpose: Enforce mock-only QA scope.
   - Input: Run unit tests with boto3/session constructors patched to raise if unmocked.
   - Expected output: Tests pass only when code uses injected mocked clients/factories.
   - Validation logic: Global fixture asserts no network/client construction escape.

## 4. Edge Cases

- Empty DynamoDB result sets for `client list` and `audit list` render successful empty lists in both human and JSON output.
- DynamoDB pagination returns duplicate or malformed items; renderer/repository should handle or reject deterministically without leaking raw provider data.
- Query/index path unavailable for `client list`; fallback scan remains bounded and never exceeds hard max.
- S3 config metadata has one, two, or all three artifacts missing.
- Destination output directory already exists, is missing, or contains conflicting files.
- Destination path is not writable or is a file instead of a directory; failure is controlled and safe.
- Existing destination files with `--overwrite` plus unrelated files in the same directory; unrelated files remain untouched.
- Invalid identifiers containing path traversal markers, spaces, shell metacharacters, or raw S3 prefixes must be rejected or safely normalized according to existing identifier validation rules.
- Provider exceptions include secrets, credentials, raw config bodies, or raw-results references; output remains sanitized.
- `--version-id` appears before or after subcommand arguments; parser rejects consistently.

## 5. Test Types Covered

- Functional unit coverage: command parsing, service dispatch, DynamoDB query/list behavior, S3 metadata and download behavior, output rendering.
- Negative unit coverage: invalid arguments, invalid limits, missing files, overwrite conflicts, unsupported `--version-id`, provider exceptions.
- Edge case coverage: default/max limits, bounded pagination, empty results, partial missing artifacts, filesystem conflict states.
- Integration-boundary coverage: CLI-to-service request mapping and stage config/env override propagation using mocked AWS clients.
- Security coverage: no Secrets Manager access, no raw-results access, no object content download for `config list`, output sanitization.
- Regression coverage: existing `audit` subcommands remain parseable; existing stage config/env override behavior is reused; no hardcoded AWS resources; no live AWS access.

## 6. Coverage Justification

This plan covers the full requested operational discovery surface at the unit level while enforcing read-safety, bounded AWS access patterns, and output sanitization. The highest-risk areas are unbounded DynamoDB scans, accidental S3 content/raw-results access, local overwrite behavior, and leakage of secrets/raw evidence through human or JSON output. Each risk is mapped to explicit parser, repository/service, renderer, and filesystem tests with mocked AWS dependencies only.

Regression risks specifically protected by this plan:

- Adding `audit list` must not remove or alter existing `audit validate/create/schedule/run/cancel` parser behavior.
- Discovery commands must reuse existing stage resolution and `RCP_*` environment override conventions rather than introducing hardcoded buckets, tables, regions, profiles, or indexes.
- New config discovery must not access Secrets Manager, raw-results, run evidence, or full object content except the exact three config artifacts during `config download`.
- List commands must remain bounded by default limit `100` and hard max `1000` to prevent cost/performance regressions.
- JSON output support must not bypass sanitization or expose provider internals.

QA execution for this plan should not approve the feature unless all critical tests above pass with evidence showing mocked AWS-only execution and no unresolved failures.
