# Test Plan

## 1. Feature Overview

Evidence Governance Workstream A1.3d.3 wires Phase 6 (Deterministic
Reporting) `ReportMetadata` CREATE and regeneration writes, and the Phase 6
report S3 artifact write, to legal-hold coordination and custody-field
computation — mirroring the already-merged A1.3d.2 Phase 5 (Reliability
Intelligence) implementation. `ReportJob` (Category 3, operational
coordination metadata) is explicitly excluded and must never receive
custody fields, evidence-class tags, or hold coordination.

Branch under validation: `feature/a1-3d3-phase6-report-hold-coordination`
(from `main@b1bfac3dbc04838e5f9ccc46564d12f7278bea02`).

This QA pass is independent: it does not trust the implementer's
self-report, it re-derives every claim from the actual diff, actual test
output, and actual lint/format output.

## 2. Authoritative Requirements and Acceptance Criteria Mapping

- ADR: `docs/architecture/adr_evidence_retention_disposal_enforcement.md`
  — **Decision 11** (three-mode construction boundary: governance
  dependencies are constructor-optional, write-method-mandatory) and
  **Non-Negotiable Invariant 31** (write-entry governance preflight order:
  hold-repository presence → custody-duration presence → validity, Boolean
  rejected before the `int` check; forbidden-field validation, where it
  exists, may precede the preflight but never an AWS call).
- Technical Design:
  `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
  **§20.4** (command-scoped CLI resolution, the three construction modes,
  the locked write-entry governance preflight and its precedence rule) and
  **§20.7.1–§20.7.11** (Phase 6 CREATE contract, regeneration contract,
  ordinary-transition contract, call-site classification, CREATE
  acceptance-coverage requirement, canonical 9-segment S3 key contract,
  Phase 7 consumer-contract preservation, seven retrieval variants, error
  matrix, file inventory, issuance-governance scope boundary).
- Also generically applicable and re-verified here: Invariants 8, 9, 11,
  12, 14, 17, 18, 27 (Category 3 exclusion), 29 (single custody
  configuration source), 30 (CLI resolution ordering).

Acceptance criteria for this subphase are structural, not a single
FR/AC list — they are the explicit "must implement it so that, in this
order..." contracts in TD §20.7.1–§20.7.3 plus the exact 13-file
implementation inventory in TD §20.7.10/§20.12. Both are testable directly
against the diff and are used as this plan's requirement source.

## 3. Test Scenarios (Requirement-to-Test Traceability)

| Requirement (ADR/TD citation) | Test evidence |
|---|---|
| `ReportRepository`/`ReportPublisher` constructors accept optional `hold_repository`/`custody_period_days`, default `None` (Decision 11/Invariant 31, TD §20.4) | Direct diff read of `repository.py`/`publisher.py` `__init__`; `test_publisher.py::test_constructor_defaults_hold_repository_to_none`, `::test_constructor_accepts_positional_hold_repository` |
| Write-entry governance preflight order: hold-repository presence → duration presence → Boolean-before-int validity (Invariant 31) | Direct diff read of `_governance_preflight`; `test_repository.py::test_put_report_metadata_once_fails_closed_when_hold_repository_missing`, `::test_put_report_metadata_once_fails_closed_on_invalid_duration` parametrized over `[None, True, False, "30", 30.0, 0, -1]` |
| `put_report_metadata_once` CREATE contract, items 1–9 (TD §20.7.1) — preflight first, SK guard preserved, structural identity parsing, `sanitize()` never called on full item, governance fields merged last, hold `ConditionCheck` appended, governed-condition-wins precedence | Direct diff read of `put_report_metadata_once`; `grep sanitize(` confirms zero calls; `test_repository.py::test_put_report_metadata_once_*` (9 tests) and `test_hold_coordination.py::test_create_*` (CREATE-focused subset) |
| Governed-condition-wins precedence specifically (TD §20.7.1 item 8/9) | `test_hold_coordination.py::test_create_duplicate_key_governed_failure_wins_over_hold_check_failure` — forces both the governed `Put` condition and the hold `ConditionCheck` to fail in the same attempt, asserts `ConditionalWriteError` with exactly one transact call (zero retries) |
| `regenerate_report_metadata` regeneration contract (TD §20.7.2) — forbidden-field check is literal first line, before preflight; `SET`/explicit `REMOVE ttl_disposal_at` per held/unheld branch | Direct diff read; `test_hold_coordination.py::test_regenerate_unheld_sets_fresh_ttl_disposal_at`, `::test_regenerate_active_hold_removes_ttl_disposal_at`, `::test_regenerate_released_hold_restores_ttl_disposal_at`, `::test_regenerate_rejects_forbidden_governance_fields_before_any_aws_call`, `::test_regenerate_preserves_other_updates_fields`, `::test_regenerate_report_metadata_does_not_mutate_caller_updates_dict` |
| `update_report_metadata_fields` forbidden-field guard is literal first line, before `_assert_phase6_sk`, `AssertionError` with fixed message, method otherwise unchanged (TD §20.7.3) | Direct diff read; 9 named tests in `test_repository.py` (rejects each field individually, all-three-together, mixed-with-ordinary, exact exception type/message, zero DynamoDB activity via mock call-count assertion, caller-dict preservation, permitted-fields-unaffected regression) |
| `engine.py` — exactly one call-site relocation, line 289's regen branch (`update_report_metadata_fields` → `regenerate_report_metadata`), nothing else differs from `main` (TD §20.7.4) | Direct diff read (single hunk) |
| PLACE/RELEASE race detection and bounded retry exhaustion (Invariant 11/12, TD §20.7.5) | `test_hold_coordination.py::test_put_report_metadata_once_place_race_bounded_success`, `::test_put_report_metadata_once_release_race_bounded_success`, `::test_put_report_metadata_once_hold_race_retry_exhaustion_fails_closed`, `::test_regenerate_report_metadata_hold_race_retry_exhaustion_fails_closed` |
| Fresh clock/fields per retry attempt, never cached (TD §20.7.5) | `test_hold_coordination.py::test_custody_expires_at_fresh_per_retry_attempt`, `::test_custody_expires_at_uses_deterministic_clock` |
| Caller-item/updates-dict immutability (TD §20.7.5) | `test_hold_coordination.py::test_put_report_metadata_once_does_not_mutate_caller_item_on_success`, `::test_regenerate_report_metadata_does_not_mutate_caller_updates_dict`; `test_repository.py::test_put_report_metadata_once_caller_item_immutability` |
| Sanitizer-sensitive identifier preservation — `sanitize()` never reaches the full persistence-bound item (TD §20.7.5, ADR Sanitization Boundary ADR) | `test_hold_coordination.py::test_sanitize_never_reaches_persistence_path_for_phone_pattern_digit_sequences`; `test_repository.py::test_put_report_metadata_once_sanitizer_sensitive_identifier_preserved` |
| Canonical 9-segment S3 key parser, not a copy of Phase 5's 8-segment parser, fixed non-key-echoing error message (TD §20.7.6) | Direct diff read of `_parse_report_key_identity`; `test_publisher.py::test_parse_report_key_identity_valid`, `::test_parse_report_key_identity_malformed` (parametrized), `::test_parse_report_key_identity_error_message_never_echoes_key` |
| `ReportPublisher.write_artifact` hold-state read (`ConsistentRead: true`) before `put_object`, fixed `rcp-evidence-class=report` + computed `rcp-legal-hold` tag, hold-error identity preserved, S3 failure mapped to `S3_WRITE_FAILED` (TD §20.7.6) | `test_publisher.py::test_write_artifact_fails_closed_when_hold_repository_not_configured`, `::test_write_artifact_reads_hold_state_with_consistent_read_true`, `::test_write_artifact_reads_hold_before_put_object`, `::test_report_tagging_exact_string_per_state` (parametrized), `::test_write_artifact_passes_correct_tagging_string`, `::test_write_artifact_storage_error_from_hold_read_propagates_unchanged`, `::test_write_artifact_unexpected_exception_from_hold_read_maps_to_storage_error`, `::test_write_artifact_s3_failure_after_successful_hold_read` |
| CLI composition — custody resolution exactly once, before `AwsClientFactory`, injected integer, shared `HoldRepository` identity, publisher receives no duration, zero AWS construction on resolution failure (TD §20.4, ADR Invariant 30) | Direct diff read of `main.py`; `test_operator_cli_generate_report.py::test_generate_report_resolves_custody_period_exactly_once`, `::test_generate_report_resolves_before_aws_client_factory_construction`, `::test_generate_report_injects_resolved_custody_period_into_repository`, `::test_generate_report_injects_same_hold_repository_instance_into_both`, `::test_generate_report_publisher_receives_no_duration_argument`, `::test_generate_report_custody_resolution_failure_zero_aws_construction` |
| All seven `retrieve report-*` variants remain dependency-free, `CustodyPeriodConfigLoader.resolve` never called, no `HoldRepository` constructed, output content-compatible (TD §20.7.8) | `test_operator_cli_generate_report.py` — `_ALL_RETRIEVE_COMMANDS` = `report-status, report-summary, report-endpoints, report-methodology, report-lineage, report-json, report-markdown`; 5 tests parametrized across all 7 |
| `report-status` specifically: zero S3 API calls; `--output json` prints `result.data["rendered"]` unchanged, no distinct JSON shape (TD §20.7.8) | `test_operator_cli_generate_report.py::test_retrieve_report_status_makes_zero_s3_api_calls` (asserts empty S3-call list on the tracking client), `::test_retrieve_report_status_prints_rendered_unchanged_with_output_json` (asserts pre-rendered text present AND `json.loads(out)` raises `JSONDecodeError`) |
| Category 3 `ReportJob` exclusion — negative regression required by ADR Invariant 27 | Unit-level: `test_repository.py::test_put_report_job_once_never_carries_governance_elements`, `::test_update_report_job_never_carries_governance_elements`. Integration-level: `test_engine.py::test_report_job_never_carries_governance_elements_first_generation`, `::test_report_job_never_carries_governance_elements_force_regeneration` |
| `test_engine_no_phase5_mutation.py` not broadened with new assertions — scope stays narrow | Direct diff read (minimal: adds only a `regenerate_report_metadata` double method to the existing tracking repository) |
| Phase 7 consumer-contract preservation (TD §20.7.7) | `git diff main -- tests/unit/audit_platform_integrity/ src/.../audit_platform_integrity/` (must be empty); the 4 Phase 7 test files run unmodified as part of the full suite |
| Error rendering — new reason codes preserve reason code, no leakage (TD §20.7.9) | `test_operator_cli_result.py::test_phase6_error_rendering_preserves_code_and_leaks_nothing`, parametrized over `_PHASE6_ERROR_CASES` × `["text", "json"]` |
| No separate hold-coordination test-double file (locked A1.3d.2 correction) | `find` for `*hold_coordination_double*` under `tests/unit/deterministic_reporting/` — none found; double is embedded in `test_hold_coordination.py` |

## 4. Edge Cases

- Invalid custody-duration values: `None`, `True`, `False`, `"30"` (string),
  `30.0` (float), `0`, `-1` — all must fail closed with
  `CUSTODY_PERIOD_CONFIG_MISSING`, Boolean rejected before the `int` check.
- Malformed `ReportMetadata` PK/SK (identity parse failure) — must raise
  `StorageError("STORAGE_ERROR")` before any hold-state read (zero calls to
  `HoldRepository.get_legal_hold`).
- Malformed / wrong-segment-count S3 report key — must raise `StorageError`
  before any hold-state read or S3 call, with a fixed message that never
  echoes the key.
- Simultaneous governed-condition failure and hold-version race in the same
  transaction attempt — governed condition must win, zero retries.
- Hold placed/released between read and commit (PLACE/RELEASE race) —
  detected by the hold `ConditionCheck`, triggers bounded retry with a
  fresh read.
- Bounded retry exhaustion — must raise `HoldStateConcurrencyExceededError`
  with zero fallback to an unconditioned write.
- Caller-supplied governance-field injection into `regenerate_report_metadata`'s
  `updates` dict — must be rejected with `AssertionError`, zero AWS calls,
  caller dict left unmutated.
- Caller-supplied governance-field injection into `put_report_metadata_once`'s
  `item` — silently overridden by repository-computed value (not rejected;
  this is the documented, distinct CREATE contract vs. regeneration's
  reject-based contract).
- `report-status --output json` — must not acquire a distinct JSON
  envelope; must remain the pre-rendered text bypass.
- Sanitizer false-positive-triggering identifier (phone-pattern digit
  sequence) in `client_id`/`audit_id` — must survive a CREATE write
  unmodified, proving `sanitize()` is never invoked on the full item.

## 5. Test Types Covered

- **Functional / unit**: `test_repository.py`, `test_publisher.py`,
  `test_hold_coordination.py` — CREATE, regeneration, ordinary-transition,
  tagging, key parsing, preflight behavior.
- **Negative / misuse**: forbidden-field rejection tests (both
  `update_report_metadata_fields` and `regenerate_report_metadata`),
  invalid-duration parametrization, malformed-identity/malformed-key
  rejection.
- **Concurrency / race**: PLACE race, RELEASE race, retry exhaustion,
  simultaneous-failure precedence — all in `test_hold_coordination.py`.
- **Integration**: `test_engine.py` (full `generate()` pipeline, Category 3
  exclusion at the integration level), `test_operator_cli_generate_report.py`
  (full CLI composition for both `generate report` and all 7
  `retrieve report-*` variants).
- **Regression**: `test_engine_no_phase5_mutation.py` (Phase 5 SK
  non-mutation invariant unaffected), the 4 unmodified Phase 7 test files,
  `test_operator_cli_result.py` (existing error-rendering contract
  extended, not replaced).
- **Static analysis**: `ruff check` / `ruff format --check` on the touched
  set, `git diff --check` for whitespace/EOL hygiene.

## 6. Focused and Canonical Test Commands

Focused (fast iteration, this subphase's own surface):
```
uv run pytest -q tests/unit/deterministic_reporting/
uv run pytest -q tests/unit/test_operator_cli_generate_report.py
uv run pytest -q tests/unit/test_operator_cli_result.py
uv run pytest -q tests/unit/audit_platform_integrity/
```

Canonical (full-suite regression gate):
```
uv run pytest -q
```

Lint / format / diff hygiene, run against the exact touched-file list (4
production + 7 test files):
```
uv run ruff check \
  src/release_confidence_platform/deterministic_reporting/repository.py \
  src/release_confidence_platform/deterministic_reporting/publisher.py \
  src/release_confidence_platform/deterministic_reporting/engine.py \
  src/release_confidence_platform/operator_cli/main.py \
  tests/unit/deterministic_reporting/test_repository.py \
  tests/unit/deterministic_reporting/test_engine.py \
  tests/unit/deterministic_reporting/test_engine_no_phase5_mutation.py \
  tests/unit/deterministic_reporting/test_publisher.py \
  tests/unit/test_operator_cli_result.py \
  tests/unit/deterministic_reporting/test_hold_coordination.py \
  tests/unit/test_operator_cli_generate_report.py

uv run ruff format --check <same 11 files>

git diff --check main
```

Scope-containment commands:
```
git status --short
git diff --stat main
git diff main -- tests/unit/audit_platform_integrity/ src/release_confidence_platform/audit_platform_integrity/
git diff main -- config/custody_periods.json
git diff main -- src/release_confidence_platform/deterministic_reporting/identity.py
git diff main -- infra/
```

## 7. Scope-Containment Checks

- Working tree must show exactly 15 files relative to `main` once QA
  records are added: 4 production modified, 5 tests modified, 2 tests new,
  2 backend docs new, 2 QA docs new (these two files). `AGENTS.md` must
  remain untracked and untouched throughout.
- `tests/unit/audit_platform_integrity/` and
  `src/release_confidence_platform/audit_platform_integrity/`: zero diff
  against `main` (Phase 7 untouched).
- `config/custody_periods.json`: zero diff against `main` (no duration
  value introduced; `report` class stays `{}`).
- `src/release_confidence_platform/deterministic_reporting/identity.py`:
  zero diff against `main` (canonical key builder untouched — only the
  *parser*, in `publisher.py`, is new).
- `infra/`: zero diff against `main` (no infrastructure change; Decision
  10/Invariant 28 — no Lambda entry points, no Serverless function
  definitions for Phase 5–7).

## 8. Phase 7 Compatibility Checks

- `git diff main -- tests/unit/audit_platform_integrity/
  src/release_confidence_platform/audit_platform_integrity/` must be
  empty.
- `tests/unit/audit_platform_integrity/test_engine.py`,
  `test_repository.py`, `test_domains.py`, and
  `test_engine_no_phase6_mutation.py` must all pass unmodified as part of
  the canonical full-suite run — these are Phase 7's read-side consumer of
  `ReportMetadata`/the S3 report artifact (`report_id`, `report_version`,
  `intelligence_version`, `aggregate_set_hash`, `endpoint_count`,
  `s3_artifact_ref` — none of which this subphase's writes are permitted
  to rename or restructure, per TD §20.7.7).

## 9. Acceptance and Rejection Criteria

**Blocking (would withhold sign-off):**
- Any full-suite test failure, or any skip count change other than the
  known, pre-existing 2 skips.
- Any `ruff check` error on the touched-file set beyond the exact
  pre-implementation baseline distribution (7 in `main.py`, 4 in
  `test_engine.py`, 2 in `test_engine_no_phase5_mutation.py`, 0
  elsewhere).
- Any previously-clean file (`publisher.py`, `test_publisher.py`,
  `test_operator_cli_result.py`, or either new test file) becoming
  `ruff format` dirty.
- Any non-empty diff under `audit_platform_integrity/`,
  `config/custody_periods.json`, `identity.py`, or `infra/`.
- Any deviation from the locked preflight order (Invariant 31), the
  governed-condition-wins precedence (TD §20.7.1 item 8), the explicit
  `REMOVE ttl_disposal_at` requirement (TD §20.7.2), or the
  forbidden-field-guard-as-first-executable-action requirement (TD
  §20.7.3).
- Any caller-supplied governance-field value silently accepted by
  `regenerate_report_metadata` (must reject) or evidence of `sanitize()`
  being called on a full persistence-bound `ReportMetadata` item.
- A working-tree file count other than exactly 15 relative to `main`, or
  any modification to `AGENTS.md`.
- `git diff --check` reporting a whitespace/EOL error.

**Non-blocking (documented as observation, does not withhold sign-off):**
- Cosmetic docstring expansion on an otherwise-unchanged method body
  (e.g. `update_report_metadata_fields`'s docstring gaining a sentence
  documenting the new `AssertionError` case).
- Pre-existing, already-documented limitations carried forward unchanged
  from Phase 5 precedent (e.g. TD §20.11's generic operator-guidance
  fallback for newly-reachable custody/hold reason codes, pending
  A1.3d.4).
- Any `ruff check`/`format --check` finding that exactly matches the
  recorded pre-implementation baseline (these are pre-existing, not
  introduced by this change, and out of this subphase's scope to fix).
