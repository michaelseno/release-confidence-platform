# Implementation Plan

## 1. Feature Overview

Workstream A1.2 (GitHub Issue #94) implements the infrastructure foundation
for evidence retention enforcement: an S3 `LifecycleConfiguration` on
`RawResultsBucket` (tag-filtered `Expiration`/`NoncurrentVersionExpiration`,
routed through EventBridge), DynamoDB `TimeToLiveSpecification` +
`StreamSpecification` on `MetadataTable`, a dead-letter queue + CloudWatch
alarm for the future `evidenceDisposalRecorder` Lambda, and
`CustodySweepClient` — the S3 per-version legal-hold tagging sweep and
cross-phase `ttl_disposal_at` removal/restore access path named by the
Technical Design's post-A1.1 amendment (Section 5.2/6/11).

This is a code-complete, non-deployed infrastructure subphase. No
`RetentionService`, CLI, Lambda handler body, or write-path integration is
implemented here.

## 2. Technical Scope

- `infra/resources/s3.yml`: four tag-filtered `LifecycleConfiguration` rules
  on `RawResultsBucket` (one per evidence-class S3 prefix), each scoped to
  `rcp-legal-hold=false`; `NotificationConfiguration.EventBridgeConfiguration`
  to route lifecycle-expiration events through EventBridge.
- `infra/resources/dynamodb.yml`: `TimeToLiveSpecification` (attribute
  `ttl_disposal_at`) and `StreamSpecification` (`NEW_AND_OLD_IMAGES`) on
  `MetadataTable`.
- `infra/resources/evidence-retention-dlq.yml` (new): `evidenceDisposalRecorderDLQ`
  (SQS) + a CloudWatch alarm on `ApproximateNumberOfMessagesVisible > 0`.
- `infra/serverless.yml`: `custom.custodyPeriodDays` per-evidence-class
  config block (no value for any stage — fail-closed gate); registers the
  new resource file.
- `src/release_confidence_platform/evidence_retention/custody_sweep_client.py`
  (new): `CustodySweepClient`.
- `src/release_confidence_platform/evidence_retention/constants.py`:
  additive-only new constants (`TTL_DISPOSAL_AT_ATTRIBUTE`,
  `CUSTODY_EXPIRES_AT_ATTRIBUTE`, `S3_EVIDENCE_CLASS_PREFIXES`).
- Test coverage for all of the above.

## 3. Source Inputs

- `docs/architecture/adr_evidence_retention_disposal_enforcement.md`
- `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
  (Section 5.2/6/8/11/12/16/17 amendment naming `CustodySweepClient`)
- `docs/product/evidence_governance_workstream_a_product_spec.md` (AC-A1-3,
  AC-A1-4, AC-A1-7)
- A1.1 merged code: `evidence_retention/{models,hold_repository,
  disposal_repository,constants,identity}.py` (read-only reference)
- `infra/resources/{s3,dynamodb}.yml`, `infra/serverless.yml` (pre-change
  state, confirmed empty of lifecycle/TTL config)
- Confirmed write-path call sites: `packages/storage/s3_client.py`,
  `reliability_intelligence/identity.py`, `deterministic_reporting/identity.py`,
  `audit_platform_integrity/identity.py::build_cert_s3_key`,
  `aggregation/repository.py` (no S3 footprint)

## 4. API Contracts Affected

No API contract changes. No CLI commands, HTTP endpoints, or Lambda
handlers are introduced by this subphase.

## 5. Data Models / Storage Affected

- `RawResultsBucket` (S3): additive `LifecycleConfiguration` +
  `NotificationConfiguration`. No existing object, versioning behavior, or
  bucket policy changes.
- `MetadataTable` (DynamoDB): additive `TimeToLiveSpecification` +
  `StreamSpecification`. No existing attribute, key schema, or item shape
  changes. **Template change only — not applied to any real AWS table by
  this subphase** (no deploy is run).
- New `evidenceDisposalRecorderDLQ` SQS queue + CloudWatch alarm — net-new
  resources, no dependency on any existing resource's shape.
- No DynamoDB item write occurs from any code added in this subphase.
  `CustodySweepClient`'s `UpdateItem` methods exist but are not yet called
  by any orchestrating service (`RetentionService` is A1.3 scope).

## 6. Files Expected to Change

- `infra/resources/s3.yml` (modified)
- `infra/resources/dynamodb.yml` (modified)
- `infra/resources/evidence-retention-dlq.yml` (new)
- `infra/serverless.yml` (modified)
- `src/release_confidence_platform/evidence_retention/constants.py` (modified, additive)
- `src/release_confidence_platform/evidence_retention/custody_sweep_client.py` (new)
- `pyproject.toml` (modified — new dev-only test dependency, see Section 8)
- `uv.lock` (modified — lockfile update for the above)
- `tests/unit/evidence_retention/test_custody_sweep_client.py` (new)
- `tests/unit/test_infra_configuration.py` (modified, additive)

## 7. Security / Authorization Considerations

- `CustodySweepClient` has no `put_object`/`delete_object`/`PutItem`/
  `DeleteItem`-capable method — enforced structurally (no such method
  exists) and defensively (internal DynamoDB/S3 dispatch helpers reject any
  method name outside a fixed allowlist of `{query, update_item}` /
  `{list_object_versions, get_object_tagging, put_object_tagging}`).
- Every `UpdateItem` call is preceded by `_assert_custody_field_only_update()`,
  which raises `AssertionError` if the target SK is `#LEGALHOLD#`/`#DISPOSAL#`-shaped
  or if the `UpdateExpression` would touch any attribute other than
  `ttl_disposal_at`. This does not weaken `_assert_retention_sk()`/
  `_assert_disposal_sk()` in `hold_repository.py`/`disposal_repository.py`
  (neither file is touched).
- No secrets, tokens, or new attack surface. No IAM policy changes are made
  in this subphase (`CustodySweepClient` has no caller yet, so no Lambda
  role needs its permissions; A1.3 wires the caller and its IAM grants).
- Custody-period duration values remain unset everywhere in `serverless.yml`
  per AC-A1-5.

## 8. Dependencies / Constraints

- **New dev-only dependency: `pyyaml>=6,<7`**, added to
  `[project.optional-dependencies].dev` in `pyproject.toml`. Justification:
  the mandatory test-coverage requirement is to "load and YAML-parse" the
  modified/new template files to catch syntax errors; this repo has no
  existing YAML-parsing test pattern (the pre-existing
  `test_infra_configuration.py` uses only plain-text substring assertions)
  and no YAML parser is available in the stdlib or any existing dependency
  (boto3/botocore parse JSON service models, not YAML). PyYAML is small,
  widely used, and added only to the `dev` extra — it is never imported by
  any `src/` runtime module and is not part of the Lambda deployment
  package (`apps/backend/requirements.txt` is unchanged). Installed and
  import-validated via `uv sync --extra dev`.
- No deployment (`serverless deploy`/`sls deploy`/`cdk deploy`) is run.
- No AWS-side apply of any kind occurs.

## 9. Assumptions

**Assumption (S3 Lifecycle rule structure — per-evidence-class, not a
single bucket-wide rule; not escalated, low-risk).** The companion ADR
Decision 1 describes "a single bucket-wide lifecycle rule," while Decision 5
requires the custody-period duration to be a **per-evidence-class**
configuration value, and each evidence class corresponds to a distinct,
non-overlapping S3 prefix (`raw-results/`, `intelligence/`, `reports/`,
`integrity/`). Since a single CloudFormation `LifecycleConfiguration` rule's
`Expiration.Days`/`NoncurrentVersionExpiration.NoncurrentDays` are each a
single scalar, achieving a genuinely different custody-period duration per
evidence class requires one rule per prefix. I implemented four rules (one
per confirmed evidence-class prefix), each filtered on `Prefix` AND the
`rcp-legal-hold=false` tag, each referencing that evidence class's own
`custom.custodyPeriodDays.<class>.<stage>` value. This preserves "single
mechanism, uniformly applied, no per-phase opt-in" (FR-A1-6 — the mechanism
itself, tag-filter inversion, is identical across all four rules; no phase
has to opt in, since the `rcp-legal-hold` tag is set uniformly at write time)
while honoring the explicit per-evidence-class parameterization requirement.
This is a low-risk implementation-detail resolution of an ambiguity between
two ADR statements, not a product-behavior change — flagging for awareness
rather than escalating, since AC-A1-5/FR-A1-3 are satisfied either way and
no evidence class's actual behavior differs from what the ADR describes.

**Assumption (fail-closed mechanism — no-fallback variable reference over
an explicit `null`-coalescing trick).** The dispatch brief suggested
`${self:custom.custodyPeriodDays....${self:provider.stage}, null}` as one
possible fail-closed pattern. I instead used the exact no-fallback pattern
already established in this same file for `logRetentionInDays`
(`${self:custom.custodyPeriodDays.<class>.${self:provider.stage}}`, with no
`custodyPeriodDays.<class>` stage key populated). An unresolved Serverless
Framework variable reference fails `sls package`/`sls deploy` outright with
an explicit "cannot resolve variable" error — this is a stronger fail-closed
guarantee than a `, null` fallback (which risks rendering literal YAML
`null` into the compiled template, deferring the failure to CloudFormation's
own type validation of `Days`/`NoncurrentDays` rather than failing at the
Serverless Framework layer) and reuses an existing, already-proven pattern
in this exact file rather than introducing a new one.

## 10. Validation Plan

- `uv run ruff check` on all new/modified `src/`/`tests/` files (scoped).
- `uv run pytest tests/unit/evidence_retention/ tests/unit/test_infra_configuration.py -v`
- Full regression suite: `uv run pytest -q`
- YAML syntax validation of all four modified/new template files via
  `yaml.safe_load()` (new test).
- Explicit documentation (test + report) of what YAML-parse validation does
  *not* cover (Serverless variable resolution, CFN schema validation) —
  those require the Serverless CLI/Node toolchain and are out of scope for
  this Python test suite.
