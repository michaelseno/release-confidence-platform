# Implementation Plan

## 1. Feature Overview

Wire Phase 7 (Audit Platform Integrity / Certificate) `CertificationMetadata`
writes, and the Phase 7 certificate S3 artifact write, to Evidence
Governance Workstream A1's legal-hold coordination and custody-field
computation, mirroring the already-merged A1.3d.2 (Phase 5) and A1.3d.3
(Phase 6) implementations. Unlike Phase 5/6, `write_cert_metadata_complete`
is an **unconditional replacement** contract (no item-level condition,
before or after this change) — forced recertification must always be able
to replace an existing `CertificationMetadata` record. `CertificationJob`
(Category 3, operational coordination metadata) is explicitly excluded and
must never receive custody fields, evidence-class tags, or hold
coordination.

## 2. Technical Scope

- `CertificationRepository.write_cert_metadata_complete`: rewritten from a
  plain unconditional `put_item` into a hold-coordinated
  `TransactWriteItems` call — the `Put` itself keeps carrying no
  `ConditionExpression` of any kind (preserving unconditional replacement),
  with an appended `LegalHold.hold_version` `ConditionCheck` as the
  transaction's only condition.
- `CertificationPublisher.write_artifact`: gains a hold-state read and
  write-time `rcp-legal-hold`/`rcp-evidence-class=certificate` S3 object
  tagging, plus a new canonical 11-segment key parser
  (`_parse_cert_key_identity`) that replaces the prior
  `assert key.startswith("integrity/")` guard as the authoritative
  structural validation. `read_artifact`'s existing prefix-only guard is
  unaffected.
- `operator_cli/main.py`'s `certify audit` construction block: resolves
  `certificate`'s custody-period duration once, before `AwsClientFactory`
  construction, constructs a shared `HoldRepository`, and injects both
  governance dependencies into `CertificationRepository`/
  `CertificationPublisher`. `retrieve cert-*` is unaffected.
- `operator_cli/result.py`'s `_error_next_step`: three new, shared,
  phase-neutral guidance branches for `CUSTODY_PERIOD_CONFIG_MISSING`,
  `HOLD_COORDINATION_NOT_CONFIGURED`, `HOLD_STATE_CONCURRENCY_EXCEEDED` —
  reused identically by `generate intelligence`/`generate report`/
  `certify audit`.
- `CertificationEngine` (`engine.py`) and `identity.py`
  (`build_cert_s3_key`) are unchanged, behavior-preservation targets —
  `certify()`'s existing call signatures to `write_cert_metadata_complete`/
  `write_artifact` do not change.

## 3. Source Inputs

- `docs/architecture/adr_evidence_retention_disposal_enforcement.md`
  (Decision 11, Non-Negotiable Invariant 31).
- `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
  §20.2, §20.4, §20.8, §20.8.1, §20.11.1, §20.12 (Phase 7 unconditional
  replacement contract, canonical certificate key parser, shared
  `_error_next_step` guidance, per-subphase file inventory).
- Already-merged Phase 6 implementation
  (`deterministic_reporting/repository.py`, `publisher.py`) as the exact
  structural template for the hold-coordinated transaction shape and the
  key-parser/tagging pattern, per the orchestrator's task brief.
- Already-merged `evidence_retention/hold_coordination.py` (unmodified
  reused mechanism), `evidence_retention/hold_repository.py`,
  `evidence_retention/constants.py`, and
  `config/custody_period_config.py` (unmodified).

## 4. API Contracts Affected

No externally-facing HTTP/REST API. CLI contract changes:

- `rcp certify audit`: now resolves `certificate`'s custody-period duration
  before `AwsClientFactory` construction and fails closed
  (`CUSTODY_PERIOD_CONFIG_MISSING`) if missing/invalid; constructs a
  `HoldRepository` shared between `CertificationRepository` and
  `CertificationPublisher`. Existing success-path output shape
  (`CommandResult` fields, `dispatch_certify_audit`'s return dict) is
  unchanged.
- `rcp retrieve cert-*` (all four variants): unchanged — no custody
  resolution, no `HoldRepository` construction, dependency-free
  `CertificationRepository`/`CertificationPublisher` construction (both
  governance params remain at their `None` default), identical to current
  behavior.
- New reason codes reachable on the `certify audit` path:
  `CUSTODY_PERIOD_CONFIG_MISSING`, `HOLD_COORDINATION_NOT_CONFIGURED`,
  `HOLD_STATE_CONCURRENCY_EXCEEDED` — all already-locked, reused codes from
  A1.LH1/A1.3c.1/A1.3d.2/A1.3d.3, no new reason code introduced.
- `operator_cli/result.py`'s `_error_next_step` gains specific,
  phase-neutral guidance for the three codes above, replacing the generic
  fallback previously returned for `generate intelligence`/
  `generate report` as well (shared branch, not certify-specific).

## 5. Data Models / Storage Affected

- `CertificationMetadata` (DynamoDB): gains `custody_expires_at` (always),
  `evidence_class="certificate"` (always), `ttl_disposal_at` (present only
  when no active hold is observed at write time) — computed fresh on
  every `write_cert_metadata_complete` call, including forced
  recertification and the TN-12 BLOCKED path.
- `CertificationJob` (DynamoDB): no schema change — remains Category 3,
  excluded from all four of its write methods.
- Phase 7 certificate S3 artifact (`integrity/` prefix): gains
  `rcp-legal-hold`/`rcp-evidence-class=certificate` object tags at write
  time, applied identically regardless of terminal state (CERTIFIED,
  CERTIFICATION_FAILED, or the TN-12 BLOCKED path).
- No migration or backfill — this only affects newly-written records;
  existing records are unaffected until their own next write.

## 6. Files Expected to Change

Production (4):
- `src/release_confidence_platform/audit_platform_integrity/repository.py`
- `src/release_confidence_platform/audit_platform_integrity/publisher.py`
- `src/release_confidence_platform/operator_cli/main.py`
- `src/release_confidence_platform/operator_cli/result.py`

Tests, modified (5):
- `tests/unit/audit_platform_integrity/test_repository.py`
- `tests/unit/audit_platform_integrity/test_engine.py`
- `tests/unit/audit_platform_integrity/test_publisher.py`
- `tests/unit/test_operator_cli_certify.py`
- `tests/unit/test_operator_cli_result.py`

Tests, new (1):
- `tests/unit/audit_platform_integrity/test_hold_coordination.py`

Unchanged, behavior-preservation targets (verified through tests, not
modified):
- `src/release_confidence_platform/audit_platform_integrity/engine.py`
- `src/release_confidence_platform/audit_platform_integrity/identity.py`
- `tests/unit/audit_platform_integrity/test_engine_no_phase6_mutation.py`

## 7. Security / Authorization Considerations

- Fail-closed governance preflight (hold-repository presence, then
  custody-duration presence/validity, Boolean rejected before the `int`
  check) on `write_cert_metadata_complete`/`write_artifact`, before any
  hold-state read or AWS mutation — mirrors the locked Invariant 31
  pattern exactly.
- Unlike Phase 5/6's CREATE contract, there is no governed-condition to
  prioritize over a hold-version race here — the `Put` carries no
  condition of its own, so any transaction cancellation is necessarily
  hold-version-caused (or a transient, condition-unrelated cancellation)
  and is always retried, bounded by `MAX_HOLD_COORDINATION_RETRY_ATTEMPTS`.
- `write_artifact`'s hold-configuration check runs before key parsing
  (locked precedence) — a missing `HoldRepository` is reported even for a
  simultaneously malformed key, never conflated with a `STORAGE_ERROR`.
- The persistence-bound `CertificationMetadata` item is built via literal
  dict construction — `sanitize()` is never called on it, avoiding the
  same PK/SK-corruption risk already locked for Phase 5/6.
- No new AWS IAM permissions required (reuses the existing
  `TransactWriteItems`/`GetItem`/`PutObject` permission surface already
  granted to Phase 5/6).
- No secrets, tokens, or credentials touched.

## 8. Dependencies / Constraints

- No new third-party dependency.
- Reuses `evidence_retention/hold_coordination.py`
  (`HoldCoordinatedTransactionRunner`, `build_hold_version_condition_check_item`,
  `compute_ttl_disposal_at`) unmodified.
- Reuses `config/custody_period_config.py`'s `CustodyPeriodConfigLoader`
  unmodified — `certificate`'s custody-period duration value in
  `config/custody_periods.json` remains an empty object; no duration value
  is introduced by this change (out of scope, per ADR Decision 5).
- CLI-only invocation boundary preserved (ADR Decision 10) — no Lambda
  infrastructure change.

## 9. Assumptions

None requiring escalation. The technical design's Phase 7 contract
(§20.8/§20.8.1) is fully specified, including the exact unconditional-Put
shape, the 11-segment key parser's exact validation order, and the shared
`_error_next_step` guidance text's required framing (policy-configuration
gap / runtime wiring defect / genuine retry exhaustion), leaving no
ambiguous product-behavior decision to the implementer.

One implementation-detail choice, documented here rather than escalated
because it does not change external behavior: several pre-existing test
functions in `test_repository.py` and `test_publisher.py` that previously
constructed a `CertificationRepository`/`CertificationPublisher` with no
governance dependencies and asserted on the (now-removed) unconditional
`_put_item`/prefix-only-`assert` code paths were adapted — same test name,
same asserted intent, updated construction/assertions — to remain
meaningful against the new hold-coordinated/parser-based contract. This
mirrors the identical, precedented adaptation already made to Phase 6's
`test_repository.py`/`test_publisher.py` during A1.3d.3 (confirmed by
direct comparison against that commit's diff) rather than an unrequested
deviation.

## 10. Validation Plan

- `uv run pytest -q tests/unit/audit_platform_integrity/` — all Phase 7
  tests pass, including the new hold-coordination file.
- `uv run pytest -q tests/unit/test_operator_cli_certify.py` and
  `tests/unit/test_operator_cli_result.py` — composition and guidance
  coverage pass.
- `uv run pytest --collect-only -q` and `uv run pytest -q` — full suite
  must pass with no regressions (2047 passed/2 skipped baseline → 2113
  passed/2 skipped expected, +66 new tests).
- `uv run ruff check <10 touched/created files>` — no new findings beyond
  the documented pre-implementation baseline (13 pre-existing errors: 7 in
  `main.py`, 1 in `test_repository.py`, 2 in `test_publisher.py`, 2 in
  `test_operator_cli_certify.py`, 1 in `test_engine.py`, 0 elsewhere).
- `uv run ruff format --check <10 touched/created files>` — files clean
  before this change (`publisher.py`, `result.py`, `test_hold_coordination.py`
  (new), `test_operator_cli_result.py`) must remain clean; files already
  needing reformatting before this change may remain so (no unrelated
  reformatting).
- `git diff main -- engine.py identity.py test_engine_no_phase6_mutation.py
  config/custody_periods.json infra/` — all must be empty.
- `git status --short` — must show exactly the 10 code files in scope as
  modified/new, plus `AGENTS.md` untracked (pre-existing, untouched).
