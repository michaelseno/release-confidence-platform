# Test Plan

## 1. Feature Overview

Evidence Governance Workstream A1.3d.4 wires Phase 7 (Audit Platform
Integrity / Certificate) `CertificationMetadata` writes, and the Phase 7
certificate S3 artifact write, to legal-hold coordination and
custody-field computation — mirroring the already-merged A1.3d.2 (Phase 5)
and A1.3d.3 (Phase 6) implementations. Unlike Phase 5/6, `write_cert_metadata_complete`
is an **unconditional replacement** contract (no item-level condition,
before or after this change) — forced recertification must always be able
to replace an existing `CertificationMetadata` record. `CertificationJob`
(Category 3, operational coordination metadata) is explicitly excluded and
must never receive custody fields, evidence-class tags, or hold
coordination.

Branch under validation: `feature/a1-3d4-phase7-certificate-hold-coordination`
(base `main@65e3ab1f23a89e2dd7dd3a8abb953fea8dd9e07f`).

This QA pass is independent: it does not trust the implementer's
self-report at face value. Every claim below was re-derived directly from
the actual diff, actual test bodies, actual test execution output, and
actual lint/format output re-run against both the branch and an isolated
`main` worktree checkout for baseline comparison.

## 2. Authoritative Requirements and Acceptance Criteria Mapping

- ADR: `docs/architecture/adr_evidence_retention_disposal_enforcement.md`
  — **Decision 11** (three-mode construction boundary: governance
  dependencies are constructor-optional, write-method-mandatory) and
  **Non-Negotiable Invariant 31** (write-entry governance preflight order:
  hold-repository presence → custody-duration presence → validity, Boolean
  rejected before the `int` check).
- Technical Design:
  `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
  **§20.2** (Category 3 `CertificationJob` exclusion), **§20.4**
  (command-scoped CLI resolution, the three construction modes, the
  locked write-entry governance preflight and precedence rule), **§20.8**
  (Phase 7 unconditional-replacement contract), **§20.8.1** (canonical
  11-segment certificate S3 key parser), **§20.11.1** (shared
  phase-neutral `_error_next_step` guidance), **§20.12** (per-subphase
  implementation inventory — exact file list for A1.3d.4).
- Also generically applicable and re-verified here: Invariants 8, 9, 11,
  12, 14, 17, 18, 27 (Category 3 exclusion), 29 (single custody
  configuration source), 30 (CLI resolution ordering).

This subphase's acceptance criteria were supplied by the orchestrator as
20 explicit, numbered acceptance items, each traced to a specific ADR/TD
citation, source file, or test function name. All 20 are testable
directly against the diff, the test bodies, and live command execution,
and are used as this plan's requirement source (§3 below maps each).

## 3. Test Scenarios (Requirement-to-Test Traceability)

| # | Requirement | Test evidence |
|---|---|---|
| 1 | Exact 14-file final scope (4 production + 5 tests modified + 1 test new + 2 backend docs + 2 QA docs), `AGENTS.md` untouched | `git status --short` before/after QA doc creation |
| 2 | `engine.py`/`identity.py` unchanged, behavior-preservation targets | `git diff main -- .../engine.py`, `git diff main -- .../identity.py` (both empty) |
| 3 | `test_engine_no_phase6_mutation.py` untouched (scope-precision correction) | `git diff main -- tests/.../test_engine_no_phase6_mutation.py` (empty) |
| 4 | No custody value, no infrastructure change | `git diff main -- config/custody_periods.json`, `git diff main -- infra/` (both empty) |
| 5 | `CertificationPublisher.write_artifact` precedence: hold-config check → key parse → `get_legal_hold(consistent_read=True)` → `put_object` w/ `Tagging=` | Direct source read of `publisher.py::write_artifact` |
| 6 | Missing hold coordination wins over malformed-key validation | `test_publisher.py::test_write_artifact_missing_hold_repository_wins_over_malformed_key` |
| 7 | Unconditional `CertificationMetadata` replacement; forced recertification succeeds | Direct source read of `write_cert_metadata_complete` (no `ConditionExpression` on Put construction); `test_hold_coordination.py::test_forced_recertification_replaces_existing_record` |
| 8 | Exactly one unconditional `Put` + one `LegalHold.hold_version` `ConditionCheck` in the transaction | `test_repository.py::test_write_cert_metadata_complete_transaction_shape_and_no_put_condition` |
| 9 | No `ConditionExpression` on the metadata `Put` | Same test as #8 |
| 10 | Fresh clock/hold state/governance fields recomputed on every retry attempt | `test_hold_coordination.py::test_fresh_clock_and_hold_state_recomputed_per_retry_attempt`, `::test_no_stale_governance_value_survives_between_attempts` |
| 11 | Correct held/unheld `ttl_disposal_at` presence/omission | `test_hold_coordination.py::test_ttl_omitted_when_held`, `::test_ttl_present_when_unheld` |
| 12 | Fixed `evidence_class = "certificate"` literal, both repository and publisher | Direct source read of `_cert_governance_fields` and `_cert_tagging` |
| 13 | Complete 11-segment malformed-key matrix, fail-before-AWS on at least 2 cases | `test_publisher.py::test_write_artifact_rejects_malformed_key` (parametrized, 9 cases) |
| 14 | TN-12 BLOCKED-path reachability wired to real-publisher tag equality (not stub-only) | `test_engine.py::test_certify_tn12_blocked_path_reaches_write_artifact_and_write_cert_metadata_complete` + `build_tn12_blocked_write_artifact_call`; `test_hold_coordination.py::test_tn12_blocked_path_tag_construction_matches_certified_path` |
| 15 | Category 3 `CertificationJob` exclusion across all 4 write methods | `test_repository.py` (4 per-method tests + zero-hold-reads test); `test_engine.py::test_certification_job_write_methods_never_carry_governance_fields_full_flow`, `::test_certification_job_write_methods_zero_hold_coordinated_transaction_construction` |
| 16 | Retrieval remains custody-independent, zero writes across all 6 write methods | `test_operator_cli_certify.py::test_retrieve_cert_zero_custody_period_config_loader_calls`, `::test_retrieve_cert_unaffected_by_certificate_configuration` |
| 17 | Shared phase-neutral `_error_next_step` guidance, no phase-name/identifier leak | Direct source read of `result.py`; `test_operator_cli_result.py::test_error_next_step_guidance_leaks_no_identifier_or_key`, `::test_error_next_step_guidance_identical_across_intelligence_report_certificate` |
| 18 | No test codifies issue #118 defects as accepted behavior | `grep` for stale-state/orphan/divergence assertion patterns across all new/modified test files |
| 19 | Zero new Ruff check/format findings relative to recorded baseline | `uv run ruff check`/`ruff format --check` on the 10 touched/created files, independently re-run against an isolated `main` worktree for byte-level baseline comparison |
| 20 | Focused, collection, canonical, hygiene, and scope commands produce exact expected counts | All 12 commands in the task brief, executed directly |

## 4. Edge Cases

- Simultaneous `hold_repository is None` AND malformed key on `write_artifact`
  — hold-configuration check must win (`HOLD_COORDINATION_NOT_CONFIGURED`),
  never `STORAGE_ERROR`.
- Invalid custody-duration values on `write_cert_metadata_complete`: `None`,
  `True` (Boolean), `"10"` (string), `0`, `-5` — all must fail closed with
  `CUSTODY_PERIOD_CONFIG_MISSING`, zero hold reads, zero AWS calls.
- 11-segment certificate key malformation matrix: too few segments, too
  many segments, wrong `parts[0]`, wrong `parts[10]`, empty `client_id`,
  empty `audit_id`, leading slash, trailing slash, doubled slash — all
  must raise `STORAGE_ERROR` before any hold read or S3 call, with a
  message that never echoes the identifiers.
- Forced recertification (`--force`) against an already-CERTIFIED record —
  must succeed unconditionally and replace `terminal_state`/`certificate_id`.
- TN-12 BLOCKED path (Phase 6 S3 artifact read failure) — certificate
  write and artifact write must still occur, tagged identically to a
  CERTIFIED-path write under the same hold state.
- Hold-version race during `write_cert_metadata_complete` — bounded retry,
  each attempt re-reading fresh hold state; retry exhaustion raises
  `HoldStateConcurrencyExceededError`.
- `retrieve cert-*` with `certificate`'s custody period entirely
  unconfigured in `config/custody_periods.json` — must succeed, zero
  `CustodyPeriodConfigLoader` calls, zero governed writes.
- Error-guidance leak probe — a representative fake `client_id`/`audit_id`/S3
  key embedded in a triggering error message must not appear in the
  rendered `next_step` guidance text.

## 5. Test Types Covered

- **Functional / unit**: `test_repository.py`, `test_publisher.py`,
  `test_hold_coordination.py` — unconditional-replacement, transaction
  shape, TTL correctness, key parsing, tagging, preflight behavior.
- **Negative / misuse**: malformed-key matrix, invalid-duration
  parametrization, missing-hold-repository precedence tests.
- **Concurrency / race**: fresh-clock-per-retry, bounded retry exhaustion,
  governed-condition-precedence-not-applicable (no Put condition to race).
- **Integration**: `test_engine.py` (full `certify()` pipeline incl. TN-12
  BLOCKED path, Category 3 exclusion at the integration level),
  `test_operator_cli_certify.py` (full CLI composition for `certify audit`
  and all `retrieve cert-*` variants).
- **Regression**: unchanged `engine.py`/`identity.py`/`test_engine_no_phase6_mutation.py`
  confirmed via empty diff; `test_operator_cli_result.py` (existing
  error-rendering contract extended, not replaced).
- **Static analysis**: `ruff check`/`ruff format --check` on the touched
  set (independently re-derived against an isolated `main` baseline
  checkout), `git diff --check` for whitespace/EOL hygiene.

## 6. Focused and Canonical Test Commands

Focused (fast iteration, this subphase's own surface):
```
uv run pytest -q tests/unit/audit_platform_integrity/
uv run pytest -q tests/unit/test_operator_cli_certify.py
uv run pytest -q tests/unit/test_operator_cli_result.py
```

Canonical (full-suite regression gate):
```
uv run pytest --collect-only -q
uv run pytest -q
```

Lint / format / diff hygiene, against the exact 10 touched/created files:
```
uv run ruff check \
  src/release_confidence_platform/audit_platform_integrity/repository.py \
  src/release_confidence_platform/audit_platform_integrity/publisher.py \
  src/release_confidence_platform/operator_cli/main.py \
  src/release_confidence_platform/operator_cli/result.py \
  tests/unit/audit_platform_integrity/test_repository.py \
  tests/unit/audit_platform_integrity/test_engine.py \
  tests/unit/audit_platform_integrity/test_publisher.py \
  tests/unit/test_operator_cli_certify.py \
  tests/unit/test_operator_cli_result.py \
  tests/unit/audit_platform_integrity/test_hold_coordination.py

uv run ruff format --check <same 10 files>

git diff --check main
```

Scope-containment commands:
```
git status --short
git diff --stat main
git diff main -- src/release_confidence_platform/audit_platform_integrity/engine.py
git diff main -- src/release_confidence_platform/audit_platform_integrity/identity.py
git diff main -- tests/unit/audit_platform_integrity/test_engine_no_phase6_mutation.py
git diff main -- config/custody_periods.json
git diff main -- infra/
```

## 7. Scope-Containment Checks

- Working tree must show exactly 14 in-scope paths relative to `main` once
  QA records are added: 4 production modified, 5 tests modified, 1 test
  new, 2 backend docs new, 2 QA docs new (these two files). `AGENTS.md`
  must remain untracked and untouched throughout.
- `engine.py`, `identity.py`, `test_engine_no_phase6_mutation.py`: zero
  diff against `main`.
- `config/custody_periods.json`: zero diff against `main` (no duration
  value introduced; `certificate` class stays `{}`).
- `infra/`: zero diff against `main` (no infrastructure change; Decision
  10/Invariant 28 — no Lambda entry points for Phase 5–7).

## 8. Baseline Reconciliation Method

Because the implementation report itself documented a prior, corrected
miscount on the Ruff baseline (an initial pass compared finding *counts*
per file rather than each finding's underlying cause, masking a
substitution in `test_operator_cli_certify.py`), this QA pass does not
accept the report's baseline claim at face value. It independently
re-derives the baseline by checking out `main` into an isolated
`git worktree`, running the identical `ruff check`/`ruff format --check`
commands there, and comparing findings by rule code, file, and message
content (not merely by count) against the branch's current findings.

## 9. Acceptance and Rejection Criteria

**Blocking (would withhold sign-off):**
- Any full-suite test failure, or any collected/passed/skipped count
  deviating from the expected 2115/2113/2 without an explicit, reconciled
  explanation.
- Any `ruff check` finding on the touched-file set not traceable, by rule
  code and content (not merely by count), to the independently re-derived
  `main` baseline.
- Any previously-clean file (`publisher.py`, `result.py`,
  `test_operator_cli_result.py`, or the new `test_hold_coordination.py`)
  becoming `ruff format` dirty.
- Any non-empty diff under `engine.py`, `identity.py`,
  `test_engine_no_phase6_mutation.py`, `config/custody_periods.json`, or
  `infra/`.
- Any deviation from the locked unconditional-`Put` contract, the
  publisher precedence order (§20.8.1), the `evidence_class="certificate"`
  fixed literal, or the Category 3 `CertificationJob` exclusion.
- A stub-only proof for the TN-12 BLOCKED-path tag-equivalence claim
  (item 14) instead of a real, non-stubbed `write_artifact` call.
- A working-tree file count other than exactly 14 in-scope paths relative
  to `main`, or any modification to `AGENTS.md`.
- Any test asserting an issue #118 partial-success/stale-state defect as
  expected/passing behavior.
- `git diff --check` reporting a whitespace/EOL error.

**Non-blocking (documented as observation, does not withhold sign-off):**
- A documentation citation (e.g. an ADR/TD line-number reference) drifting
  from the actual current line number due to unrelated intervening edits,
  provided the underlying mechanism it describes is independently
  verified correct.
- Any `ruff check`/`format --check` finding that traces, by rule code and
  content, to the independently re-derived `main` baseline.
