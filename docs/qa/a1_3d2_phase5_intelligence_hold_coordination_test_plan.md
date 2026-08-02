# QA Test Plan — A1.3d.2 Phase 5 Intelligence Hold Coordination

## 1. Scope

Validate that Phase 5 (Reliability Intelligence) is correctly wired to
A1.LH1 legal-hold coordination and custody-field computation per
`docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
Section 20 (especially 20.4-20.6, 20.9-20.11) and the companion ADR's
Decision 10, Decision 11, and Non-Negotiable Invariants 27-31.

In scope: `IntelligenceRepository.put_intelligence_metadata_once`,
`update_intelligence_metadata`; `IntelligencePublisher.write_artifact`;
`operator_cli/main.py`'s `generate intelligence` dispatch block. Out of
scope: any Phase 6/7 file, `config/custody_periods.json` duration values,
issue #118 partial-success behavior, `engine.py` behavior changes (none
authorized or made).

## 2. Test Files

- `tests/unit/reliability_intelligence/test_engine_no_phase4_mutation.py` (modified)
- `tests/unit/reliability_intelligence/test_engine_idempotency.py` (modified)
- `tests/unit/reliability_intelligence/test_engine_gate.py` (modified)
- `tests/unit/test_reliability_intelligence_retrieval.py` (modified)
- `tests/unit/reliability_intelligence/test_hold_coordination.py` (new)
- `tests/unit/test_operator_cli_generate_intelligence.py` (new)

## 3. Required Coverage Checklist

### Category 3 exclusion (`IntelligenceJob`)
- [ ] `IntelligenceJob` writes never carry `custody_expires_at`,
  `ttl_disposal_at`, `evidence_class`, `rcp-legal-hold`,
  `rcp-evidence-class`, or `hold_version` — first generation, force
  regeneration, failed retry (`test_engine_no_phase4_mutation.py`).
- [ ] `IntelligenceRepository.put_intelligence_job_once` /
  `update_intelligence_job` produce zero `transact_write_items` calls and
  zero legal-hold `get_item` reads, in a fully write-capable repository
  instance (`test_hold_coordination.py`).

### Dry-run exemption
- [ ] `--dry-run` performs zero repository writes and zero publisher
  writes, with and without pre-existing COMPLETE metadata
  (`test_engine_idempotency.py`).
- [ ] `--dry-run` resolves zero `CustodyPeriodConfigLoader.resolve` calls
  and constructs zero `HoldRepository`; repository/publisher constructed
  with `hold_repository`/`custody_period_days` at `None`; existing dry-run
  output shape/exit code unaffected (`test_operator_cli_generate_intelligence.py`).

### Gate denial
- [ ] Zero `IntelligenceMetadata` writes and zero artifact writes on
  `AggregateSetCompletion` gate denial (missing, incomplete, failed).
- [ ] The gate-denial code path in `engine.py` contains no
  hold-coordination-related identifier (structural proof via
  `inspect.getsource`) (`test_engine_gate.py`).

### Retrieval independence
- [ ] `retrieve intelligence-status`/`intelligence-summary` succeed under
  three `config/custody_periods.json` `intelligence`-class shapes (present
  empty, present with only an unrelated stage, key entirely absent), with
  zero `CustodyPeriodConfigLoader.resolve` calls and zero `HoldRepository(`
  construction (`test_reliability_intelligence_retrieval.py`).

### Repository preflight (write-entry governance preflight)
- [ ] All 8 conditions (missing hold_repository, missing duration, Boolean
  True/False, string, float, zero, negative) for both
  `put_intelligence_metadata_once` and `update_intelligence_metadata`,
  each asserting exact exception type/reason code and zero downstream
  `get_item`/`transact_write_items` calls.
- [ ] Hold-before-duration precedence when both are simultaneously invalid.

### Structural
- [ ] `repository.py` source contains no `CustodyPeriodConfigLoader`
  reference and no `os.environ`/`os.getenv` reference.
- [ ] `publisher.py` source contains no `MarkerStore`/`RetentionService`/
  `CustodySweepClient`/marker/reconciliation/sweep/disposal reference.

### CREATE / regeneration contract
- [ ] CREATE unheld/active-hold/released-hold: `ttl_disposal_at`
  present/omitted correctly, `evidence_class="intelligence"`, existing
  `attribute_not_exists` condition preserved.
- [ ] A duplicate CREATE against an existing key raises
  `ConditionalWriteError`, not `HoldStateConcurrencyExceededError`, even
  when the hold-version `ConditionCheck` also fails in the same attempt —
  zero retries.
- [ ] Regeneration unheld/active-hold/released-hold: `ttl_disposal_at`
  present/omitted correctly; Put carries no `ConditionExpression`.

### Retry / race / clock / byte-boundary
- [ ] PLACE race (hold placed between read and commit) — bounded, correct
  final state.
- [ ] RELEASE race, symmetric, for both CREATE and regeneration.
- [ ] Bounded retry exhaustion → `HoldStateConcurrencyExceededError` with
  `error_type == "HOLD_STATE_CONCURRENCY_EXCEEDED"`, zero partial writes.
- [ ] Deterministic clock: monkeypatched `datetime` in
  `reliability_intelligence.repository` produces an exact,
  clock-independent `custody_expires_at`.
- [ ] A generic `ClientError` (non-condition failure) on attempt 1 raises
  `StorageError` (not `HoldStateConcurrencyExceededError`), not retried.

### Immutability / sanitizer safety
- [ ] Caller-supplied item dict is unchanged after both a successful call
  and a retry-exhaustion call, for both write methods.
- [ ] Caller-supplied stale `custody_expires_at`/`ttl_disposal_at`/
  `evidence_class` values are overridden by repository-computed values.
- [ ] A PK/SK/identifier embedding the literal digit sequence
  `2475004829` survives byte-identical on both write methods (no
  `sanitize()` call reaches the persistence path).

### Publisher
- [ ] Identity parsing: valid key; malformed key (wrong prefix, wrong
  segment count, missing `artifact.json` suffix, empty client_id/audit_id
  segment).
- [ ] Call-order proof: parse → `get_legal_hold(consistent_read=True)` →
  tag computation → `put_object`, for unheld/active/released states.
- [ ] Exact `Tagging` string per state.
- [ ] A `StorageError` from `get_legal_hold` propagates unchanged, zero
  `put_object` calls.
- [ ] An unexpected non-`StorageError` exception from `get_legal_hold` maps
  to `StorageError(..., "STORAGE_ERROR")`, zero `put_object` calls.
- [ ] Artifact immutability.
- [ ] `HOLD_COORDINATION_NOT_CONFIGURED` fail-closed when
  `hold_repository` is `None`.

### CLI dispatch (`generate intelligence`)
- [ ] `CustodyPeriodConfigLoader.resolve` called exactly once, before
  `AwsClientFactory` construction.
- [ ] Resolved integer injected into `IntelligenceRepository`; same
  `HoldRepository` instance (identity-checked) injected into both
  `IntelligenceRepository` and `IntelligencePublisher`; publisher receives
  no duration argument.
- [ ] Resolution failure (`CUSTODY_PERIOD_CONFIG_MISSING`) produces zero
  `AwsClientFactory`/boto3 client construction and zero AWS calls.
- [ ] Rendering/sanitization for `CUSTODY_PERIOD_CONFIG_MISSING`,
  `HOLD_COORDINATION_NOT_CONFIGURED`, `HOLD_STATE_CONCURRENCY_EXCEEDED`,
  and generic `STORAGE_ERROR`: reason code preserved, non-zero exit code,
  no raw traceback/AWS request ID/DynamoDB key/S3 key/client_id/audit_id
  value leaked, in both `human` and `json` output.

## 4. Regression Requirements

- Full suite (`pytest -q`) must show zero regressions versus the `main`
  baseline (Phase 1-4, 6, 7, existing Phase 5 tests all still pass).
- `git diff main -- .../engine.py` must produce zero output.
- `ruff check` / `ruff format --check` must show zero new violations in
  new files; pre-existing baseline drift in modified files is documented,
  not newly introduced.
- Changed-file set must match exactly the 13 authorized files.

## 5. Out of Scope / Explicit Non-Goals

- No test may assert a stale `PENDING`/`IN_PROGRESS` Job, an orphaned S3
  artifact, `Job`/`Metadata` status divergence, or a partially-failed
  terminal update as expected/correct/passing behavior (issue #118).
- No test may assert or require a specific custody-duration value.
- No test may assert Lambda, `environment:`, or IAM changes for Phase 5.
