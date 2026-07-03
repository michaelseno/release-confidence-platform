# Operator CLI `rcp`

Internal operator entry point for the Release Confidence Platform. All commands are engineering-only and do not expose raw evidence, secrets, or customer-facing output.

Every command requires `--stage dev|staging|prod`. AWS resources resolve from `config/stages/{stage}.json`; non-empty `RCP_*` environment variables take precedence.

---

## Command Groups

| Group | Purpose |
|---|---|
| `audit` | Validate, create, schedule, run, cancel, and list audits |
| `client` | Discover known clients |
| `config` | Inspect, download, and initialize audit configuration |
| `retrieve` | Read-only engineering retrieval (Phase 4 aggregation + Phase 5 intelligence) |
| `generate` | Generate Phase 5 intelligence artifacts |

---

## `audit`

### `audit validate`

Validate local client, audit, and endpoint configuration files without writing to AWS.

```
rcp audit validate \
  --client-config <path> \
  --audit-config <path> \
  --endpoints-config <path> \
  --stage <dev|staging|prod>
```

| Argument | Required | Description |
|---|---|---|
| `--client-config` | Yes | Path to `client_config.json` |
| `--audit-config` | Yes | Path to `audit_config.json` |
| `--endpoints-config` | Yes | Path to `endpoints.json` |
| `--stage` | Yes | Deployment stage |
| `--output` | No | Output format: `text` (default) or `json` |

---

### `audit create`

Validate configs, upload deterministic S3 config objects, and write a `DRAFT` audit metadata record.

```
rcp audit create \
  --client-config <path> \
  --audit-config <path> \
  --endpoints-config <path> \
  --stage <dev|staging|prod> \
  [--dry-run] \
  [--force]
```

| Argument | Required | Description |
|---|---|---|
| `--client-config` | Yes | Path to `client_config.json` |
| `--audit-config` | Yes | Path to `audit_config.json` |
| `--endpoints-config` | Yes | Path to `endpoints.json` |
| `--stage` | Yes | Deployment stage |
| `--dry-run` | No | Validate and compute without writing to S3 or DynamoDB |
| `--force` | No | Overwrite an existing `DRAFT` audit record |
| `--output` | No | Output format: `text` (default) or `json` |

---

### `audit schedule`

Load persisted audit config and metadata, create enabled EventBridge schedules, and transition the audit lifecycle to `SCHEDULED`. Production scheduling requires `--allow-production`.

```
rcp audit schedule \
  --client-id <client_id> \
  --audit-id <audit_id> \
  --stage <dev|staging|prod> \
  [--dry-run] \
  [--allow-production]
```

| Argument | Required | Description |
|---|---|---|
| `--client-id` | Yes | Client identifier |
| `--audit-id` | Yes | Audit identifier |
| `--stage` | Yes | Deployment stage |
| `--dry-run` | No | Validate scheduling without creating EventBridge rules |
| `--allow-production` | No | Required when `--stage prod`; acts as a guard against accidental production scheduling |
| `--output` | No | Output format: `text` (default) or `json` |

---

### `audit run`

Manually invoke the audit run orchestrator with `triggered_by=manual`.

```
rcp audit run \
  --client-id <client_id> \
  --audit-id <audit_id> \
  --stage <dev|staging|prod> \
  --scenario-type <type> \
  [--run-id <run_id>] \
  [--schedule-type <type>] \
  [--dry-run]
```

| Argument | Required | Description |
|---|---|---|
| `--client-id` | Yes | Client identifier |
| `--audit-id` | Yes | Audit identifier |
| `--stage` | Yes | Deployment stage |
| `--scenario-type` | Yes | One of: `baseline_health`, `burst_stability`, `repeated_stability`, `response_consistency` |
| `--run-id` | No | Explicit run ID to assign; auto-generated if omitted |
| `--schedule-type` | No | One of: `manual`, `baseline`, `burst`, `repeated` |
| `--dry-run` | No | Validate without invoking the orchestrator Lambda |
| `--output` | No | Output format: `text` (default) or `json` |

---

### `audit cancel`

Record cancellation intent, clean EventBridge schedules, retain metadata, and exit with code `3` if cleanup is only partially successful.

```
rcp audit cancel \
  --client-id <client_id> \
  --audit-id <audit_id> \
  --stage <dev|staging|prod> \
  [--reason <reason>] \
  [--dry-run]
```

| Argument | Required | Description |
|---|---|---|
| `--client-id` | Yes | Client identifier |
| `--audit-id` | Yes | Audit identifier |
| `--stage` | Yes | Deployment stage |
| `--reason` | No | Cancellation reason string (default: `operator_cancelled`) |
| `--dry-run` | No | Validate without making changes |
| `--output` | No | Output format: `text` (default) or `json` |

---

### `audit list`

List metadata-only audit summaries for a client. Does not expose raw evidence.

```
rcp audit list \
  --client-id <client_id> \
  --stage <dev|staging|prod> \
  [--limit <n>] \
  [--output json]
```

| Argument | Required | Description |
|---|---|---|
| `--client-id` | Yes | Client identifier |
| `--stage` | Yes | Deployment stage |
| `--limit` | No | Number of results to return; integer 1–1000 (default: 100) |
| `--output` | No | Output format: `text` (default) or `json` |

---

## `client`

### `client list`

List unique known clients for a stage using the client registry, with a bounded audit metadata scan as fallback.

```
rcp client list \
  --stage <dev|staging|prod> \
  [--limit <n>] \
  [--output json]
```

| Argument | Required | Description |
|---|---|---|
| `--stage` | Yes | Deployment stage |
| `--limit` | No | Number of results to return; integer 1–1000 (default: 100) |
| `--output` | No | Output format: `text` (default) or `json` |

---

## `config`

### `config list`

Inspect metadata for the three persisted config artifacts (`client_config.json`, `audit_config.json`, `endpoints.json`) without downloading their contents.

```
rcp config list \
  --client-id <client_id> \
  --audit-id <audit_id> \
  --stage <dev|staging|prod>
```

| Argument | Required | Description |
|---|---|---|
| `--client-id` | Yes | Client identifier |
| `--audit-id` | Yes | Audit identifier |
| `--stage` | Yes | Deployment stage |
| `--output` | No | Output format: `text` (default) or `json` |

---

### `config download`

Download `client_config.json`, `audit_config.json`, and `endpoints.json` to a local directory. Existing files are not replaced unless `--overwrite` is supplied. Prefer paths under `.local-configs/` (gitignored).

```
rcp config download \
  --client-id <client_id> \
  --audit-id <audit_id> \
  --output-dir <path> \
  --stage <dev|staging|prod> \
  [--overwrite]
```

| Argument | Required | Description |
|---|---|---|
| `--client-id` | Yes | Client identifier |
| `--audit-id` | Yes | Audit identifier |
| `--output-dir` | Yes | Local directory to write downloaded files to |
| `--stage` | Yes | Deployment stage |
| `--overwrite` | No | Replace existing files; omit to protect existing downloads |
| `--output` | No | Output format: `text` (default) or `json` |

---

### `config stage-info`

Show the resolved local stage resource configuration (table names, bucket, region) without making any AWS calls. Useful for verifying environment variable overrides.

```
rcp config stage-info --stage <dev|staging|prod>
```

| Argument | Required | Description |
|---|---|---|
| `--stage` | Yes | Deployment stage |
| `--output` | No | Output format: `text` (default) or `json` |

---

### `config init`

Generate local starter audit configuration files (`client_config.json`, `audit_config.json`, `endpoints.json`) from a template. Does not write to AWS.

```
rcp config init \
  --client-name <name> \
  [--defaults <dev|staging|prod>] \
  [--output-dir <path>] \
  [--timezone <tz>] \
  [--include-sample-endpoints] \
  [--overwrite] \
  [--output text|json]
```

| Argument | Required | Description |
|---|---|---|
| `--client-name` | Yes | Human-readable client name used to derive `client_id` and populate config fields |
| `--defaults` | No | Stage profile to seed default values from (default: `dev`) |
| `--output-dir` | No | Directory to write generated files to; defaults to current directory |
| `--timezone` | No | IANA timezone string for schedule generation (e.g., `America/Chicago`) |
| `--include-sample-endpoints` | No | Add sample endpoint definitions to the generated `endpoints.json` |
| `--overwrite` | No | Replace existing files; omit to protect existing configs |
| `--output` | No | Output format: `text` (default) or `json` |

---

## `retrieve`

All `retrieve` commands are **read-only**. They never modify Phase 4 or Phase 5 artifacts. All output includes a provenance envelope for traceability.

Two sub-groups are available:

- **Phase 4 Aggregation Retrieval** — 15 commands covering aggregation results, orchestration state, execution history, and engineering logs
- **Phase 5 Intelligence Retrieval** — 4 commands covering intelligence status, summary, full artifact detail, and methodology disclosure

---

### Phase 4 Aggregation Retrieval

All Phase 4 retrieval commands accept these base arguments:

| Argument | Required | Description |
|---|---|---|
| `--client` | Yes | Client identifier |
| `--audit` | Yes | Audit identifier |
| `--stage` | Yes | Deployment stage |
| `--output` | No | Output format: `human` (default) or `json` |

Commands that also accept `--run`, `--endpoint`, `--scenario` filters:

- `aggregation-results`
- `engineering-logs`
- `execution-summary`
- `audit-event-timeline`

Commands that also accept `--window` (ISO-8601 range, e.g. `2024-01-01T00:00:00Z/2024-01-02T00:00:00Z`):

- `execution-summary`
- `audit-event-timeline`
- `engineering-logs`

---

| Command | Data Source | Returns |
|---|---|---|
| `retrieve aggregation-results` | DynamoDB | Full aggregate artifact set for the audit: `AuditAggregate`, all `EndpointAggregate` records, `FailureClassificationAggregate` records, `AggregateSetCompletion` marker. Accepts `--run`, `--endpoint`, `--scenario` filters. |
| `retrieve aggregation-metadata` | DynamoDB | Aggregation job metadata: status, counts, timestamps, `aggregation_version` |
| `retrieve aggregation-lineage` | DynamoDB | Lineage manifest references, source ref counts, `manifest_hash` |
| `retrieve aggregation-status` | DynamoDB | Current aggregation job status and reason code |
| `retrieve aggregation-generation-status` | DynamoDB | Aggregation completeness and generation state summary |
| `retrieve aggregation-version` | DynamoDB | Aggregation version metadata |
| `retrieve orchestration-timeline` | DynamoDB | Chronological orchestration events for the audit |
| `retrieve lifecycle-transitions` | DynamoDB | Lifecycle state history for the audit |
| `retrieve execution-summary` | DynamoDB | Execution counts, durations, and outcome summary. Accepts `--run`, `--endpoint`, `--scenario`, `--window`. |
| `retrieve audit-event-timeline` | DynamoDB | Ordered event timeline across the full audit lifecycle. Accepts `--run`, `--endpoint`, `--scenario`, `--window`. |
| `retrieve engineering-logs` | DynamoDB | Consolidated sanitized engineering log events. Accepts `--run`, `--endpoint`, `--scenario`, `--window`. |
| `retrieve retry-history` | DynamoDB | Aggregation job retry attempts and outcomes |
| `retrieve evidence-references` | DynamoDB | Bounded lineage manifest source references, `manifest_hash` |
| `retrieve failure-summaries` | DynamoDB | Failure classification counts and reason codes |
| `retrieve processing-timeline` | DynamoDB | Per-stage processing timestamps |

**Example — aggregation results with endpoint filter:**
```bash
rcp retrieve aggregation-results \
  --client client_abc \
  --audit audit_20260626_6f433adc \
  --stage dev \
  --endpoint health_fast \
  --output json
```

---

### Phase 5 Intelligence Retrieval

All Phase 5 intelligence retrieval commands accept these base arguments:

| Argument | Required | Description |
|---|---|---|
| `--client` | Yes | Client identifier |
| `--audit` | Yes | Audit identifier |
| `--execution` | Yes | Audit execution identity (`audexec_...`) |
| `--stage` | Yes | Deployment stage |
| `--output` | No | Output format: `human` (default) or `json` |
| `--endpoint` | No | Endpoint ID filter (parsed but reserved for future scoped retrieval) |
| `--config-version` | No | Configuration version (default: `v1`) |
| `--aggregation-version` | No | Aggregation version (default: `agg_v1`) |
| `--intelligence-version` | No | Intelligence version (default: `intel_v1`) |

---

| Command | Data Source | Returns |
|---|---|---|
| `retrieve intelligence-status` | DynamoDB | Current status, `intelligence_job_id`, `composite_score`, `score_label`, `endpoint_count`, `s3_artifact_ref`, `completed_at` |
| `retrieve intelligence-summary` | DynamoDB | Full `IntelligenceMetadata` record: all stable fields including composite score, component breakdown, `aggregate_set_hash`, `intelligence_version`, `aggregation_version` |
| `retrieve intelligence-detail` | S3 artifact | Complete S3 intelligence artifact JSON: `input_lineage`, `audit_reliability_summary`, `composite_score` with component breakdown, all per-endpoint analysis (`reliability_metrics`, `stability_analysis`, `burst_analysis`, `consistency_analysis`, `endpoint_score`, `source_field_refs`), and `methodology_disclosure` |
| `retrieve intelligence-methodology` | S3 artifact | `methodology_disclosure` section only: algorithm names, weights, thresholds, label definitions, and documented limitations |

**Example — full intelligence detail:**
```bash
rcp retrieve intelligence-detail \
  --client client_lineage_issue_verification_2_1b5e3d6e \
  --audit audit_20260626_c3927ce1 \
  --execution audexec_00294bb91dc74d499e46c9788718b86a \
  --stage dev \
  --output json
```

---

## `generate`

### `generate intelligence`

Generate Phase 5 reliability intelligence from an existing Phase 4 `AggregateSetCompletion`. Requires the Phase 4 aggregation set to be complete. Idempotent by default — re-run returns `ALREADY_COMPLETE` without writing. Use `--force` to overwrite an existing complete artifact.

```
rcp generate intelligence \
  --client <client_id> \
  --audit <audit_id> \
  --execution <audit_execution_id> \
  --config-version <version> \
  --stage <dev|staging|prod> \
  [--aggregation-version <version>] \
  [--force] \
  [--dry-run] \
  [--output json|human]
```

| Argument | Required | Description |
|---|---|---|
| `--client` | Yes | Client identifier |
| `--audit` | Yes | Audit identifier |
| `--execution` | Yes | Audit execution identity (`audexec_...`) |
| `--config-version` | Yes | Configuration version (e.g., `v1`) |
| `--stage` | Yes | Deployment stage |
| `--aggregation-version` | No | Phase 4 aggregation version to consume (default: `agg_v1`) |
| `--force` | No | Re-generate and overwrite an existing `COMPLETE` artifact |
| `--dry-run` | No | Run the full computation pipeline without writing to DynamoDB or S3 |
| `--output` | No | Output format: `json` (default) or `human` |

**Success output includes:** `intelligence_job_id`, `status`, `composite_score`, `score_label`, `endpoint_count`, `s3_artifact_ref`, `aggregate_set_hash`, `completed_at`.

**Status values:**
- `COMPLETE` — intelligence generated and persisted
- `ALREADY_COMPLETE` — existing complete artifact returned; no writes performed
- `DRY_RUN` — computation successful; no writes performed

**Example:**
```bash
rcp generate intelligence \
  --client client_abc \
  --audit audit_20260626_6f433adc \
  --execution audexec_b146ca56faa44b7581686a0f1d5e11c7 \
  --config-version v1 \
  --stage dev \
  --output json
```

---

## Global Behavior

- **`--stage`** is required on every command. AWS resource names (DynamoDB table, S3 bucket, region) resolve from `config/stages/{stage}.json`. Non-empty `RCP_*` environment variables override the file values.
- **`--dry-run`** is available on mutating commands (`audit create`, `audit schedule`, `audit run`, `audit cancel`, `generate intelligence`). It validates inputs and runs computation without writing to any AWS resource.
- **`--output`** defaults differ by command group. `audit`, `client`, `config` commands default to `text`. `retrieve` and `generate intelligence` commands default to `json` or `human` depending on the subcommand. Pass `--output json` to get machine-readable output on any command.
- The CLI is internal only. It does not accept or print secrets. Discovery and retrieval commands never access Secrets Manager, raw evidence S3 objects, or `raw-results/` prefixes.

---

## Setup

Use Python 3.11 (`pyproject.toml` requires `>=3.11,<3.12`). Install in editable mode:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip setuptools
.venv/bin/python -m pip install -e .[dev]
hash -r
rcp --help
```

If `rcp --help` fails with `ModuleNotFoundError: No module named 'release_confidence_platform'` on macOS, hidden file flags on `.venv` may be blocking the editable install `.pth` file:

```bash
chflags -R nohidden .venv
.venv/bin/python -m pip install -e .
hash -r
rcp --help
```

Downloaded config files may contain sensitive operational details. Use paths under `.local-configs/` (gitignored) and do not commit downloaded files.

---

## Deferred / Not Yet Implemented

The following commands are planned but not implemented:

- `config delete`, `config archive`
- `run list`, `run inspect`
- `audit status`, `schedule status`
- Version-specific config downloads via `--version-id`
- `retrieve intelligence-*` with `--endpoint` scoped S3 filtering (deferred to `intel_v2`)
