# Product Specification

## 1. Feature Overview

The Operational Discovery CLI feature extends the existing internal `rcp` operator CLI with read-oriented operational discovery and safe configuration retrieval commands.

This feature enables trusted platform operators to inspect runtime audit metadata, discover registered clients and audits, inspect uploaded configuration artifacts in S3, and safely download runtime configuration artifacts for debugging and audit lifecycle support.

This feature is internal operator tooling only. It is not customer-facing.

The commands covered by this specification are:

- `rcp client list --stage <stage>`
- `rcp audit list --client-id <client_id> --stage <stage>`
- `rcp config list --client-id <client_id> --audit-id <audit_id> --stage <stage>`
- `rcp config download --client-id <client_id> --audit-id <audit_id> --output-dir <path> --stage <stage>`

The implementation must reuse existing shared service modules and stage configuration resolution. The CLI must not duplicate business logic for AWS resource discovery, DynamoDB access, S3 access, lifecycle interpretation, or config path construction when shared modules already exist or are being introduced for reuse.

## 2. Problem Statement

Operators currently need safe visibility into audit runtime state and uploaded configuration artifacts without directly querying DynamoDB, browsing S3 manually, downloading unintended files, exposing secrets, or inspecting raw evidence.

Without explicit discovery commands, operational debugging is slower, less repeatable, and more error-prone. Operators may use ad hoc AWS console or CLI commands that bypass project safety rules, stage configuration, pagination limits, and output redaction expectations.

This feature provides a controlled, stage-aware CLI interface for metadata discovery and S3 config retrieval while preserving operational safety and avoiding customer-facing scope expansion.

## 3. User Persona / Target User

- **Technical operator / maintainer:** Uses the internal CLI to inspect clients, audits, and uploaded config artifacts during support, debugging, and audit lifecycle management.
- **Platform engineer:** Implements reusable discovery/config service modules and keeps CLI behavior thin and consistent with platform storage conventions.
- **QA engineer:** Validates command parsing, AWS interaction boundaries, pagination safeguards, output formats, and safe download behavior using mocked AWS dependencies only.

## 4. User Stories

- As a technical operator, I want to list known clients for a stage so that I can discover which clients have audit metadata without directly scanning AWS resources manually.
- As a technical operator, I want to list audits for a client so that I can inspect audit lifecycle state and config metadata without loading raw evidence.
- As a technical operator, I want to list config artifacts for a client audit so that I can confirm which config files exist in S3 and see their metadata without downloading contents.
- As a technical operator, I want to download runtime config artifacts to a local directory so that I can debug operational issues using the exact persisted config files.
- As a platform engineer, I want discovery commands to reuse shared services so that future APIs or dashboards do not duplicate CLI-only business logic.
- As a QA engineer, I want deterministic command behavior with mocked AWS dependencies so that safety and failure behavior can be validated without live AWS calls.

## 5. Goals / Success Criteria

The feature is successful when:

- Operators can list unique client IDs for a specified stage with bounded pagination safeguards.
- Operators can list audit metadata for a specified client and stage without loading raw evidence or S3 raw-results data.
- Operators can inspect S3 metadata for expected config artifacts without downloading object contents.
- Operators can safely download only the expected S3 config artifacts into a local directory while preserving filenames.
- Existing local files are not overwritten unless `--overwrite` is explicitly supplied.
- Commands provide concise human-readable output and support `--output json` where specified.
- Stage configuration is resolved from `config/stages/{dev,staging,prod}.json` with environment overrides and no hardcoded AWS resource identifiers.
- No secrets are downloaded from Secrets Manager, printed, or otherwise exposed by these commands.
- Unit tests cover command parsing, DynamoDB query behavior, S3 listing behavior, config download behavior, overwrite protection, output format behavior, and pagination/limit safeguards using mocked AWS dependencies only.

## 6. Feature Scope

### In Scope

- Internal `rcp` CLI extension for operational discovery and config retrieval.
- Command: `rcp client list --stage <stage>`.
- Command: `rcp audit list --client-id <client_id> --stage <stage>`.
- Command: `rcp config list --client-id <client_id> --audit-id <audit_id> --stage <stage>`.
- Command: `rcp config download --client-id <client_id> --audit-id <audit_id> --output-dir <path> --stage <stage>`.
- Human-readable table or concise text output for all commands.
- `--output json` support for all commands.
- Optional `--limit <n>` for `client list` and `audit list`.
- Bounded paginated DynamoDB access for client discovery fallback.
- DynamoDB audit metadata query using `PK = CLIENT#{client_id}` and `SK = AUDIT#{audit_id}` conventions.
- S3 config artifact metadata inspection for expected config object paths.
- S3 config artifact download for only:
  - `client_config.json`
  - `audit_config.json`
  - `endpoints.json`
- Local output directory creation for config downloads.
- Overwrite protection with optional `--overwrite`.
- Warning message before or during config download indicating that config files may contain sensitive operational details.
- Recommendation to use `.local-configs/` for downloaded configs.
- Ensuring `.local-configs/` is included in git ignore configuration as part of this feature if it is not already ignored.
- Unit tests with mocked AWS only.

### Out of Scope

- Customer-facing UI, API, documentation, or self-service workflow.
- Secrets Manager retrieval or download.
- Printing, downloading, or inspecting secrets.
- Loading raw evidence details.
- Loading S3 raw-results objects.
- Run metadata discovery.
- Raw execution/result inspection.
- New AWS resource naming rules.
- Hardcoded AWS resource identifiers.
- Live AWS calls in unit tests.
- Implementing `--version-id` for config downloads.
- Deleting, archiving, mutating, or lifecycle-transitioning configs.
- Audit scheduling, cancellation, creation, validation, or manual run behavior beyond compatibility with existing `rcp` CLI commands.

### Future Considerations

The following placeholders must be documented only and must not be implemented in this PR:

- `rcp config delete`
- `rcp config archive`
- `rcp run list`
- `rcp run inspect`
- `rcp audit status`
- `rcp schedule status`
- `rcp config download --version-id <version_id>`

## 7. Functional Requirements

### FR-001: CLI Integration and Invocation

The system must extend the existing internal `rcp` operator CLI rather than creating a separate CLI.

The minimum invocation must remain compatible with the existing Operator CLI entry point. If the existing project supports both `python scripts/rcp.py ...` and `rcp ...`, the discovery commands must be available through the same supported invocation methods.

The CLI must provide stage-aware commands using `--stage` for `dev`, `staging`, and `prod` where those stages are supported by project stage config.

### FR-002: Shared Service Reuse

The CLI command handlers must delegate resource resolution, DynamoDB access, S3 path construction, S3 metadata retrieval, S3 download behavior, and output serialization to shared modules where available or to reusable service modules introduced for this feature.

The CLI must not duplicate business logic that should be shared with future admin APIs, dashboards, or other operator tooling.

### FR-003: Stage Configuration Resolution

All AWS resources must be resolved from stage configuration files under `config/stages/{dev,staging,prod}.json` with existing environment variable override behavior.

The commands must not hardcode DynamoDB table names, S3 bucket names, regions, account IDs, ARNs, or environment-specific resource identifiers.

### FR-004: Client List Command

The system must support:

```bash
rcp client list --stage dev
```

The command must return unique `client_id` values known to the audit metadata system.

The command may include these additional fields when available without unsafe or unbounded access:

- `client_name`
- `created_at`
- `active_audit_count`

The command must support:

- Human-readable table output by default.
- `--output json` for structured output.
- Optional `--limit <n>`.

Limit behavior must be:

- Default limit: `100` clients.
- Hard maximum limit: `1000` clients.
- Values above `1000` must be rejected or capped with an explicit operator-visible message.
- The implementation must never scan beyond the requested limit plus any explicit internal page guard needed to deduplicate client IDs.

The preferred data access pattern is an indexed or queryable client registry source. If no client registry table or index exists, the temporary fallback is to derive unique client IDs from audit metadata records using a bounded paginated DynamoDB scan.

The fallback scan must be documented in implementation-facing docs or code comments as temporary until a registry or index exists.

### FR-005: Audit List Command

The system must support:

```bash
rcp audit list --client-id client_demo --stage dev
```

The command must query DynamoDB audit metadata for the specified client using the metadata key pattern:

- `PK = CLIENT#{client_id}`
- `SK` begins with or equals audit metadata records using the `AUDIT#` prefix.

The command must return audit metadata fields when available:

- `audit_id`
- `lifecycle_state`
- `created_at`
- `audit_window`
- `target_environment`
- `config_version`
- `config_hash`

The command must support:

- Human-readable table output by default.
- `--output json` for structured output.
- Optional `--limit <n>`.

The command must not load raw evidence details, S3 raw-results data, execution payloads, or full config object contents.

### FR-006: Config List Command

The system must support:

```bash
rcp config list --client-id client_demo --audit-id audit_001 --stage dev
```

The command must inspect S3 metadata for the expected config artifact paths:

- `configs/{client_id}/client_config.json`
- `configs/{client_id}/audits/{audit_id}/audit_config.json`
- `configs/{client_id}/audits/{audit_id}/endpoints.json`

For each available object, the command must return:

- logical filename
- S3 object key
- `last_modified`
- `version_id` if S3 versioning metadata is available from the metadata/list/head operation
- `size_bytes`

The command must support:

- Human-readable table output by default.
- `--output json` for structured output.

The command must not download object contents.

### FR-007: Config Download Command

The system must support:

```bash
rcp config download --client-id client_demo --audit-id audit_001 --output-dir .local-configs/client_demo/audit_001 --stage dev
```

The command must download only the expected config artifacts:

- `configs/{client_id}/client_config.json` to `<output-dir>/client_config.json`
- `configs/{client_id}/audits/{audit_id}/audit_config.json` to `<output-dir>/audit_config.json`
- `configs/{client_id}/audits/{audit_id}/endpoints.json` to `<output-dir>/endpoints.json`

The command must create the output directory if it does not exist.

The command must preserve filenames exactly as listed above.

The command must fail safely if any required S3 config file is missing. Safe failure means:

- The command exits non-zero.
- The operator receives a clear message identifying missing artifact names or keys.
- The command does not silently produce a partial successful result.

The default overwrite behavior must be:

- If any target local file already exists, the command must fail before replacing files.
- The operator must pass `--overwrite` to replace existing local files.

The command must support:

- `--overwrite`
- `--output json`

The command must print an operator-visible warning that downloaded configs may contain sensitive operational details.

The command must never retrieve secrets from Secrets Manager.

The command must not support `--version-id` in this PR.

### FR-008: Output Format

All commands must produce concise human-readable output by default.

All commands must support `--output json` and return structured JSON suitable for automated operator workflows.

JSON output must avoid secrets, raw evidence, and full downloaded object contents.

Human-readable output must not expose raw evidence, secrets, or full config contents.

### FR-009: Operational Safety

The commands must avoid sensitive values, secrets, raw evidence, and unbounded AWS reads.

The commands must be read-only except for local filesystem writes performed by `rcp config download`.

The commands must not mutate DynamoDB records, S3 objects, schedules, Lambda state, audit lifecycle state, or Secrets Manager values.

### FR-010: Testing Requirements

The implementation must include automated tests for:

- Command parsing for all new commands and supported options.
- Stage argument handling.
- DynamoDB client list behavior, including fallback bounded pagination and limit enforcement.
- DynamoDB audit list query behavior.
- S3 config list metadata behavior.
- S3 config download behavior.
- Missing S3 artifact failure behavior.
- Local output directory creation.
- Default overwrite protection.
- `--overwrite` replacement behavior.
- JSON output behavior.
- Human-readable output behavior where practical.
- Confirmation that unit tests use mocked AWS only and do not require live AWS credentials.

## 8. Acceptance Criteria

### AC-001: Client List Returns Unique Clients

Given audit metadata contains multiple audit records for the same client in the selected stage  
When an operator runs `rcp client list --stage dev`  
Then the command returns each `client_id` only once.

### AC-002: Client List Supports JSON Output

Given known client audit metadata exists for the selected stage  
When an operator runs `rcp client list --stage dev --output json`  
Then the command returns valid JSON containing the discovered client records and no raw evidence or secrets.

### AC-003: Client List Enforces Default Limit

Given more than 100 clients are discoverable in the selected stage  
When an operator runs `rcp client list --stage dev` without `--limit`  
Then the command returns no more than 100 clients.

### AC-004: Client List Enforces Hard Limit

Given an operator requests a limit greater than 1000  
When the operator runs `rcp client list --stage dev --limit 5000`  
Then the command rejects or caps the request with an explicit operator-visible message and does not read beyond the hard maximum behavior.

### AC-005: Client List Uses Bounded Fallback Scan

Given no client registry table or index is available  
When an operator runs `rcp client list --stage dev --limit 25`  
Then the command derives clients from audit metadata using bounded paginated access and does not scan beyond the requested limit/page guard.

### AC-006: Audit List Returns Metadata Only

Given audit metadata exists for `client_demo` in the selected stage  
When an operator runs `rcp audit list --client-id client_demo --stage dev`  
Then the command returns audit metadata fields including `audit_id`, `lifecycle_state`, `created_at`, `audit_window`, `target_environment`, and available config version/hash fields.

### AC-007: Audit List Does Not Load Raw Evidence

Given raw evidence exists in S3 for audits belonging to `client_demo`  
When an operator runs `rcp audit list --client-id client_demo --stage dev`  
Then the command does not request, load, print, or summarize raw evidence or raw-results objects.

### AC-008: Audit List Supports Limit

Given more audit records exist than the requested limit  
When an operator runs `rcp audit list --client-id client_demo --stage dev --limit 10`  
Then the command returns no more than 10 audit records.

### AC-009: Config List Returns S3 Metadata Only

Given the expected config objects exist in S3 for `client_demo` and `audit_001`  
When an operator runs `rcp config list --client-id client_demo --audit-id audit_001 --stage dev`  
Then the command returns object key, last modified timestamp, size in bytes, and version ID when available for each config object without downloading contents.

### AC-010: Config List Handles Missing Objects Clearly

Given one or more expected config objects are missing in S3  
When an operator runs `rcp config list --client-id client_demo --audit-id audit_001 --stage dev`  
Then the command indicates which expected artifacts are unavailable without downloading any object contents.

### AC-011: Config Download Creates Output Directory

Given the output directory does not exist and all expected S3 config objects exist  
When an operator runs `rcp config download --client-id client_demo --audit-id audit_001 --output-dir .local-configs/client_demo/audit_001 --stage dev`  
Then the command creates the output directory and downloads the expected files with preserved filenames.

### AC-012: Config Download Fails on Missing S3 Artifact

Given at least one expected config object is missing in S3  
When an operator runs `rcp config download --client-id client_demo --audit-id audit_001 --output-dir .local-configs/client_demo/audit_001 --stage dev`  
Then the command exits non-zero, identifies the missing artifact, and does not report a successful complete download.

### AC-013: Config Download Protects Existing Files by Default

Given `<output-dir>/client_config.json` already exists locally  
When an operator runs `rcp config download --client-id client_demo --audit-id audit_001 --output-dir <output-dir> --stage dev` without `--overwrite`  
Then the command exits non-zero and does not replace the existing file.

### AC-014: Config Download Allows Explicit Overwrite

Given target config files already exist locally and all expected S3 config objects exist  
When an operator runs `rcp config download --client-id client_demo --audit-id audit_001 --output-dir <output-dir> --stage dev --overwrite`  
Then the command replaces the existing target files with the downloaded S3 config artifacts.

### AC-015: Config Download Warns About Sensitive Operational Details

Given an operator invokes config download  
When the command begins or prepares to download config artifacts  
Then the command prints a warning that configs may contain sensitive operational details.

### AC-016: Secrets Manager Is Not Accessed

Given config artifacts reference secret identifiers or runtime secret locations  
When an operator runs any discovery or config download command  
Then the command does not retrieve, print, or download secret values from Secrets Manager.

### AC-017: Stage Resources Are Config-Driven

Given a stage is supplied through `--stage`  
When any discovery command resolves AWS resources  
Then the command uses stage configuration and environment override behavior and does not use hardcoded resource identifiers.

### AC-018: Commands Are Read-Only Against AWS

Given an operator runs any command in this feature  
When the command interacts with AWS  
Then it does not mutate DynamoDB records, S3 objects, schedules, Lambda state, audit lifecycle state, or Secrets Manager values.

### AC-019: Version ID Is Metadata Only in This PR

Given an S3 config object has a version ID available through metadata operations  
When an operator runs `rcp config list`  
Then the command may display the version ID as object metadata.

### AC-020: Version-Specific Download Is Deferred

Given an operator attempts to use `--version-id` with `rcp config download`  
When the command is parsed  
Then the command does not provide version-specific download behavior in this PR.

### AC-021: Tests Use Mocked AWS Only

Given the automated test suite is run without live AWS credentials  
When tests for the discovery CLI execute  
Then the tests pass using mocked AWS clients and do not require live AWS calls.

## 9. Edge Cases

- No clients are discoverable for the selected stage.
- Multiple audit metadata records exist for the same client and must be deduplicated.
- Client metadata fields such as `client_name`, `created_at`, or `active_audit_count` are unavailable.
- Audit metadata exists without optional `config_version` or `config_hash` fields.
- Audit metadata contains unexpected lifecycle states that should be displayed as stored without causing raw evidence access.
- DynamoDB pagination returns duplicate client IDs across pages.
- Requested `--limit` is zero, negative, non-numeric, or above the hard maximum.
- No audit metadata exists for a supplied client ID.
- S3 object versioning is disabled and no `version_id` is available.
- One or more expected S3 config artifacts are missing.
- Local output directory does not exist.
- Local output path exists as a file instead of a directory.
- Local target files already exist without `--overwrite`.
- Local filesystem permissions prevent directory creation or file writes.
- Download succeeds for one object but fails for a later object; the command must not claim full success.
- Stage config is missing, invalid, or lacks required resource identifiers.
- AWS access is denied for DynamoDB or S3 metadata operations.
- AWS throttling or transient errors occur during paginated reads or S3 metadata operations.

## 10. Constraints

- This feature is a separate PR from the merged core Operator CLI PR #12.
- The feature must extend the existing internal `rcp` CLI.
- The CLI must be internal operator tooling only and not customer-facing.
- The implementation must reuse shared service modules and must not duplicate business logic.
- Stage resource resolution must use `config/stages/{dev,staging,prod}.json` and supported environment overrides.
- AWS resource names and identifiers must not be hardcoded.
- DynamoDB reads must use queryable/indexed access patterns where available.
- Any fallback DynamoDB scan for client discovery must be bounded, paginated, limited, and temporary.
- Default client list limit is `100`; hard maximum is `1000`.
- `rcp audit list` is metadata-focused only.
- `rcp config list` must not download object contents.
- `rcp config download` must download only S3 config artifacts and never Secrets Manager secrets.
- `--version-id` for config download is explicitly deferred and must not be implemented in this PR.
- `.local-configs/` must be recommended for local downloads and gitignored if not already ignored.
- Unit tests must use mocked AWS only.

## 11. Dependencies

- Existing core `rcp` Operator CLI from merged PR #12.
- Existing stage configuration files under `config/stages/`.
- Existing environment override behavior for stage configuration.
- DynamoDB audit metadata table or service with records using:
  - `PK = CLIENT#{client_id}`
  - `SK = AUDIT#{audit_id}`
- S3 bucket configured for runtime config artifacts.
- S3 config object structure:
  - `configs/{client_id}/client_config.json`
  - `configs/{client_id}/audits/{audit_id}/audit_config.json`
  - `configs/{client_id}/audits/{audit_id}/endpoints.json`
- Shared service modules for AWS clients, stage config resolution, metadata access, S3 config path construction, and output formatting, or new reusable service modules introduced for these purposes.
- Test framework and AWS mocking utilities already used by the project or added without requiring live AWS access.

## 12. Assumptions

- Assumption requiring confirmation: The existing `rcp` CLI command structure can add `client` and `config` command groups without conflicting with existing commands.
- Assumption requiring confirmation: Audit metadata records contain enough fields to populate `audit_id`, `lifecycle_state`, `created_at`, `audit_window`, and `target_environment`; missing optional fields may be omitted or displayed as unavailable.
- Assumption requiring confirmation: S3 metadata operations can retrieve `version_id` when bucket versioning is enabled and permissions allow it.
- Assumption requiring confirmation: A `.gitignore` or equivalent ignore file is the correct place to ensure `.local-configs/` is ignored in this repository.

## 13. Open Questions

- Should `--limit` values above `1000` be rejected with a non-zero exit code or capped to `1000` with a warning? Either behavior is acceptable only if explicit and tested.
- Should `rcp config download` remove already-downloaded files after a later artifact fails, or is retaining partial local files acceptable when the command exits non-zero and does not claim success?
- What exact JSON envelope shape should be standardized across commands if the core Operator CLI already defines an output schema?
- If a client registry/index exists in a future stage, what is the canonical field source for `client_name`, `created_at`, and `active_audit_count`?

## 14. Risks

- Bounded fallback scanning may miss clients beyond the requested limit/page guard until a proper client registry or index exists.
- Downloaded config files may contain sensitive operational details even though they are not Secrets Manager secrets.
- Operators may accidentally store downloaded configs outside ignored local directories if they choose a custom output path.
- Partial local downloads may require manual cleanup depending on final implementation behavior.
- If shared service boundaries are not enforced, CLI-specific logic may be duplicated and increase future maintenance cost.
