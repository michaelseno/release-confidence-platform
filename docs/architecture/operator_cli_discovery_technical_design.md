# Technical Design

## 1. Feature Overview

Operational Discovery extends the existing internal `rcp` Operator CLI with read-only discovery and configuration retrieval commands:

- `rcp client list`
- `rcp audit list`
- `rcp config list`
- `rcp config download`

The feature is internal operator tooling only. It adds no dashboard, API, or customer-facing UI. The CLI remains thin and delegates discovery, storage access, pagination, S3 key construction, output shaping, and sanitization to shared modules under the existing `src/release_confidence_platform/...` src-layout introduced by the core Operator CLI.

## 2. Product Requirements Summary

- Add read-only discovery/config retrieval commands extending `rcp`.
- Reuse existing core Operator CLI entry points, parser style, `CommandResult`, human/JSON output mechanisms, stage config resolution, AWS client factory, S3/DynamoDB wrappers, config path constants, exceptions, and sanitization.
- Do not duplicate S3 logic, DynamoDB query logic, validation logic, or config path generation logic in CLI handlers.
- Do not expose raw evidence or Secrets Manager values.
- Do not mutate configs, audits, schedules, or run/evidence data. `config download` may only write local files.
- Defer `--version-id`; it must not be added or implemented in this feature.
- Recommend and gitignore `.local-configs/` for downloaded config files.
- Use current S3 config paths and DynamoDB keys:
  - `configs/{client_id}/client_config.json`
  - `configs/{client_id}/audits/{audit_id}/audit_config.json`
  - `configs/{client_id}/audits/{audit_id}/endpoints.json`
  - audit metadata `PK=CLIENT#{client_id}`, `SK=AUDIT#{audit_id}`
- Pagination/limits:
  - default limit `100`
  - hard max `1000` for `client list` fallback
  - no unbounded scans
  - `audit list` must also be limit-bound
  - use DynamoDB query/index if available
  - `client list` may temporarily use a bounded paginated DDB scan only if no client registry/index exists
- Support human-readable and JSON output for every command.
- Tests must use mocked AWS only.

## 3. Requirement-to-Architecture Mapping

| Requirement | Technical Design Response |
| --- | --- |
| Four new commands | Extend `operator_cli/main.py` parser with `client`, `audit list`, and `config` command groups/subcommands. Route through thin adapters in `operator_cli/services.py` or split command modules if parser growth warrants. |
| Thin CLI | CLI handlers only parse args, load stage config, instantiate shared services/wrappers, and render `CommandResult`. Discovery logic lives in `operator_cli/discovery_service.py` or `core/discovery_service.py`. |
| Reuse stage/output/sanitization | Keep `StageConfigLoader`, `AwsClientFactory`, `CommandResult`, `render`, `render_error`, and `sanitize` as the CLI boundary. |
| Reuse S3/DDB wrappers/path generation | Add read/list methods to `storage/s3_client.py` and `storage/audit_metadata_client.py`; use `core.constants.engine` path templates. No direct boto3 calls in CLI/service command adapters. |
| No raw evidence/secrets | Discovery services allow only config keys and audit metadata summaries. They must not list/read `raw-results/` and must not call `SecretsManagerClient.get_secret_value`. Output is sanitized. |
| Read-only AWS behavior | AWS wrapper extensions are read-only: DDB `query`/bounded `scan`, S3 `get_object`/`head_object`/bounded `list_objects_v2`. No put/update/delete/scheduler/Lambda calls. |
| Config download writes local files only | Download service reads allowed S3 config objects and writes to operator-specified local directory, defaulting to `.local-configs/{stage}/{client_id}/{audit_id}/...`. |
| `--version-id` deferred | Parser and services must not expose `--version-id`; S3 reads use latest object version only. |
| Pagination/limits | Shared service validates `--limit` in `[1, 1000]`; default `100`. It uses DynamoDB `Limit` and `LastEvaluatedKey`; any fallback scan stops once the requested page is filled or hard max is reached. |
| Human + JSON output | Use existing `CommandResult` renderer, extending it only if needed to format `items`, `next_token`, `downloaded_files`, and `config_keys`. |
| Mocked AWS tests | Add unit/contract tests with fake S3/DDB clients; no real boto3 sessions in tests. |

## 4. Technical Scope

### Current Technical Scope

- Parser integration for:
  - `rcp client list --stage ... [--limit N] [--next-token TOKEN] [--output text|json]`
  - `rcp audit list --stage ... --client-id CLIENT [--limit N] [--next-token TOKEN] [--output text|json]`
  - `rcp config list --stage ... --client-id CLIENT [--audit-id AUDIT] [--output text|json]`
  - `rcp config download --stage ... --client-id CLIENT --audit-id AUDIT [--output-dir DIR] [--output text|json]`
- Shared discovery/config retrieval service contracts.
- Read-only S3 and DynamoDB wrapper extensions.
- Safe output schemas for text and JSON.
- Local file-write behavior for downloaded configs.
- `.gitignore` update for `.local-configs/`.
- Mocked AWS unit tests and CLI parser/contract tests.

### Out of Scope

- Dashboard, API, UI, admin RBAC, or customer-facing documentation.
- Mutating configs, audit metadata, schedules, Lambda invocations, or evidence.
- Listing/downloading raw evidence under `raw-results/`.
- Fetching or printing Secrets Manager secret values.
- `--version-id` support for config download.
- Unbounded DDB scans or S3 listings.
- Real AWS calls in unit tests.

### Future Technical Considerations

- Replace temporary `client list` bounded scan fallback with a first-class client registry item or GSI if product/platform confirms a registry schema.
- Add `--version-id` to `config download` only after explicit product approval and S3 versioning semantics are designed.
- Add richer table formatting or filtering after stable operator usage patterns emerge.

## 5. Architecture Overview

### Existing Core CLI Reuse

Current core CLI implementation uses:

- `scripts/rcp.py` as a thin shim.
- Console script `rcp = release_confidence_platform.operator_cli.main:main` in `pyproject.toml`.
- `src/release_confidence_platform/operator_cli/main.py` for `argparse` parser/dispatch.
- `src/release_confidence_platform/operator_cli/services.py` for command-to-service adapters.
- `src/release_confidence_platform/operator_cli/result.py` for sanitized text/JSON rendering.
- `src/release_confidence_platform/config/stage_config.py` for stage resolution.
- `src/release_confidence_platform/storage/aws_client_factory.py` for boto3 construction.
- `src/release_confidence_platform/storage/s3_client.py` and `storage/audit_metadata_client.py` as AWS wrappers.

Operational Discovery must extend these modules rather than introducing parallel packaging or legacy `packages/...` paths. If any legacy compatibility imports exist elsewhere, they should continue importing from `src/release_confidence_platform/...`; no new legacy package tree is required.

### Request Flow

1. CLI parses command and global `--stage`/`--output` options.
2. CLI adapter loads `StageConfig` via `StageConfigLoader`.
3. CLI adapter constructs `AwsClientFactory(stage_config)`.
4. CLI adapter creates shared discovery service with S3/DDB wrappers.
5. Shared service validates IDs, limits, tokens, and command-specific arguments.
6. Shared service performs read-only S3/DDB wrapper calls.
7. Shared service returns a sanitized, bounded result object.
8. CLI returns `CommandResult` through existing human/JSON renderer.

## 6. System Components

### Update: `src/release_confidence_platform/operator_cli/main.py`

Responsibilities:

- Extend top-level groups from `{audit}` to `{client,audit,config}`.
- Preserve existing `audit validate|create|schedule|run|cancel` behavior.
- Add `audit list` without changing existing audit subcommands.
- Add shared list args:
  - `--limit`, default `100`, type `int`
  - `--next-token`, optional opaque token string
- Do not add `--version-id`.

### Update: `src/release_confidence_platform/operator_cli/services.py`

Responsibilities:

- Add thin adapters:
  - `client_list_command(args)`
  - `audit_list_command(args)`
  - `config_list_command(args)`
  - `config_download_command(args)`
- Load stage config and build `AwsClientFactory`.
- Call shared discovery/config retrieval services.
- Return `CommandResult` only; no boto3 calls, path construction, pagination loops, or raw file parsing in this module.

### Add: `src/release_confidence_platform/operator_cli/discovery_service.py`

This is acceptable under `operator_cli` because the use case is internal operator discovery. It must still be shared-service-style and independent of `argparse`.

Service classes/contracts:

- `DiscoveryListService`
  - `list_clients(limit: int = 100, next_token: str | None = None) -> ClientListResult`
  - `list_audits(client_id: str, limit: int = 100, next_token: str | None = None) -> AuditListResult`
- `ConfigDiscoveryService`
  - `list_config_keys(client_id: str, audit_id: str | None = None) -> ConfigListResult`
  - `download_audit_config_set(client_id: str, audit_id: str, output_dir: Path | None = None) -> ConfigDownloadResult`

Rules:

- No `argparse.Namespace` dependency.
- Validate identifiers with existing shared validators where available.
- Validate `limit` once in service layer.
- Encode/decode pagination tokens through a small helper so DDB `LastEvaluatedKey` is not exposed as implementation-specific Python objects.
- Return only safe metadata/config content; no raw evidence, no secret values.

### Update: `src/release_confidence_platform/storage/audit_metadata_client.py`

Add read-only repository methods:

- `list_audits_for_client(client_id: str, *, limit: int, next_key: dict | None = None) -> Page[dict]`
  - Uses DynamoDB `query` with `PK = CLIENT#{client_id}` and `begins_with(SK, 'AUDIT#')`.
  - Excludes occurrence items by ensuring only `SK` values matching audit metadata shape are returned. If using `begins_with`, service must filter out `#OCCURRENCE#` defensively and continue only within the requested bounded page behavior.
- `list_clients_from_registry(*, limit: int, next_key: dict | None = None) -> Page[dict] | None`
  - Uses a registry/index only if one already exists in the current schema/configuration. This design does not create a new table/GSI.
- `scan_clients_bounded(*, limit: int, next_key: dict | None = None, max_items: int = 1000) -> Page[dict]`
  - Temporary fallback only when no registry/index exists.
  - Uses DDB `scan` with `Limit` per request and stops after collecting up to requested `limit` unique client IDs or reading `max_items` items.
  - Projection should include only `PK`, `SK`, `client_id`, and safe summary fields.

The repository should centralize DDB query/scan behavior to avoid duplicating DDB logic in services.

### Update: `src/release_confidence_platform/storage/s3_client.py`

Add read-only helpers:

- `read_text(key: str) -> str` or reuse `read_json` for JSON-only config downloads.
- `list_keys(prefix: str, *, max_keys: int = 1000, continuation_token: str | None = None) -> Page[str]`
  - Wraps `list_objects_v2`.
  - Must be bounded and prefix-scoped to `configs/{client_id}/...` only for this feature.
- Existing `read_json` and `object_exists` should be reused.

Do not add raw evidence listing helpers for discovery.

### Update: `src/release_confidence_platform/core/constants/engine.py`

Reuse existing templates:

- `CLIENT_CONFIG_KEY_TEMPLATE`
- `AUDIT_CONFIG_KEY_TEMPLATE`
- `ENDPOINTS_CONFIG_KEY_TEMPLATE`

Add only small helper functions if needed, for example in a new module `core/config_paths.py`, to avoid duplicating `.format(...)` calls across services. Do not hardcode config S3 paths in CLI handlers.

### Update: `src/release_confidence_platform/operator_cli/result.py`

Extend text rendering minimally to display safe list/download result fields:

- `items` as rows/bullets for list commands.
- `config_keys` for `config list`.
- `downloaded_files` for `config download`.
- `next_token` when present.

JSON rendering can continue returning the sanitized payload object.

### Update: `.gitignore`

Add:

```gitignore
.local-configs/
```

## 7. Data Models

No new persisted AWS data model is introduced.

### Existing Audit Metadata Item

#### Purpose

Stores audit lifecycle/config summary metadata and is used as the source for audit discovery.

#### Primary Key

- `PK = CLIENT#{client_id}`
- `SK = AUDIT#{audit_id}`

#### Fields Read by Discovery

- `client_id`: string.
- `audit_id`: string.
- `lifecycle_state`: string.
- `created_at`: string, if present.
- `updated_at`: string, if present.
- `config_hash`: string/map, if present and safe.
- `config_version`: string, if present.
- `audit_window`: object, safe summary only.
- `execution_environment`: string/object, safe summary only.

#### Ownership Model

Scoped by `client_id` in the partition key. Operators must pass an explicit `--client-id` for audit/config discovery except `client list`.

#### Lifecycle

Read-only in this feature. No create/update/delete/archive behavior.

### Existing Config S3 Objects

#### Purpose

Persist runtime configuration created by `rcp audit create`.

#### Keys

- `configs/{client_id}/client_config.json`
- `configs/{client_id}/audits/{audit_id}/audit_config.json`
- `configs/{client_id}/audits/{audit_id}/endpoints.json`

#### Ownership Model

Scoped by `client_id` and, for audit/endpoints configs, `audit_id`.

#### Lifecycle

Read from S3 only. `config download` creates local copies but does not mutate S3.

## 8. API Contracts

No HTTP API is introduced. CLI command contracts are defined below.

## Command: `rcp client list`

### Purpose

List known clients for an operator-selected stage.

### Authentication / Authorization

Uses operator AWS credentials resolved by `StageConfigLoader`/`AwsClientFactory`. No application RBAC is added.

### Request Parameters

- `--stage <dev|staging|prod>` required.
- `--limit <int>` optional, default `100`, allowed `1..1000`.
- `--next-token <string>` optional.
- `--output <text|json>` optional, default `text`.

### Request Body

None.

### Response Body

JSON output shape:

```json
{
  "command": "client list",
  "stage": "dev",
  "status": "success",
  "summary": "clients listed",
  "items": [
    {"client_id": "client1", "audit_count": 3, "updated_at": "2026-05-23T00:00:00Z"}
  ],
  "limit": 100,
  "next_token": "opaque-token-or-null"
}
```

### Success Status Codes

- Process exit `0`.

### Error Status Codes

- Process exit `1` for invalid stage, invalid limit/token, DDB errors, or unexpected sanitized failures.

### Validation Rules

- `limit` must be `1..1000`.
- `next_token` must decode to a safe pagination key produced by this CLI.

### Side Effects

- None.

### Idempotency / Duplicate Handling

- Repeated calls are read-only and may reflect current DDB state.

## Command: `rcp audit list`

### Purpose

List audit metadata summaries for one client.

### Authentication / Authorization

Uses operator AWS credentials. Access is limited by the operator's IAM permissions.

### Request Parameters

- `--stage <dev|staging|prod>` required.
- `--client-id <string>` required.
- `--limit <int>` optional, default `100`, allowed `1..1000`.
- `--next-token <string>` optional.
- `--output <text|json>` optional, default `text`.

### Response Body

```json
{
  "command": "audit list",
  "stage": "dev",
  "status": "success",
  "summary": "audits listed",
  "client_id": "client1",
  "items": [
    {
      "audit_id": "audit1",
      "lifecycle_state": "DRAFT",
      "created_at": "2026-05-23T00:00:00Z",
      "updated_at": "2026-05-23T00:00:00Z"
    }
  ],
  "limit": 100,
  "next_token": "opaque-token-or-null"
}
```

### Success Status Codes

- Process exit `0`.

### Error Status Codes

- Process exit `1` for invalid args, missing client/audits where treated as storage errors, DDB errors, or unexpected sanitized failures.

### Validation Rules

- `client_id` must pass shared identifier validation where available.
- `limit` must be `1..1000`.
- Use DDB query against `PK=CLIENT#{client_id}`; do not scan for this command.

### Side Effects

- None.

### Idempotency / Duplicate Handling

- Read-only.

## Command: `rcp config list`

### Purpose

Show deterministic config object keys available for a client or a specific audit without reading raw evidence.

### Authentication / Authorization

Uses operator AWS credentials.

### Request Parameters

- `--stage <dev|staging|prod>` required.
- `--client-id <string>` required.
- `--audit-id <string>` optional.
- `--output <text|json>` optional, default `text`.

### Response Body

```json
{
  "command": "config list",
  "stage": "dev",
  "status": "success",
  "summary": "config keys listed",
  "client_id": "client1",
  "audit_id": "audit1",
  "config_keys": [
    {"type": "client", "key": "configs/client1/client_config.json", "exists": true},
    {"type": "audit", "key": "configs/client1/audits/audit1/audit_config.json", "exists": true},
    {"type": "endpoints", "key": "configs/client1/audits/audit1/endpoints.json", "exists": true}
  ]
}
```

### Success Status Codes

- Process exit `0`.

### Error Status Codes

- Process exit `1` for invalid IDs, S3 errors, or unexpected sanitized failures.

### Validation Rules

- `client_id` and optional `audit_id` must pass shared identifier validation where available.
- If `audit_id` is absent, list only the client config key plus bounded keys under `configs/{client_id}/audits/` if implemented through `S3StorageClient.list_keys(max_keys=1000)`. Do not list outside `configs/{client_id}/`.

### Side Effects

- None.

### Idempotency / Duplicate Handling

- Read-only.

## Command: `rcp config download`

### Purpose

Download the three persisted config files for a client audit to a local operator directory.

### Authentication / Authorization

Uses operator AWS credentials.

### Request Parameters

- `--stage <dev|staging|prod>` required.
- `--client-id <string>` required.
- `--audit-id <string>` required.
- `--output-dir <path>` optional; default `.local-configs/{stage}/{client_id}/{audit_id}`.
- `--output <text|json>` optional, default `text`.

### Request Body

None.

### Response Body

```json
{
  "command": "config download",
  "stage": "dev",
  "status": "success",
  "summary": "configs downloaded",
  "client_id": "client1",
  "audit_id": "audit1",
  "downloaded_files": [
    {"type": "client", "path": ".local-configs/dev/client1/audit1/client_config.json"},
    {"type": "audit", "path": ".local-configs/dev/client1/audit1/audit_config.json"},
    {"type": "endpoints", "path": ".local-configs/dev/client1/audit1/endpoints.json"}
  ]
}
```

### Success Status Codes

- Process exit `0`.

### Error Status Codes

- Process exit `1` for invalid IDs, missing S3 config object, invalid output directory, local file write failure, S3 errors, or unexpected sanitized failures.

### Validation Rules

- `client_id` and `audit_id` must pass shared identifier validation where available.
- Do not accept `--version-id`.
- Only download the three deterministic config files.
- Write pretty JSON or exact normalized JSON content only after successful read and sanitization.
- Output directory path must not be an existing file.

### Side Effects

- Local filesystem writes only.
- Creates output directory if missing.
- No S3/DDB/EventBridge/Lambda mutation.

### Idempotency / Duplicate Handling

- Re-running may overwrite local files in the chosen output directory. This is acceptable because local files are operator-owned and `.local-configs/` is gitignored/recommended.

## 9. Frontend Impact

No frontend impact. This feature intentionally adds no dashboard, API, or UI.

### Components Affected

- None.

### API Integration

- None.

### UI States

- Not applicable.

## 10. Backend Logic

### Responsibilities

- Stage-aware discovery through existing AWS wrapper boundaries.
- Safe, bounded DDB query/scan behavior.
- Safe, prefix-scoped S3 config listing and reads.
- Safe local file download behavior.
- Sanitized human/JSON output.

### Validation Flow

1. Parser enforces required command arguments and basic type parsing.
2. `StageConfigLoader` validates stage and required AWS resource config.
3. Discovery services validate IDs, limits, and pagination tokens.
4. Storage wrappers enforce bounded AWS reads.
5. Output is sanitized before rendering.

### Business Rules

- No raw evidence access.
- No Secrets Manager value retrieval.
- No AWS mutations.
- No unbounded scans/listings.
- `client list` fallback DDB scan is temporary and bounded.
- `audit list` uses query/index semantics, not table scan.
- `config download` is latest-version only; `--version-id` is not implemented.

### Persistence Flow

- AWS persistence: none.
- Local persistence: `config download` creates/writes files under `--output-dir` or `.local-configs/{stage}/{client_id}/{audit_id}`.

### Error Handling

- Use existing `EngineError` subclasses where applicable (`ConfigError`, `StorageError`).
- Map unknown exceptions at CLI boundary to `UNEXPECTED_ERROR` without traceback.
- Sanitize provider messages before output.
- Missing config objects should fail the download command rather than producing partial success, unless implementation returns a controlled error with already-written local files disclosed.

## 11. File Structure

### Files to Update

- `src/release_confidence_platform/operator_cli/main.py`
  - Add `client` group.
  - Add `audit list` subcommand.
  - Add `config list` and `config download` subcommands.
- `src/release_confidence_platform/operator_cli/services.py`
  - Add command adapters for the four new commands.
- `src/release_confidence_platform/operator_cli/result.py`
  - Extend text rendering for list/config/download output fields.
- `src/release_confidence_platform/storage/audit_metadata_client.py`
  - Add bounded read-only list/query/temporary scan helpers.
- `src/release_confidence_platform/storage/s3_client.py`
  - Add bounded config key listing and/or read-text helper if needed.
- `.gitignore`
  - Add `.local-configs/`.

### Files to Add

- `src/release_confidence_platform/operator_cli/discovery_service.py`
  - Shared discovery/config retrieval services and pagination token helper.
- Optional if path helper is preferred:
  - `src/release_confidence_platform/core/config_paths.py`
- Tests:
  - `tests/unit/test_operator_cli_discovery.py`
  - `tests/api/test_operator_cli_discovery_contract.py`

### Files Not to Add

- No new `packages/...` implementation tree.
- No dashboard/API/UI files.
- No Secrets Manager discovery command.
- No raw evidence discovery/download module.

## 12. Security

- Authentication is AWS credential/profile based through existing stage config and boto3 session construction.
- Authorization is enforced by IAM permissions for the configured AWS profile; this feature adds no app-level RBAC.
- Output is passed through existing sanitizer.
- Services must not call Secrets Manager read APIs.
- Services must not list/read `raw-results/` or expose evidence payloads.
- DDB projection should include only safe summary fields for list commands.
- Config files may contain `auth_ref` identifiers but must not contain or resolve actual secret values.
- Pagination tokens should be opaque and integrity-safe enough to avoid arbitrary key injection. At minimum, decode JSON/base64 and validate expected key names/types before use.
- Local download defaults to `.local-configs/`, which must be gitignored to reduce accidental commits.

## 13. Reliability

- All AWS reads are bounded by explicit limits.
- `client list` scan fallback must stop at hard max `1000` read items and return a next token if more data may exist.
- `audit list` uses DDB query/index behavior and returns `next_token` from `LastEvaluatedKey`.
- S3 config listing, if used, must set `MaxKeys` and prefix scope.
- No retry layer is added beyond boto3/botocore defaults in this feature.
- Storage wrapper methods should convert AWS failures to sanitized `StorageError` messages.
- Unit tests use fake AWS clients to verify no mutating methods are called for discovery commands.
- Performance is acceptable for operator tooling because limits are small and calls are stage-scoped.

## 14. Dependencies

- Existing Python package and console script configuration in `pyproject.toml`.
- Existing `boto3` dependency and `AwsClientFactory`.
- Existing stage config files under `config/stages/`.
- Existing S3 config path constants in `core.constants.engine`.
- Existing `AuditMetadataRepository` and `S3StorageClient` wrappers.
- Existing sanitizer and exception hierarchy.

## 15. Assumptions

- Audit metadata records use `PK=CLIENT#{client_id}` and `SK=AUDIT#{audit_id}` as stated.
- Persisted config objects use the existing deterministic paths in `core.constants.engine`.
- No stable client registry/index is currently visible in the inspected repo; therefore `client list` must prefer a registry/index if discovered during implementation, otherwise use the documented temporary bounded scan fallback.
- Downloaded config files are operator-local artifacts and may be overwritten on repeated runs.

## Technical Assumptions Requiring Confirmation

- Whether a first-class client registry item or DDB GSI exists outside the current repository branch. If yes, implementation should route `client list` to it and disable the scan fallback where possible.
- Exact safe summary fields desired for `client list` beyond `client_id`, `audit_count`, and timestamps.
- Whether `config list` without `--audit-id` should list all audit config keys via bounded S3 prefix listing or only the deterministic client config key plus a message requiring `--audit-id` for audit files.

## 16. Risks / Open Questions

- **Temporary scan fallback risk:** bounded DDB scans are less efficient and may miss clients outside the page/max read window. This is acceptable only as a temporary fallback until registry/index support is confirmed.
- **Occurrence item filtering:** `PK=CLIENT#{client_id}` can include occurrence records whose `SK` begins with `AUDIT#...#OCCURRENCE#`; `audit list` must filter those out and return only audit metadata summaries.
- **Config sensitivity risk:** Config JSON may include sensitive-adjacent references. Sanitization must remain enabled for downloaded content and command output must not print full config bodies.
- **Pagination token compatibility:** Token format should be treated as CLI-internal and may change before public/customer use, but must be validated to avoid malformed input errors.

## 17. Implementation Notes

- Implement command adapters first, but keep all substantive logic in `discovery_service.py` and storage wrappers.
- Add parser tests ensuring:
  - All four commands parse.
  - `--stage` remains required.
  - `--output json` is accepted for all commands.
  - `config download` rejects unknown `--version-id` by default argparse behavior.
- Add mocked AWS tests ensuring:
  - `client list` uses registry/index method when fake exposes it; otherwise scan fallback is bounded.
  - `audit list` calls query, not scan.
  - `config list` only inspects `configs/...` keys.
  - `config download` reads exactly the three deterministic config keys and writes local files.
  - No fake AWS mutating methods (`put_item`, `update_item`, `put_object`, `delete_object`, scheduler calls, Lambda invoke) are called.
- Keep JSON output stable with top-level `items`, `config_keys`, `downloaded_files`, and `next_token` fields.
- Update `docs/operator-cli/README.md` in implementation work if operator usage docs are part of downstream scope; this architecture document only defines the implementation blueprint.
