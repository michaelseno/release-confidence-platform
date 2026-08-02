# Implementation Plan

## 1. Feature Overview

Subphase A1.3d.2 wires Phase 5 (Reliability Intelligence) to A1.LH1
legal-hold coordination and custody-field computation, per ADR Decision 10,
Decision 11, Non-Negotiable Invariants 27-31, and Technical Design Section
20 (especially 20.4-20.6, 20.9-20.11). `IntelligenceMetadata` (Category 2,
evidence-derived artifact) and the `intelligence/` S3 artifact (Category 1)
gain hold-coordinated writes; `IntelligenceJob` (Category 3) remains
entirely excluded. `engine.py` is not modified.

## 2. Technical Scope

- `IntelligenceRepository.put_intelligence_metadata_once` and
  `update_intelligence_metadata` become hold-coordinated
  `TransactWriteItems` calls (via the already-proven, unmodified
  `HoldCoordinatedTransactionRunner`), each preceded by a write-entry
  governance preflight.
- `IntelligenceRepository`'s constructor gains optional
  `hold_repository: HoldRepository | None = None` and keyword-only
  `custody_period_days: int | None = None` (Decision 11 / Invariant 31) --
  both default to `None` so the existing read-only `retrieve
  intelligence-*` construction path is unaffected.
- `IntelligencePublisher.write_artifact` gains a `ConsistentRead: true`
  hold-state read immediately before `put_object`, computing
  `rcp-legal-hold`/`rcp-evidence-class=intelligence` S3 object tags.
  `IntelligencePublisher`'s constructor gains optional
  `hold_repository: HoldRepository | None = None` only (no duration).
- `operator_cli/main.py`'s `generate intelligence` dispatch block resolves
  `custody_period_days` once via `CustodyPeriodConfigLoader`, before any
  AWS-client construction, then constructs one `HoldRepository` shared by
  both the repository and publisher. The `retrieve intelligence-*` block
  and `--dry-run` mode are unaffected (Invariant 31, Section 20.5).
- `IntelligenceJob` write methods (`put_intelligence_job_once`,
  `update_intelligence_job`) and all read methods are untouched.

## 3. Source Inputs

- `docs/architecture/adr_evidence_retention_disposal_enforcement.md` --
  Decision 5 (as amended), Decision 8, Decision 9, Decision 10, Decision
  11, Non-Negotiable Invariants 8-9, 11-12, 14, 17-18, 26-31.
- `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
  -- Section 20 in full (20.1-20.12), especially 20.4 (three construction
  modes, write-entry governance preflight, preflight precedence),
  20.5 (dry-run exemption), 20.6 (Phase 5 CREATE/regeneration contract),
  20.9 (S3/A1.LH2 boundary), 20.10 (partial-success boundary / issue #118
  exclusion), 20.11 (sanitization boundary), 20.12 (A1.3d.2 inventory).
- `src/release_confidence_platform/aggregation/repository.py` -- the
  already-implemented Phase 4 reference pattern
  (`put_records_once`/`put_lineage_page_once`, `_aggregate_governance_fields`,
  `HoldCoordinatedTransactionRunner` usage). Structurally mirrored, minus
  its `sanitize(item)` call (see the locked correction below).
- `src/release_confidence_platform/evidence_retention/hold_coordination.py`,
  `hold_repository.py`, `constants.py` -- read-only precedent, unmodified.
- `src/release_confidence_platform/config/custody_period_config.py` --
  `CustodyPeriodConfigLoader.resolve(evidence_class, stage) -> int`.
- `src/release_confidence_platform/sanitization/sanitizer.py` -- confirms
  `STRUCTURAL_IDENTIFIER_KEYS` excludes `PK`/`SK`, which is why `sanitize()`
  must never be called on a full DynamoDB item in this subphase.

## 4. API Contracts Affected

No CLI argument, output shape, or exit-code contract changes for `rcp
generate intelligence` or `rcp retrieve intelligence-*`. New,
previously-unreachable failure reason codes become reachable from `rcp
generate intelligence` only: `CUSTODY_PERIOD_CONFIG_MISSING`,
`HOLD_COORDINATION_NOT_CONFIGURED`, `HOLD_STATE_CONCURRENCY_EXCEEDED`. All
three are rendered through the existing, unmodified `render()`/`render_error()`
sanitization boundary (`operator_cli/result.py`) -- no phase-level
sanitization is added or duplicated. `_error_next_step()` has no
phase-specific branch for these codes yet (falls through to the existing
generic guidance) -- this is a documented, temporary operator-usability
limitation per Technical Design Section 20.11, not a safety gap; specific
guidance is deferred to A1.3d.4 per the locked design.

## 5. Data Models / Storage Affected

- `IntelligenceMetadata` (DynamoDB, `#INTEL#...#META` SK): gains
  `custody_expires_at` (always), `ttl_disposal_at` (present unless an
  active hold is observed), and `evidence_class = "intelligence"` on both
  CREATE (`put_intelligence_metadata_once`) and regeneration
  (`update_intelligence_metadata`), computed fresh from an atomically
  verified `LegalHold.hold_version` read on every write attempt.
- `intelligence/` S3 artifacts: gain `rcp-legal-hold` /
  `rcp-evidence-class=intelligence` object tags at write time, computed
  from a `ConsistentRead: true` hold-state read immediately before
  `put_object`.
- `IntelligenceJob` (DynamoDB, `#INTJOB#` SK): **no change** -- remains
  Category 3, never receives any governance field or hold-coordinated
  write path (Invariant 27).

## 6. Files Expected to Change

Production (3, exact scope):
- `src/release_confidence_platform/reliability_intelligence/repository.py`
- `src/release_confidence_platform/reliability_intelligence/publisher.py`
- `src/release_confidence_platform/operator_cli/main.py` (`generate
  intelligence` dispatch block only)

Tests, modified (4):
- `tests/unit/reliability_intelligence/test_engine_no_phase4_mutation.py`
- `tests/unit/reliability_intelligence/test_engine_idempotency.py`
- `tests/unit/reliability_intelligence/test_engine_gate.py`
- `tests/unit/test_reliability_intelligence_retrieval.py`

Tests, new (2):
- `tests/unit/reliability_intelligence/test_hold_coordination.py`
- `tests/unit/test_operator_cli_generate_intelligence.py`

Docs, new (4): this plan, its report, and the two `docs/qa/` documents.

`engine.py` is a behavior-preservation target: not modified, verified via
`git diff main -- .../engine.py` producing zero output.

## 7. Security / Authorization Considerations

- Fail-closed governance preflight (`HOLD_COORDINATION_NOT_CONFIGURED` /
  `CUSTODY_PERIOD_CONFIG_MISSING`) is the first executable action of every
  governed write method, before any hold-state read or AWS mutation.
- No `sanitize()` call is introduced on any item bound for DynamoDB
  persistence -- `STRUCTURAL_IDENTIFIER_KEYS` does not cover `PK`/`SK`, so
  calling `sanitize()` on a full item risks corrupting key values via
  `PHONE_PATTERN`/`EMAIL_PATTERN` substitution. This is the one deliberate
  divergence from Phase 4's textually mirrored pattern.
- `ConsistentRead: true` is used for the S3-write-path hold read only (no
  transactional backstop exists on that leg); the DynamoDB write path's own
  pre-transaction read remains at default consistency (the
  `TransactWriteItems` `ConditionCheck` makes staleness harmless there).
- All new failure codes pass through the existing, unmodified
  `render()`/`render_error()` sanitization boundary -- no raw exception
  detail, AWS request ID, DynamoDB key, S3 key, or `client_id`/`audit_id`
  value is exposed in rendered CLI output.

## 8. Dependencies / Constraints

No new third-party dependency. No Lambda infrastructure, `environment:`
binding, or IAM change (Decision 10 / Invariant 28 -- Phase 5 remains
CLI-only). No custody duration value is introduced anywhere
(`config/custody_periods.json` remains untouched by this subphase).

## 9. Assumptions

- Assumption requiring confirmation (documented, not silently resolved):
  the task brief's instruction to import `CustodyPeriodConfigLoader` and
  `HoldRepository` "at the top of main.py" is interpreted as "at the top of
  the `generate intelligence` dispatch block," consistent with this file's
  established, unbroken convention of lazy, per-command-scoped imports
  (every existing repository/publisher/engine/`AwsClientFactory` import in
  `dispatch()` is a local, `# noqa: PLC0415`-marked import, not a
  module-level import). A module-level import would be the one stylistic
  outlier in the file and would also change import-time behavior for every
  CLI invocation, not only `generate intelligence`. This does not change
  external behavior, API contract, or resolution ordering (Invariant 30 is
  unaffected either way).
- Neither assumption affects external behavior, data shape, security,
  billing, permissions, or API contracts.

## 10. Validation Plan

- `git diff main -- src/release_confidence_platform/reliability_intelligence/engine.py`
  -- must produce zero output.
- `pytest tests/unit/reliability_intelligence/ tests/unit/test_reliability_intelligence_retrieval.py tests/unit/test_operator_cli_generate_intelligence.py -v`
- Full suite: `pytest -q` -- zero regressions permitted anywhere (Phase
  1-4, 6, 7, existing Phase 5 tests).
- `ruff check` / `ruff format --check` on all new/modified Python files.
- `git status --short` / `git diff --stat main` -- confirm the changed-file
  set matches exactly the 13 authorized files.
