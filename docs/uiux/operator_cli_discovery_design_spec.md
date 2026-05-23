# Design Specification

## 1. Feature Overview

Operational Discovery extends the internal `rcp` CLI with read-only discovery commands for clients, audits, persisted config metadata, and safe local config downloads.

In scope commands:

```bash
rcp client list --stage dev [--limit n] [--output json]
rcp audit list --client-id client_demo --stage dev [--limit n] [--output json]
rcp config list --client-id client_demo --audit-id audit_001 --stage dev [--output json]
rcp config download --client-id client_demo --audit-id audit_001 --output-dir .local-configs/client_demo/audit_001 --stage dev [--overwrite] [--output json]
```

This is internal operator tooling only. No customer-facing UI, web dashboard, interactive prompt, color-dependent styling, or backend implementation is defined by this document.

Future placeholders may be documented in help as unavailable only when clearly marked `not implemented`. `--version-id` for `config download` is explicitly deferred and must not be exposed in command help or accepted by the command parser for this release.

## 2. User Goal

Operators need to discover available client and audit identifiers, inspect available persisted configuration artifacts, and download source configuration files for local operational review without directly browsing storage services or exposing secrets, raw evidence, or sensitive values in terminal output.

## 3. UX Rationale

- Use concise text output optimized for terminal logs, copy/paste, screen readers, and incident workflows.
- Require `--stage` for every command to prevent accidental environment ambiguity.
- Keep tables minimal and deterministic; avoid borders, icons, progress animations, and color-only status.
- Provide optional stable JSON for automation while ensuring JSON is sanitized and does not include secrets, sensitive config values, raw evidence, or presigned URLs.
- Make local file safety explicit: downloads fail when destination files already exist unless `--overwrite` is provided.
- Warn before successful download output that config files may contain sensitive operational details and recommend `.local-configs/`.

## 4. User Flow

### Client Discovery

1. Operator runs `rcp client list --stage dev` with optional `--limit` and `--output json`.
2. CLI validates stage and limit.
3. CLI prints a concise list of clients available in the selected stage.
4. CLI exits `0` when the request succeeds, including when no clients are found.

### Audit Discovery

1. Operator identifies a client ID from client discovery or prior knowledge.
2. Operator runs `rcp audit list --client-id client_demo --stage dev` with optional `--limit` and `--output json`.
3. CLI validates stage, client ID, and limit.
4. CLI prints audit summaries for the client without raw evidence, run logs, or sensitive config values.

### Config Metadata Discovery

1. Operator identifies `client_id` and `audit_id`.
2. Operator runs `rcp config list --client-id client_demo --audit-id audit_001 --stage dev`.
3. CLI validates required IDs and stage.
4. CLI prints available configuration artifacts and safe metadata such as file name, artifact type, version marker when already supported by storage metadata, update time, and size.

### Config Download

1. Operator runs `rcp config download --client-id client_demo --audit-id audit_001 --output-dir .local-configs/client_demo/audit_001 --stage dev`.
2. CLI validates IDs, stage, and output directory path.
3. If target files already exist, CLI fails with a clear error and instructs the operator to rerun with `--overwrite` only after verifying local files may be replaced.
4. If files do not exist, CLI downloads config artifacts to the requested directory.
5. CLI prints a sensitivity warning, downloaded file list, and next-step handling guidance.

## 5. Information Hierarchy

Terminal output must prioritize:

1. Result status: `SUCCESS`, `ERROR`, or `WARNING`.
2. Command identity and `stage`.
3. Target identity: `client_id`, `audit_id`, and `output_dir` when applicable.
4. Count or file summary.
5. Deterministic table or file list.
6. Safety warning for downloaded config files.
7. Operator next step for failures or sensitive local files.

## 6. Layout Structure

### Command Structure

```text
rcp
  client
    list      --stage STAGE [--limit N] [--output text|json]
  audit
    list      --client-id CLIENT_ID --stage STAGE [--limit N] [--output text|json]
  config
    list      --client-id CLIENT_ID --audit-id AUDIT_ID --stage STAGE [--output text|json]
    download  --client-id CLIENT_ID --audit-id AUDIT_ID --output-dir PATH --stage STAGE [--overwrite] [--output text|json]
```

Default output is text. `--output json` switches the complete command response to JSON. `--output text` may be accepted for consistency if the existing CLI supports explicit text output, but text remains the default.

### Top-Level Help Layout

```text
usage: rcp [-h] {client,audit,config} ...

Internal Release Confidence Platform operator CLI.

commands:
  client    Discover clients available to operators
  audit     Audit operations and audit discovery
  config    Discover and download persisted audit configuration artifacts

Run "rcp <command> --help" for command-specific options.
```

### `rcp client list --help`

```text
usage: rcp client list --stage STAGE [--limit N] [--output {text,json}]

List clients visible in a stage.

required:
  --stage STAGE          Target stage, for example dev, staging, or prod

optional:
  --limit N              Maximum clients to return
  --output {text,json}   Output format; default: text
  -h, --help             Show this help message and exit

examples:
  rcp client list --stage dev
  rcp client list --stage dev --limit 20 --output json
```

### `rcp audit list --help`

```text
usage: rcp audit list --client-id CLIENT_ID --stage STAGE [--limit N] [--output {text,json}]

List audits for a client without exposing raw evidence or sensitive config values.

required:
  --client-id CLIENT_ID  Client identifier
  --stage STAGE          Target stage, for example dev, staging, or prod

optional:
  --limit N              Maximum audits to return
  --output {text,json}   Output format; default: text
  -h, --help             Show this help message and exit

examples:
  rcp audit list --client-id client_demo --stage dev
  rcp audit list --client-id client_demo --stage dev --limit 10 --output json
```

### `rcp config list --help`

```text
usage: rcp config list --client-id CLIENT_ID --audit-id AUDIT_ID --stage STAGE [--output {text,json}]

List persisted configuration artifacts for an audit.

required:
  --client-id CLIENT_ID  Client identifier
  --audit-id AUDIT_ID    Audit identifier
  --stage STAGE          Target stage, for example dev, staging, or prod

optional:
  --output {text,json}   Output format; default: text
  -h, --help             Show this help message and exit

examples:
  rcp config list --client-id client_demo --audit-id audit_001 --stage dev
  rcp config list --client-id client_demo --audit-id audit_001 --stage dev --output json
```

### `rcp config download --help`

```text
usage: rcp config download --client-id CLIENT_ID --audit-id AUDIT_ID --output-dir PATH --stage STAGE [--overwrite] [--output {text,json}]

Download persisted audit configuration artifacts to a local directory.

required:
  --client-id CLIENT_ID  Client identifier
  --audit-id AUDIT_ID    Audit identifier
  --output-dir PATH      Local destination directory; recommended under .local-configs/
  --stage STAGE          Target stage, for example dev, staging, or prod

optional:
  --overwrite            Replace existing local files in the destination when names conflict
  --output {text,json}   Output format; default: text
  -h, --help             Show this help message and exit

safety:
  Downloaded configs may contain sensitive operational details. Prefer paths under .local-configs/
  and do not commit downloaded files to source control.

examples:
  rcp config download --client-id client_demo --audit-id audit_001 --output-dir .local-configs/client_demo/audit_001 --stage dev
  rcp config download --client-id client_demo --audit-id audit_001 --output-dir .local-configs/client_demo/audit_001 --stage dev --overwrite
```

## 7. Components

- Command parser and help text.
- Text output renderer.
- JSON output renderer.
- Table renderer for list commands.
- Sanitized error renderer.
- Empty-state renderer.
- Download warning renderer.
- Local file conflict guard.
- Overwrite confirmation-by-flag messaging.

No visual web components are defined.

## 8. Interaction Behavior

### Common Text Success Pattern

```text
SUCCESS: <command>
stage: <stage>
summary: <concise result sentence>
```

Additional identity lines must appear immediately after `stage` when relevant:

```text
client_id: <client_id>
audit_id: <audit_id>
output_dir: <path>
```

### Common Failure Pattern

```text
ERROR: <command> failed
stage: <stage if parsed>
code: <CONTROLLED_ERROR_CODE>
message: <sanitized actionable message>
next_step: <specific corrective action>
```

Error messages must not include secret values, raw config content, raw evidence, stack traces by default, AWS credentials, bucket internals beyond safe identifiers, or presigned URLs.

### Exit Codes

Use deterministic exit codes:

| Exit code | Meaning | Example |
| --- | --- | --- |
| `0` | Success, including valid empty result | No audits found for a client |
| `1` | General controlled failure | Storage lookup failed with sanitized message |
| `2` | CLI usage or validation error | Missing `--stage`, invalid `--limit` |
| `3` | Local file safety conflict | Download target file exists without `--overwrite` |
| `4` | Not found | Client, audit, or config artifacts not found |
| `5` | Permission or environment access denied | Operator lacks access to stage data |

### List Limit Behavior

- `--limit` accepts positive integers only.
- Invalid values such as `0`, negative numbers, decimals, or non-numeric text fail before service access with exit code `2`.
- When results are truncated by limit, text output must include `truncated: true` and `next_step: rerun with a higher --limit if more rows are needed` when pagination is not implemented.
- Future pagination tokens are not implemented in this release and must not be emitted as active workflow instructions.

### Text Table Rules

- Use plain columns with a single header row.
- Do not use box-drawing characters, emoji, spinners, or color-only status.
- Use `-` for unavailable non-sensitive fields.
- Use ISO-like timestamps such as `2026-05-23T14:30:00Z` where available.
- Keep row values sanitized and compact.

## 9. Component States

### Command Parser

| State | Behavior |
| --- | --- |
| Default | Parses command, required flags, optional flags, and defaults `--output` to text. |
| Focus | Not applicable visually; terminal cursor and shell handle focus. Help must remain readable by keyboard-only users. |
| Active | On command submission, validates local arguments before service access. |
| Disabled | Not applicable; unsupported commands fail with usage help and exit code `2`. |
| Loading | No spinner required. For longer downloads, optional single line `downloading: <n> config files` may be printed before final result in text mode only. |
| Success | Emits success renderer and exits `0`. |
| Error | Emits sanitized error renderer and exits non-zero. |
| Empty | Delegates to empty-state renderer for list commands. |

### Help Text

| State | Behavior |
| --- | --- |
| Default | Shows usage, description, required options, optional options, safety notes where applicable, and examples. |
| Hover | Not applicable. |
| Focus | Text order must be logical for terminal screen readers. |
| Active | Triggered by `-h` or `--help`; exits `0`. |
| Disabled | Deferred flags, including `--version-id`, are not shown. |
| Loading | Not applicable. |
| Success | Help renders without requiring stage configuration or service access. |
| Error | Unknown command or invalid option shows concise parser error and relevant usage. |
| Empty | Not applicable. |

### Text Table Renderer

| State | Behavior |
| --- | --- |
| Default | Renders deterministic header and rows. |
| Hover | Not applicable. |
| Focus | Preserve left-to-right reading order and avoid alignment that requires color. |
| Active | Renders after successful data retrieval. |
| Disabled | Not applicable. |
| Loading | Not applicable; renderer only receives completed data. |
| Success | Prints count and table. |
| Error | Not used; error renderer handles failures. |
| Empty | Prints `count: 0` and a specific empty message without table rows. |

### JSON Output Renderer

| State | Behavior |
| --- | --- |
| Default | Emits stable, sanitized JSON object with predictable keys. |
| Hover | Not applicable. |
| Focus | Not applicable. |
| Active | Triggered by `--output json`. |
| Disabled | Not applicable. |
| Loading | Must not emit partial JSON progress lines. |
| Success | Emits one valid JSON document and exits `0`. |
| Error | Emits one valid JSON error document and exits non-zero. |
| Empty | Emits success JSON with `count: 0` and empty arrays. |

### Download Warning Renderer

| State | Behavior |
| --- | --- |
| Default | Present for every successful text download. |
| Hover | Not applicable. |
| Focus | Warning appears before downloaded file list so screen reader users hear safety guidance first. |
| Active | Triggered after successful download validation and before final file summary. |
| Disabled | Not applicable for download command. |
| Loading | Not used. |
| Success | Prints sensitivity and `.local-configs/` recommendation. |
| Error | If download fails before file writes, error renderer handles failure; if partial writes are possible, message must identify local cleanup next step without exposing file contents. |
| Empty | If no config artifacts exist, command fails with not found rather than producing an empty download. |

### Local File Conflict Guard

| State | Behavior |
| --- | --- |
| Default | Checks destination file conflicts before writing. |
| Hover | Not applicable. |
| Focus | Not applicable. |
| Active | Triggered during `config download`. |
| Disabled | Not applicable. |
| Loading | Not applicable. |
| Success | Allows writes when no conflicts exist or when `--overwrite` is present. |
| Error | Existing files without `--overwrite` fail with exit code `3`; no files are replaced. |
| Empty | Not applicable. |

## 10. Responsive Design Rules

CLI output is terminal-based rather than viewport-based, but it must remain usable across common terminal widths.

- Desktop/wide terminals: tables may align columns for readability.
- Tablet/remote terminal widths: avoid long decorative separators; keep columns minimal.
- Mobile/narrow SSH terminals: content remains readable when wrapped; critical fields appear as `key: value` lines before tables.
- JSON output must not depend on terminal width.
- Do not rely on color, hover, pointer interactions, or fixed-width rendering for meaning.

## 11. Visual Design Tokens

No graphical design system tokens are required. CLI text conventions:

- Status labels: uppercase `SUCCESS`, `ERROR`, `WARNING`.
- Indentation: two spaces for nested list items.
- Missing values: `-`.
- Booleans: lowercase `true` / `false`.
- Output format: UTF-8 plain text, no required ANSI color.
- JSON field names: lowercase snake_case.

## 12. Accessibility Requirements

- All commands must be fully operable by keyboard because interaction occurs through terminal input.
- Help and output must use meaningful text labels rather than color, icons, or alignment alone.
- Screen readers must receive status first, then stage and identifiers, then detailed rows.
- Error messages must include `code`, `message`, and `next_step` so operators can act without visual context.
- JSON output must be valid JSON for assistive tooling and automation.
- Avoid animated progress indicators and frequently updating lines, which can be disruptive in screen readers and logs.
- Use concise language; do not bury safety warnings after long tables.

## 13. Edge Cases

### Empty Client List

```text
SUCCESS: client list
stage: dev
summary: no clients found
count: 0
next_step: verify stage or client onboarding status if clients were expected
```

### Empty Audit List

```text
SUCCESS: audit list
stage: dev
client_id: client_demo
summary: no audits found for client
count: 0
next_step: verify client_id or create an audit if needed
```

### No Config Artifacts

```text
ERROR: config list failed
stage: dev
client_id: client_demo
audit_id: audit_001
code: CONFIG_ARTIFACTS_NOT_FOUND
message: no persisted configuration artifacts were found for this audit
next_step: verify audit_id and stage, then confirm the audit was created successfully
```

### Download File Conflict

```text
ERROR: config download failed
stage: dev
client_id: client_demo
audit_id: audit_001
output_dir: .local-configs/client_demo/audit_001
code: LOCAL_FILE_EXISTS
message: one or more destination files already exist; no files were replaced
conflicts:
  - client_config.json
  - audit_config.json
next_step: review local files, then rerun with --overwrite if replacement is intended
```

### Invalid Limit

```text
ERROR: client list failed
code: INVALID_ARGUMENT
message: --limit must be a positive integer
next_step: rerun with --limit 1 or greater
```

### Access Denied

```text
ERROR: audit list failed
stage: prod
client_id: client_demo
code: ACCESS_DENIED
message: operator credentials do not allow reading audit discovery data for this stage
next_step: verify active credentials and request stage access if appropriate
```

### Unsupported Deferred Version Download

If an operator attempts `--version-id`, the parser must treat it as unsupported:

```text
ERROR: config download failed
code: INVALID_ARGUMENT
message: --version-id is not supported for config download in this release
next_step: rerun without --version-id
```

## 14. Developer Handoff Notes

### Text Success Examples

#### `client list`

```text
SUCCESS: client list
stage: dev
summary: found 2 clients
count: 2

client_id     audit_count  last_updated
client_demo   3            2026-05-23T14:30:00Z
client_acme   1            2026-05-22T09:15:00Z
```

Fields:

| Field | Description | Sensitive? |
| --- | --- | --- |
| `client_id` | Client identifier safe for operator use | No |
| `audit_count` | Count of visible audits when available, otherwise `-` | No |
| `last_updated` | Last safe metadata update timestamp when available | No |

#### `audit list`

```text
SUCCESS: audit list
stage: dev
client_id: client_demo
summary: found 2 audits
count: 2

audit_id   lifecycle_state  created_at              updated_at              schedule_status
audit_001  SCHEDULED        2026-05-20T12:00:00Z    2026-05-21T08:10:00Z    enabled
audit_002  DRAFT            2026-05-22T10:05:00Z    2026-05-22T10:05:00Z    -
```

Fields:

| Field | Description | Sensitive? |
| --- | --- | --- |
| `audit_id` | Audit identifier | No |
| `lifecycle_state` | Safe lifecycle state | No |
| `created_at` | Audit metadata creation time | No |
| `updated_at` | Audit metadata update time | No |
| `schedule_status` | Safe schedule summary such as `enabled`, `disabled`, or `-` | No |

#### `config list`

```text
SUCCESS: config list
stage: dev
client_id: client_demo
audit_id: audit_001
summary: found 3 config artifacts
count: 3

file_name              artifact_type      size_bytes  updated_at
client_config.json     client_config      1840        2026-05-20T12:00:00Z
audit_config.json      audit_config       2962        2026-05-20T12:00:00Z
endpoints_config.json  endpoints_config   1214        2026-05-20T12:00:00Z
```

Fields:

| Field | Description | Sensitive? |
| --- | --- | --- |
| `file_name` | Local-safe file name only; no full storage URI required | No |
| `artifact_type` | Config artifact category | No |
| `size_bytes` | File size | No |
| `updated_at` | Last metadata update time | No |

#### `config download`

```text
SUCCESS: config download
stage: dev
client_id: client_demo
audit_id: audit_001
output_dir: .local-configs/client_demo/audit_001
summary: downloaded 3 config files

WARNING: downloaded configs may contain sensitive operational details
next_step: keep files under .local-configs/, do not commit them, and delete them when no longer needed

files:
  - client_config.json
  - audit_config.json
  - endpoints_config.json
```

With overwrite:

```text
SUCCESS: config download
stage: dev
client_id: client_demo
audit_id: audit_001
output_dir: .local-configs/client_demo/audit_001
summary: downloaded 3 config files; existing local files were overwritten

WARNING: downloaded configs may contain sensitive operational details
next_step: keep files under .local-configs/, do not commit them, and delete them when no longer needed

files:
  - client_config.json
  - audit_config.json
  - endpoints_config.json
```

### JSON Success Examples

JSON must be one valid document with stable keys. Do not include raw config contents, secrets, raw evidence, stack traces, storage URIs containing sensitive path segments, or presigned URLs.

#### `client list --output json`

```json
{
  "status": "success",
  "command": "client list",
  "stage": "dev",
  "count": 2,
  "truncated": false,
  "clients": [
    {
      "client_id": "client_demo",
      "audit_count": 3,
      "last_updated": "2026-05-23T14:30:00Z"
    },
    {
      "client_id": "client_acme",
      "audit_count": 1,
      "last_updated": "2026-05-22T09:15:00Z"
    }
  ]
}
```

#### `audit list --output json`

```json
{
  "status": "success",
  "command": "audit list",
  "stage": "dev",
  "client_id": "client_demo",
  "count": 2,
  "truncated": false,
  "audits": [
    {
      "audit_id": "audit_001",
      "lifecycle_state": "SCHEDULED",
      "created_at": "2026-05-20T12:00:00Z",
      "updated_at": "2026-05-21T08:10:00Z",
      "schedule_status": "enabled"
    },
    {
      "audit_id": "audit_002",
      "lifecycle_state": "DRAFT",
      "created_at": "2026-05-22T10:05:00Z",
      "updated_at": "2026-05-22T10:05:00Z",
      "schedule_status": null
    }
  ]
}
```

#### `config list --output json`

```json
{
  "status": "success",
  "command": "config list",
  "stage": "dev",
  "client_id": "client_demo",
  "audit_id": "audit_001",
  "count": 3,
  "artifacts": [
    {
      "file_name": "client_config.json",
      "artifact_type": "client_config",
      "size_bytes": 1840,
      "updated_at": "2026-05-20T12:00:00Z"
    },
    {
      "file_name": "audit_config.json",
      "artifact_type": "audit_config",
      "size_bytes": 2962,
      "updated_at": "2026-05-20T12:00:00Z"
    },
    {
      "file_name": "endpoints_config.json",
      "artifact_type": "endpoints_config",
      "size_bytes": 1214,
      "updated_at": "2026-05-20T12:00:00Z"
    }
  ]
}
```

#### `config download --output json`

```json
{
  "status": "success",
  "command": "config download",
  "stage": "dev",
  "client_id": "client_demo",
  "audit_id": "audit_001",
  "output_dir": ".local-configs/client_demo/audit_001",
  "count": 3,
  "overwritten": false,
  "warning": "downloaded configs may contain sensitive operational details; keep files under .local-configs/ and do not commit them",
  "files": [
    "client_config.json",
    "audit_config.json",
    "endpoints_config.json"
  ]
}
```

### JSON Error Shape

```json
{
  "status": "error",
  "command": "config download",
  "stage": "dev",
  "client_id": "client_demo",
  "audit_id": "audit_001",
  "code": "LOCAL_FILE_EXISTS",
  "message": "one or more destination files already exist; no files were replaced",
  "next_step": "review local files, then rerun with --overwrite if replacement is intended",
  "conflicts": ["client_config.json", "audit_config.json"]
}
```

### Safety and Sanitization Requirements

- Never print secret values, API keys, tokens, credentials, raw evidence, raw endpoint payloads, raw config contents, or presigned URLs.
- `config list` may show file names and metadata only, not file contents.
- `config download` may list local file names only, not downloaded content.
- Destination path examples must prefer `.local-configs/<client_id>/<audit_id>`.
- Default download behavior must fail on existing local files; `--overwrite` is required to replace conflicts.
- `--overwrite` is a flag, not an interactive prompt.
- Do not expose or document `--version-id` as an available option in help for this release.

### Future Placeholders Not Implemented

The following may be referenced only in planning notes or roadmap documentation, not as active CLI behavior:

- Pagination tokens for list commands.
- Filtering or sorting flags beyond `--limit`.
- Selecting historical config object versions with `--version-id`.
- Interactive confirmations.
- Colored or rich terminal output.
