# Implementation Plan

## 1. Feature Overview

A1.4b implements the Operator CLI and `RetentionService` contract correction
that companion ADR Decision 12 / Non-Negotiable Invariants 32-37 and
Technical Design §21 (the A1.4b.0 Amendment) authorize: adds the first
`rcp retention hold place|release|status` CLI commands (none existed
before this subphase — confirmed by direct inspection, no `commands.py`
existed under `evidence_retention/` and `operator_cli/main.py` never
imported `RetentionService`), and corrects a genuine pre-existing defect in
`RetentionService.place_legal_hold`/`release_legal_hold`, which return the
pre-sweep `HoldTransitionOutcome` snapshot instead of the audit identity's
authoritative, currently-persisted hold state.

## 2. Technical Scope

- `HoldTransitionOutcome` (`hold_transitions.py`) gains `is_resumption: bool`,
  set at all five existing branch points in `HoldTransitions.place`/`release`.
- New `HoldOperationResult` dataclass in `retention_service.py` — the exact
  §21.4 field contract, shared by PLACE/RELEASE/STATUS.
- New `RetentionService.get_hold_status` (strongly consistent read, zero
  mutation) and shared `_build_result` helper.
- `place_legal_hold`/`release_legal_hold` return type changes from
  `HoldTransitionOutcome` to `HoldOperationResult`, sourced from a
  post-sweep, strongly consistent re-read — not the pre-sweep outcome.
- Stale `HoldStateConcurrencyExceededError` docstring claims corrected on
  both methods (§21.7.1) — no behavior change.
- New `evidence_retention/commands.py`: parser/dispatch for the three
  commands, constructing only `RetentionService` calls, never touching
  `HoldRepository` directly.
- `operator_cli/main.py` wiring: new `retention` argparse group, dispatch
  branch constructing `HoldRepository`/`CustodySweepClient`/`MarkerStore`/
  `HoldTransitions`/`RetentionService` once per invocation, `_command_name`
  update.
- `operator_cli/result.py`: text-rendering rules for the nine
  `HoldOperationResult` fields, plus three new `_error_next_step` branches
  (`HOLD_NOT_ACTIVE`, `HOLD_MARKER_ESTABLISHMENT_FAILED`,
  `HOLD_MARKER_INTEGRITY_VIOLATION`) — `HOLD_STATE_CONCURRENCY_EXCEEDED`'s
  existing branch is left untouched.

## 3. Source Inputs

- `docs/architecture/adr_evidence_retention_disposal_enforcement.md` —
  Decision 12, Non-Negotiable Invariants 32-37
- `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
  §21 (all subsections 21.1-21.11) — the binding, exact contract for field
  names, method signatures, disposition precedence, error codes, rendering
  rules, and file inventory
- Existing implementation: `hold_transitions.py`, `retention_service.py`,
  `hold_repository.py`, `custody_sweep_client.py`, `marker_store.py`,
  `core/time.py`
- Existing CLI pattern reference: `audit_platform_integrity/commands.py`
  (parser/dispatch shape to mirror), `operator_cli/main.py` (per-command-group
  construction pattern used for `generate intelligence`/`generate report`/
  `certify audit`)

## 4. API Contracts Affected

Three new CLI commands (no HTTP API changes):

- `rcp retention hold place --client-id --audit-id --stage --actor --reason`
- `rcp retention hold release --client-id --audit-id --stage --actor --reason`
  (new required `--reason`, corrected from §8's original omission)
- `rcp retention hold status --client-id --audit-id --stage` (no `--actor`/
  `--reason`)

All three return `HoldOperationResult` (§21.4), rendered per §21.9. Error
codes: `INVALID_IDENTIFIER` (emitted by this command group's own
`_validate_hold_identifier` translation boundary in `commands.py` — corrected
in a post-QA release-readiness pass; see §9), `HOLD_NOT_ACTIVE` (release
only), `HOLD_MARKER_ESTABLISHMENT_FAILED`, `HOLD_MARKER_INTEGRITY_VIOLATION`,
`STORAGE_ERROR`. `HOLD_ALREADY_ACTIVE` is not part of this contract (§21.7) —
a completed, repeated PLACE returns `disposition="no_op"` with exit code 0.

## 5. Data Models / Storage Affected

No new DynamoDB tables, no schema changes. No new fields on `LegalHold`/
`LegalHoldEvent`. `HoldOperationResult` is a pure in-memory, operator-facing
result contract — never persisted.

## 6. Files Expected to Change

Modified production:
- `src/release_confidence_platform/evidence_retention/hold_transitions.py`
- `src/release_confidence_platform/evidence_retention/retention_service.py`
- `src/release_confidence_platform/operator_cli/main.py`
- `src/release_confidence_platform/operator_cli/result.py`

New production:
- `src/release_confidence_platform/evidence_retention/commands.py`
  (subsequently corrected in a post-QA release-readiness pass to add the
  `_validate_hold_identifier` `INVALID_IDENTIFIER` translation boundary —
  see §9)

Modified tests:
- `tests/unit/evidence_retention/test_hold_transitions.py`
- `tests/unit/evidence_retention/test_retention_service.py`
- `tests/unit/test_operator_cli_result.py`

New tests:
- `tests/unit/test_operator_cli_retention.py`

## 7. Security / Authorization Considerations

- `client_id`/`audit_id` validated via the existing `validate_identifier`
  before any `RetentionService` call.
- `RetentionService` remains the sole boundary into hold-state storage
  (§21.2) — `commands.py` never imports `HoldRepository` and never calls
  `get_legal_hold`/`upsert_hold`/`write_hold_event` directly, including for
  the read-only STATUS path. Enforced by a structural AST-based test
  (`test_commands_module_never_references_hold_repository_directly`).
- `--reason` is required and non-empty for both PLACE and RELEASE — no
  synthetic default is ever substituted (a legal-hold governance action must
  carry the operator's actual justification).
- The operator never supplies the `now` timestamp — generated internally via
  `core.time.utc_now_iso()`, no `--now`/`--timestamp` CLI argument exists.
- Text/JSON rendering reuses the existing `sanitize()` boundary in
  `result.py` unmodified — no parallel rendering path.
- `HoldOperationResult` has no field capable of carrying `placed_by`,
  `released_by`, `reason`, `marker_s3_key`, `marker_confirmed_last_modified`,
  or any DynamoDB/S3 key shape — a structural, not merely rendering-time,
  leak-prevention guarantee (§21.4/21.9).

## 8. Dependencies / Constraints

- No new third-party dependencies.
- No custody-duration configuration (`CustodyPeriodConfigLoader`) is used or
  permitted for these three commands (§19 requirement 19) — `RetentionService`/
  `HoldTransitions`/`CustodySweepClient` have no `custody_period_days`
  parameter anywhere, unchanged by this subphase.
- No infrastructure, IAM, deployment, or activation change.

## 9. Assumptions

**Correction (post-QA release-readiness review):** the original version of
this plan carried an "assumption requiring confirmation" here stating that
`commands.py` inheriting `INVALID_EVENT` (the codebase-wide
`validate_identifier` helper's own hardcoded error code) instead of TD
§21.5's specified `INVALID_IDENTIFIER` was an acceptable, precedented
inheritance. Product Strategy's release-readiness review correctly rejected
that characterization: TD §21.5 is this command group's own authoritative
contract and explicitly requires `INVALID_IDENTIFIER`, so silently letting
`INVALID_EVENT` leak through was a genuine defect, not an accepted
pre-existing pattern. It has since been corrected: `commands.py` now defines
a narrow, A1.4b-local `_validate_hold_identifier` translation boundary that
reuses `validate_identifier`'s identifier-format rules unchanged (no
reimplementation of validation logic) but catches its `INVALID_EVENT`
failure and re-raises a sanitized `ValidationError` with error code
`INVALID_IDENTIFIER`, for both `client_id` and `audit_id`, identically
across `place`/`release`/`status`. `core/validators.py` itself is
unmodified — its codebase-wide `INVALID_EVENT` behavior remains correct and
unchanged for every other caller. See the implementation report's §5/§9 and
§10 for the corrected regression coverage and validation evidence.

Remaining assumptions requiring confirmation (flagged, not silently
resolved):

- `--stage`/`--output` argument shape (choices, defaults) is not specified
  by §21.5 beyond "required" — this implementation follows the majority
  existing CLI convention (`--stage` with `choices=("dev","staging","prod")`,
  `--output` with `choices=("text","json")`, `default="text"`), matching the
  `client`/`audit`/`config` command groups rather than `certify audit`'s
  `("json","human")`/`default="human"` variant, since retention commands
  flow through the standard `render()`/`render_error()` dispatch which only
  special-cases `output == "json"`.
- `CommandResult.data`'s `"status"` key (from `HoldOperationResult.status`,
  e.g. `"ACTIVE"`) overwrites `CommandResult`'s own `"status"` field
  (`"success"`) in the merged JSON payload, since dict-literal construction
  in `render()` spreads `**result.data` after the `"status"` key. This exact
  collision pattern is already an accepted, precedented behavior for
  `generate intelligence`/`generate report`/`certify audit` (whose `data`
  dicts also carry a domain-specific `"status"` value distinct from the
  CLI's own success/failure status) — this implementation follows the same
  established pattern rather than introducing a new field name to avoid it.

## 10. Validation Plan

```bash
uv run pytest -q tests/unit/evidence_retention/test_hold_transitions.py
uv run pytest -q tests/unit/evidence_retention/test_retention_service.py
uv run pytest -q tests/unit/test_operator_cli_result.py
uv run pytest -q tests/unit/test_operator_cli_retention.py
uv run pytest -q
uv run ruff check <touched files>
uv run ruff format --check <touched files>
```
