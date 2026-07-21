# Implementation Report

## 1. Summary of Changes

Implemented the Workstream A1.2 infrastructure foundation (GitHub Issue
#94): S3 `LifecycleConfiguration` on `RawResultsBucket` (four tag-filtered
rules, one per evidence-class prefix, routed through EventBridge), DynamoDB
`TimeToLiveSpecification` + `StreamSpecification` on `MetadataTable`, a new
`evidenceDisposalRecorderDLQ` SQS queue + CloudWatch depth alarm, the
`custom.custodyPeriodDays` per-evidence-class configuration gate in
`serverless.yml`, and `CustodySweepClient` — the S3 per-version legal-hold
tagging sweep and cross-phase `ttl_disposal_at` removal/restore access path
named by the Technical Design's post-A1.1 amendment. This is a
code-complete, non-deployed infrastructure subphase: no deployment command
was run, no AWS-side apply occurred, and no `RetentionService`, CLI, Lambda
handler body, or write-path integration was implemented.

## 2. Files Modified

- `infra/resources/s3.yml` — added `LifecycleConfiguration` (four rules) and
  `NotificationConfiguration.EventBridgeConfiguration` to `RawResultsBucket`.
- `infra/resources/dynamodb.yml` — added `TimeToLiveSpecification` and
  `StreamSpecification` to `MetadataTable`.
- `infra/resources/evidence-retention-dlq.yml` (new) — `evidenceDisposalRecorderDLQ`
  (SQS) + `evidenceDisposalRecorderDLQAlarm` (CloudWatch).
- `infra/serverless.yml` — added `custom.custodyPeriodDays` block (empty for
  every evidence class/stage); registered the new resource file.
- `src/release_confidence_platform/evidence_retention/constants.py` —
  additive-only: `TTL_DISPOSAL_AT_ATTRIBUTE`, `CUSTODY_EXPIRES_AT_ATTRIBUTE`,
  `S3_EVIDENCE_CLASS_PREFIXES`. No existing constant, SK marker, or bounded
  set was changed.
- `src/release_confidence_platform/evidence_retention/custody_sweep_client.py`
  (new) — `CustodySweepClient` + `_assert_custody_field_only_update()`.
- `pyproject.toml` — added `pyyaml>=6,<7` to `[project.optional-dependencies].dev`
  (test-only; not a runtime or Lambda-package dependency — see Section 9).
- `uv.lock` — regenerated via `uv sync --extra dev` to include PyYAML and
  its transitive dependencies.
- `tests/unit/test_infra_configuration.py` — 12 new tests, additive; no
  existing test was modified.
- `tests/unit/evidence_retention/test_custody_sweep_client.py` (new) — 31
  test functions (36 collected items, one parametrized ×6).

**Files explicitly not touched** (per dispatch scope): `hold_repository.py`,
`disposal_repository.py`, `models.py`, `identity.py`. No `RetentionService`,
CLI command, Lambda handler body, or Phase 1–7 write-path file was created
or modified.

## 3. API Contract Implementation

No API contract changes. This subphase introduces no CLI commands, HTTP
endpoints, or Lambda handlers.

## 4. Data / Persistence Implementation

**S3 (`RawResultsBucket`) — template change, not deployed:**

- Four `LifecycleConfiguration` rules, one per evidence-class prefix
  (`raw-results/`, `intelligence/`, `reports/`, `integrity/`), each:
  - `Filter.And` combining `Prefix` (the evidence-class S3 prefix) with a
    `Tags` match on `rcp-legal-hold=false` — an object/version tagged
    `rcp-legal-hold=true` is excluded from both `Expiration` and
    `NoncurrentVersionExpiration` by S3's exact-match tag-filter semantics
    (ADR Decision 2 — tag-filter inversion, not S3 Object Lock).
  - `Expiration.Days` / `NoncurrentVersionExpiration.NoncurrentDays` both
    reference `${self:custom.custodyPeriodDays.<evidence_class>.${self:provider.stage}}`
    — no evidence class or stage has a value defined anywhere in
    `serverless.yml`.
  - Phase 4 aggregation is correctly excluded (DynamoDB-only, no S3
    footprint — see Section 9, verification performed).
- `NotificationConfiguration.EventBridgeConfiguration: {}` enables
  EventBridge delivery for all bucket notification events, including future
  `s3:LifecycleExpiration:*` events. The EventBridge rule(s) that filter for
  those events and target a Lambda are A1.3/A1.4 scope — no such rule exists
  yet.

**DynamoDB (`MetadataTable`) — template change, not deployed, and does not
imply this has been applied to any real AWS table:**

- `TimeToLiveSpecification: {AttributeName: ttl_disposal_at, Enabled: true}`.
- `StreamSpecification: {StreamViewType: NEW_AND_OLD_IMAGES}`.
- No `AttributeDefinitions`, `KeySchema`, or existing item shape changed.

**New standalone resources (`evidence-retention-dlq.yml`):**

- `evidenceDisposalRecorderDLQ` — `AWS::SQS::Queue`, 14-day
  `MessageRetentionPeriod` (SQS's maximum, chosen so a dropped
  disposal-recording attempt remains inspectable for as long as AWS
  allows).
- `evidenceDisposalRecorderDLQAlarm` — `AWS::CloudWatch::Alarm` on
  `AWS/SQS ApproximateNumberOfMessagesVisible > 0` for the queue, 1
  evaluation period of 300s, `TreatMissingData: notBreaching`.
- Neither resource references or depends on any Lambda function. No
  `AWS::Lambda::Function` or `AWS::Lambda::EventSourceMapping` resource
  exists anywhere in this file or in `serverless.yml`'s `functions:` block
  for `evidenceDisposalRecorder` — verified by
  `test_evidence_retention_dlq_template_defines_no_lambda_function` and
  `test_serverless_defines_no_evidence_disposal_recorder_function`.

**DynamoDB writes performed by any code added in this subphase: none.**
`CustodySweepClient`'s `UpdateItem`-issuing methods exist but have no
caller yet (`RetentionService` is A1.3 scope) — no orchestration path
invokes them.

## 5. Key Logic Implemented

**`CustodySweepClient`** (`custody_sweep_client.py`):

- `remove_ttl_disposal_at(client_id, audit_id) -> int` — queries
  `PK=CLIENT#{client_id}`, `SK begins_with AUDIT#{audit_id}` (paginated via
  `LastEvaluatedKey`), and for every item carrying `ttl_disposal_at`, issues
  a guarded `UpdateItem REMOVE ttl_disposal_at`. Items without the attribute
  are skipped, making the operation safely re-invocable.
- `restore_ttl_disposal_at(client_id, audit_id, now_epoch_seconds) -> int` —
  same query; for every item with a recorded `custody_expires_at` but no
  current `ttl_disposal_at`, issues a guarded
  `UpdateItem SET ttl_disposal_at = MAX(custody_expires_at, now)`. Items
  already carrying `ttl_disposal_at`, or lacking `custody_expires_at`
  entirely, are skipped.
- `retag_s3_versions(client_id, audit_id, legal_hold: bool) -> int` — for
  each of the four evidence-class prefixes, lists every object version
  under `{prefix}/{client_id}/{audit_id}/` (paginated via
  `NextKeyMarker`/`NextVersionIdMarker`, skipping delete markers, which
  carry no content and cannot be tagged), reads each version's existing tag
  set, merges in `rcp-legal-hold={true|false}` (preserving every other tag,
  in particular `rcp-evidence-class`), and writes the merged set back via
  `PutObjectTagging`.
- `_assert_custody_field_only_update(sk, expression_attribute_names)` — the
  required guard. Raises `AssertionError` if `sk` contains `#LEGALHOLD` or
  `#DISPOSAL`, or if the set of attribute names actually referenced by
  `expression_attribute_names` (i.e., what the `UpdateExpression` will
  touch) is not exactly `{"ttl_disposal_at"}`. Called before every
  `UpdateItem` in both `_remove_ttl_disposal_at_item()` and
  `_restore_ttl_disposal_at_item()`.
- Structural allowlists on the two internal dispatch helpers
  (`_call_dynamodb`, `_call_s3`): each raises `AssertionError` if asked to
  invoke any method name outside a fixed set (`{query, update_item}` for
  DynamoDB; `{list_object_versions, get_object_tagging, put_object_tagging}`
  for S3) — a second, code-level enforcement layer beyond "the method
  doesn't exist," so a future change to this same file cannot silently
  reintroduce a `put_item`/`put_object`/`delete_object` call path through
  the generic dispatcher.

## 6. Security / Authorization Implemented

- `CustodySweepClient` has no `put_object`, `delete_object`, `PutItem`, or
  `DeleteItem`-capable method, verified both structurally (`hasattr`
  assertions in `test_custody_sweep_client.py`) and behaviorally (the
  dispatch-helper allowlist tests).
- `_assert_custody_field_only_update()` is exercised with negative tests in
  every direction specified: rejects `#LEGALHOLD#`-shaped SKs (both
  current-state and event-log forms), rejects `#DISPOSAL#`-shaped SKs,
  rejects an `UpdateExpression` touching a non-`ttl_disposal_at` attribute,
  and rejects one touching `ttl_disposal_at` *plus* another attribute (the
  guard requires the touched-attribute set to equal `{"ttl_disposal_at"}`
  exactly, not merely contain it). A positive test confirms a valid
  `ttl_disposal_at`-only update on an ordinary (non-guarded) SK is accepted.
- `_assert_retention_sk()` / `_assert_disposal_sk()` in
  `hold_repository.py`/`disposal_repository.py` are untouched — neither file
  was opened for writing in this dispatch.
- No IAM policy changes. `CustodySweepClient` has no caller yet, so no
  Lambda execution role requires new permissions in this subphase; A1.3
  will need to grant its eventual caller `dynamodb:Query`/`UpdateItem` on
  `MetadataTable` and `s3:ListBucketVersions`/`GetObjectTagging`/
  `PutObjectTagging` on `RawResultsBucket`, scoped as the Technical Design
  Section 12 specifies — not done here, since no function references this
  class yet.
- No custody-period duration value exists anywhere in `serverless.yml`
  (verified by `test_custody_period_days_config_defines_no_value_for_any_stage`).
  No test fixture in `test_custody_sweep_client.py` uses a real-looking
  custody-period duration as a default; test values used (e.g., epoch
  seconds `100`/`500`/`900` in the `restore_ttl_disposal_at` clamp tests)
  are arbitrary integers exercising comparison logic, not duration
  defaults, and appear only inside the test file.

## 7. Error Handling Implemented

- `AssertionError` from `_assert_custody_field_only_update()` and from both
  dispatch-helper allowlist checks — programming-error guards, not
  user-facing validation, consistent with the existing `_assert_retention_sk`/
  `_assert_disposal_sk`/`_assert_phase7_sk` convention.
- DynamoDB client/request failures translated via the existing
  `storage_error_from_dynamodb_client_error`/`_request_error` helpers
  (identical pattern to `HoldRepository`/`DisposalRepository`/
  `CertificationRepository`).
- S3 client/request failures wrapped as `StorageError("...",
  "S3_CUSTODY_SWEEP_FAILURE")` — no internal exception detail or AWS error
  message is passed through unsanitized to a caller beyond the wrapped
  message (this class currently has no caller to observe the boundary in
  practice; the wrapping exists for when A1.3 wires one in).
- Infra: an unresolved `custom.custodyPeriodDays.<class>.<stage>` reference
  fails Serverless Framework variable resolution outright at
  package/deploy time (an explicit "cannot resolve variable" error) rather
  than silently defaulting — this is the deployment-gate mechanism (see
  Section 11).

## 8. Observability / Logging

No structured logging is added in this subphase. `CustodySweepClient` has no
caller yet; `RetentionService` (A1.3 scope) is the appropriate place for the
`place_legal_hold`/`release_legal_hold` structured log events the Technical
Design Section 13 calls for, consistent with how A1.1's report reasoned
about `HoldRepository`/`DisposalRepository` (neither logs directly either).
The CloudWatch alarm on `evidenceDisposalRecorderDLQ` is the
observability surface introduced by this subphase specifically (infra-level,
not application-level logging).

## 9. Assumptions Made

1. **S3 Lifecycle rule structure — four per-prefix rules, not one
   bucket-wide rule (flagged, not silently resolved).** The ADR's Decision 1
   describes "a single bucket-wide lifecycle rule," while Decision 5/AC-A1-5
   require the custody-period duration to be a genuinely per-evidence-class
   value, and CloudFormation's `Expiration.Days`/`NoncurrentDays` are each a
   single rule-level scalar. I implemented one rule per evidence-class
   prefix (four total: `raw-results/`, `intelligence/`, `reports/`,
   `integrity/`), each filtered on `Prefix` AND `rcp-legal-hold=false`, each
   independently referencing its own evidence class's custody-period
   config key. The *mechanism* (tag-filter inversion) remains single and
   uniform across all four rules — no phase opts in or out, since the
   legal-hold tag is set the same way regardless of evidence class — so
   FR-A1-6 ("no per-phase opt-in") is preserved. This resolves an ambiguity
   between two ADR statements rather than a genuine conflict with either;
   documented here for architecture review rather than silently decided.

2. **`pyyaml` added as a new dev-only dependency (flagged, justified in
   Section 8 of the plan).** No YAML parser exists in this repo's stdlib or
   existing dependencies, and no prior YAML-parsing test pattern existed
   (`test_infra_configuration.py` used only plain-text substring
   assertions before this change). The explicit test-coverage requirement
   for this subphase — "at minimum write a test that loads and YAML-parses
   the three modified/new template files" — could not be satisfied without
   either adding a parser or writing a hand-rolled one; a hand-rolled parser
   would itself be a larger, riskier, less-vetted addition than a one-line
   `pyyaml` dev dependency. Added to `[project.optional-dependencies].dev`
   only — verified absent from `apps/backend/requirements.txt` (the Lambda
   package manifest) and from the main `dependencies` array.

3. **DynamoDB Query pagination reuses the codebase's established
   `encode_dynamodb_call_kwargs`/`decode_dynamodb_response` idempotent
   re-encoding behavior for `ExclusiveStartKey`/`LastEvaluatedKey`
   round-tripping**, identical to how every other repository in this
   package already round-trips low-level DynamoDB attribute-value shapes.
   Not a new assumption introduced by this subphase — verified by reading
   `storage/dynamodb_codec.py`'s `_is_attribute_value()` idempotency check
   before relying on it.

No assumption above changes external behavior, security, billing,
permissions, or API contracts. Assumption 1 is the one most likely to
warrant explicit architect sign-off, since it resolves a genuine ambiguity
in the companion ADR's own text (Decision 1 vs. Decision 5) rather than a
pure implementation-detail choice.

## 10. Validation Performed

Scoped lint (new/modified files only):

```
$ uv run ruff check src/release_confidence_platform/evidence_retention/ tests/unit/evidence_retention/ tests/unit/test_infra_configuration.py
All checks passed!
```

New test suite:

```
$ uv run pytest tests/unit/evidence_retention/ tests/unit/test_infra_configuration.py -v
============================= test session starts ==============================
platform darwin -- Python 3.11.11, pytest-8.4.2, pluggy-1.6.0
collected 117 items / 2 deselected  (2 skipped shown below)
...
tests/unit/evidence_retention/test_custody_sweep_client.py::test_assert_custody_field_only_update_accepts_ttl_only_update_on_run_metadata_sk PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_assert_custody_field_only_update_accepts_ttl_only_update_on_report_metadata_sk PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_assert_custody_field_only_update_rejects_legal_hold_current_state_sk PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_assert_custody_field_only_update_rejects_legal_hold_event_sk PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_assert_custody_field_only_update_rejects_disposal_sk PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_assert_custody_field_only_update_rejects_non_ttl_attribute PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_assert_custody_field_only_update_rejects_ttl_plus_other_attribute PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_assert_custody_field_only_update_rejects_sk_with_both_prohibited_markers PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_custody_sweep_client_has_no_write_or_delete_capable_method[put_object] PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_custody_sweep_client_has_no_write_or_delete_capable_method[delete_object] PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_custody_sweep_client_has_no_write_or_delete_capable_method[PutItem] PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_custody_sweep_client_has_no_write_or_delete_capable_method[DeleteItem] PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_custody_sweep_client_has_no_write_or_delete_capable_method[put_item] PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_custody_sweep_client_has_no_write_or_delete_capable_method[delete_item] PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_call_dynamodb_rejects_disallowed_method_name PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_call_dynamodb_rejects_delete_item PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_call_s3_rejects_disallowed_method_name PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_call_s3_rejects_delete_object PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_remove_ttl_disposal_at_updates_only_items_carrying_the_attribute PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_remove_ttl_disposal_at_returns_zero_when_no_items_carry_the_attribute PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_remove_ttl_disposal_at_item_builds_remove_expression_and_asserts_guard PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_remove_ttl_disposal_at_item_raises_on_legal_hold_sk PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_restore_ttl_disposal_at_clamps_to_now_when_custody_already_elapsed PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_restore_ttl_disposal_at_uses_custody_expires_at_when_not_yet_elapsed PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_restore_ttl_disposal_at_skips_items_without_custody_expires_at PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_restore_ttl_disposal_at_skips_items_that_already_carry_ttl_disposal_at PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_restore_ttl_disposal_at_item_builds_set_expression_and_asserts_guard PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_restore_ttl_disposal_at_item_raises_on_disposal_sk PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_query_audit_items_uses_correct_key_condition PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_query_audit_items_paginates_via_last_evaluated_key PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_retag_s3_versions_covers_all_four_evidence_class_prefixes PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_retag_s3_versions_retags_every_returned_version PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_retag_s3_versions_uses_false_value_on_release PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_retag_object_version_merges_and_preserves_existing_tags PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_list_object_versions_yields_key_version_pairs_and_paginates PASSED
tests/unit/evidence_retention/test_custody_sweep_client.py::test_list_object_versions_skips_delete_markers PASSED
... (test_hold_repository.py / test_disposal_repository.py / test_models.py -- all 49 A1.1 tests, unchanged, PASSED) ...
tests/unit/test_infra_configuration.py::test_serverless_configuration_contains_required_stages_and_names PASSED
tests/unit/test_infra_configuration.py::test_serverless_stage_guard_rejects_unsupported_stages PASSED
tests/unit/test_infra_configuration.py::test_resource_fragments_reference_required_resources PASSED
tests/unit/test_infra_configuration.py::test_serverless_lambda_environment_avoids_reserved_keys PASSED
tests/unit/test_infra_configuration.py::test_serverless_grants_prefix_scoped_s3_listbucket_for_runtime_bucket PASSED
tests/unit/test_infra_configuration.py::test_serverless_scopes_runtime_s3_object_permissions_to_required_prefixes PASSED
tests/unit/test_infra_configuration.py::test_backend_lambda_requirements_manifest_includes_requests PASSED
tests/unit/test_infra_configuration.py::test_serverless_packages_backend_python_requirements PASSED
tests/unit/test_infra_configuration.py::test_serverless_artifact_contains_backend_handler_and_requests_dependencies_if_present SKIPPED
tests/unit/test_infra_configuration.py::test_evidence_retention_template_files_are_syntactically_valid_yaml PASSED
tests/unit/test_infra_configuration.py::test_serverless_variable_resolution_requires_serverless_cli SKIPPED
tests/unit/test_infra_configuration.py::test_s3_lifecycle_configuration_has_one_tag_filtered_rule_per_evidence_class PASSED
tests/unit/test_infra_configuration.py::test_s3_lifecycle_days_reference_custody_period_config_not_hardcoded PASSED
tests/unit/test_infra_configuration.py::test_s3_notification_configuration_routes_through_eventbridge PASSED
tests/unit/test_infra_configuration.py::test_dynamodb_ttl_specification_targets_ttl_disposal_at_attribute PASSED
tests/unit/test_infra_configuration.py::test_dynamodb_stream_specification_uses_new_and_old_images PASSED
tests/unit/test_infra_configuration.py::test_evidence_disposal_recorder_dlq_and_alarm_resources_present PASSED
tests/unit/test_infra_configuration.py::test_evidence_retention_dlq_template_defines_no_lambda_function PASSED
tests/unit/test_infra_configuration.py::test_serverless_registers_evidence_retention_dlq_resource_file PASSED
tests/unit/test_infra_configuration.py::test_serverless_defines_no_evidence_disposal_recorder_function PASSED
tests/unit/test_infra_configuration.py::test_custody_period_days_config_defines_no_value_for_any_stage PASSED

======================== 115 passed, 2 skipped in 0.36s =========================
```

Full existing suite (regression check):

```
$ uv run pytest -q
........................................................................ [  4%]
... (full run) ...
1517 passed, 2 skipped in 2.60s
```

(1517 vs. A1.1's reported 1459 baseline: +58 net collected items from this
subphase's new tests, no failures, no new skips beyond the two documented
above and the one pre-existing PDF-formatter skip pattern A1.1 previously
flagged, which resolved cleanly here since `fpdf2` is already a main
dependency and installed via `uv sync --extra dev` in this environment.)

Lint (scoped to new/modified files):

```
$ uv run ruff check src/release_confidence_platform/evidence_retention/ tests/unit/evidence_retention/ tests/unit/test_infra_configuration.py
All checks passed!
```

`ruff format --check` on the three touched/new `src`/test files reports the
same pre-existing repo-wide drift A1.1's report already documented (ruff's
formatter would collapse certain multi-line signatures this codebase's
existing reference files also use) — confirmed by running the identical
check against `audit_platform_integrity/repository.py` and
`evidence_retention/hold_repository.py`, both of which also "would be
reformatted." Not treated as a regression; not auto-reformatted, to avoid
diverging from the exact style these new files were modeled on.

YAML syntax validation (all four modified/new template files, standalone
sanity check ahead of the automated test):

```
$ uv run python3 -c "
import yaml
for f in ['infra/resources/s3.yml','infra/resources/dynamodb.yml','infra/resources/evidence-retention-dlq.yml','infra/serverless.yml']:
    with open(f) as fh:
        data = yaml.safe_load(fh)
    print(f, 'OK', type(data))
"
infra/resources/s3.yml OK <class 'dict'>
infra/resources/dynamodb.yml OK <class 'dict'>
infra/resources/evidence-retention-dlq.yml OK <class 'dict'>
infra/serverless.yml OK <class 'dict'>
```

**Not performed, and explicitly out of scope for this test suite:** `sls
print`/`sls package`/`sls deploy` (Serverless CLI variable resolution and
CloudFormation schema validation) — requires the Node/Serverless toolchain,
which this Python-only validation pass does not invoke. Documented via
`test_serverless_variable_resolution_requires_serverless_cli`
(`pytest.skip` with an explanatory message) rather than fabricated.

## 11. Known Limitations / Follow-Ups

- **Custody-period deployment gate mechanism.** No custody-period duration
  value exists anywhere in `serverless.yml` for any evidence class or
  stage (`custom.custodyPeriodDays.<class>` is `{}` for all four evidence
  classes). The S3 `LifecycleConfiguration.Days`/`NoncurrentDays`
  properties reference `${self:custom.custodyPeriodDays.<class>.${self:provider.stage}}`
  with **no fallback value** — this exactly mirrors the existing,
  already-proven `logRetentionInDays` pattern in the same file (also a
  per-stage config with no fallback). Referencing an unresolved key of this
  form causes Serverless Framework to fail `sls package`/`sls deploy`
  outright with an explicit "cannot resolve variable" error, before any
  CloudFormation template is even rendered. This fails closed by
  construction: there is no code path in which an unset custody-period
  value silently becomes `0`, an empty string, or any other value AWS would
  accept — the deploy simply cannot proceed. I chose this over a
  `${..., null}` fallback specifically because a `null` fallback would
  still let a compiled template with `Days: null` reach CloudFormation,
  deferring (and potentially weakening) the failure to CFN's own property
  type validation instead of failing earlier, at the Serverless Framework
  layer, using a pattern this file already trusts elsewhere.
- Enabling DynamoDB TTL/Streams and the S3 Lifecycle/notification
  configuration are template changes only. **No deploy was run; none of
  this has been applied to any real AWS `MetadataTable` or
  `RawResultsBucket` in any stage.**
- No `RetentionService`, CLI command, Lambda handler body, or
  `evidenceDisposalRecorder` event-source-mapping wiring exists — all
  explicitly out of scope, confirmed absent by
  `test_serverless_defines_no_evidence_disposal_recorder_function` and
  `test_evidence_retention_dlq_template_defines_no_lambda_function`.
- No backlog/backfill migration logic was written, stubbed, or silently
  resolved. `CustodySweepClient` operates only against an explicit
  `(client_id, audit_id)` pair passed by its future caller; there is no
  "sweep everything" entry point.
- **Discrepancy check performed, none found requiring escalation.** Per the
  dispatch's required verification, I read `aggregation/repository.py`,
  `reliability_intelligence/repository.py` and `identity.py`,
  `deterministic_reporting/repository.py` and `identity.py`, and
  `audit_platform_integrity/repository.py` and `identity.py`. All four
  confirmed `PK=CLIENT#{client_id}` / `SK begins_with AUDIT#{audit_id}...`
  exactly as the Technical Design assumes, and all four S3-writing phases
  (1/2/3, 5, 6, 7) confirmed the `{prefix}/{client_id}/{audit_id}/...` key
  structure `CustodySweepClient.retag_s3_versions()` relies on. Phase 4
  aggregation was independently confirmed to have zero S3 footprint
  (`aggregation/repository.py`/`lineage.py` never call any S3 client). The
  one genuine ambiguity found — the ADR's "single bucket-wide rule"
  language (Decision 1) versus its own per-evidence-class custody-period
  requirement (Decision 5) — is documented as Assumption 1 in Section 9
  above and flagged for architecture review; it is a resolvable ambiguity
  between two ADR statements, not a Technical-Design-vs.-code discrepancy.
- `ruff format --check` drift on the touched files is pre-existing and
  repo-wide (see Section 10); not blocking, flagged for awareness only.

## 12. Commit Status

Not committed. Per the dispatch instructions, the working tree is left
as-is for QA and human review before commit. No PR was opened.
