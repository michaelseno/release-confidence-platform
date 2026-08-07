# Test Report

Branch: `feature/a1-3d4-phase7-certificate-hold-coordination`
(from `main@65e3ab1f23a89e2dd7dd3a8abb953fea8dd9e07f`).

This report documents an independent QA validation pass. Every command
below was executed directly against the actual working tree; nothing here
is transcribed from the implementer's self-report without independent
re-derivation. Where the implementation report made a claim (e.g. the
Ruff baseline distribution), this pass re-derived it from an isolated
`main` worktree checkout rather than trusting the stated numbers.

## 1. Execution Summary

- Full suite: **2115 collected, 2113 passed, 2 skipped, 0 failed** —
  exact match to the task brief's expected numbers (2049 baseline + 66
  new tests).
- Focused: `tests/unit/audit_platform_integrity/` — 275 passed.
  `tests/unit/test_operator_cli_certify.py` — 21 passed.
  `tests/unit/test_operator_cli_result.py` — 26 passed.
- All 20 acceptance items independently verified: **20/20 PASS**.
- No blocking defects found. One non-blocking, informational precision
  note (§5, Observation 1).

## 2. Detailed Results (Per Acceptance Item)

| # | Item | Result | Evidence |
|---|---|---|---|
| 1 | Exact 14-file final scope | **PASS** | §7 below |
| 2 | `engine.py`/`identity.py` unchanged | **PASS** | Both `git diff main --` empty |
| 3 | `test_engine_no_phase6_mutation.py` unchanged | **PASS** | `git diff main --` empty |
| 4 | `config/custody_periods.json`/`infra/` unchanged | **PASS** | Both `git diff main --` empty |
| 5 | Publisher precedence order | **PASS** | Direct source read confirms: (1) `self._hold_repository is None` check, (2) `_parse_cert_key_identity(key)`, (3) `get_legal_hold(consistent_read=True)`, (4) `put_object(..., Tagging=tagging)` — exact order, `publisher.py:124-149` |
| 6 | Missing hold wins over malformed key | **PASS** | `test_write_artifact_missing_hold_repository_wins_over_malformed_key` asserts `error_type == "HOLD_COORDINATION_NOT_CONFIGURED"` with a 10-segment malformed key present; test passes |
| 7 | Unconditional replacement + forced recert | **PASS** | `write_cert_metadata_complete`'s `Put` construction has no `ConditionExpression` key anywhere (`repository.py:458-463`); `test_forced_recertification_replaces_existing_record` writes twice and asserts the second write's `terminal_state`/`certificate_id` replaced the first; passes |
| 8 | Exactly 1 Put + 1 ConditionCheck | **PASS** | `test_write_cert_metadata_complete_transaction_shape_and_no_put_condition` asserts `len(TransactItems) == 2`, `len(put_items) == 1`, `len(cc_items) == 1`, `cc["Key"] == {"PK": ..., "SK": "AUDIT#{audit_id}#LEGALHOLD"}` — matches LegalHold PK/SK shape exactly; passes for both never-held and already-held scenarios |
| 9 | No `ConditionExpression` on Put | **PASS** | Same test, asserts `"ConditionExpression" not in put_item` twice (once per scenario) |
| 10 | Fresh clock/hold/governance per retry | **PASS** | `test_fresh_clock_and_hold_state_recomputed_per_retry_attempt` and `test_no_stale_governance_value_survives_between_attempts` both use `_FlakyDynamoClient`(fail_times≥1) + `_SequencedHoldRepository` to genuinely simulate a multi-attempt retry, then assert the *final committed* item reflects only the final attempt's own hold-state read, never an earlier attempt's; both pass |
| 11 | TTL held/unheld correctness | **PASS** | `test_ttl_omitted_when_held` (seeds `HOLD_STATUS_ACTIVE` LegalHold, asserts `"ttl_disposal_at" not in item`) and `test_ttl_present_when_unheld` (asserts `ttl_disposal_at == custody_expires_at`); both pass |
| 12 | Fixed `evidence_class="certificate"` | **PASS** | `repository.py::_cert_governance_fields` line 105 (`"evidence_class": "certificate"`, literal); `publisher.py::_cert_tagging` line 85 (`"certificate"`, literal in the `urlencode` dict) — both fixed string literals, not variables |
| 13 | 11-segment malformed-key matrix | **PASS** | `test_write_artifact_rejects_malformed_key`, 9 parametrized cases: too-few (`10_segments_drop_cert_version`), too-many (`12_segments_extra_inserted`), wrong `parts[0]` (`wrong_segment_0`), wrong `parts[10]` (`wrong_segment_10`), empty `client_id` (`empty_client_segment`), empty `audit_id` (`empty_audit_segment`), leading slash, trailing slash, doubled slash — all 9 (exceeding the "at least 2" requirement) assert `hold_repository.calls == []` and `s3.put_object.assert_not_called()`; all pass |
| 14 | TN-12 BLOCKED-path real-publisher tag equality | **PASS** | `test_engine.py::build_tn12_blocked_write_artifact_call` runs the **real** `CertificationEngine.certify()` against a repository stub whose `read_artifact_raises`, capturing `publisher.write_calls[0]` — the actual `(key, artifact)` the real engine passed to `write_artifact`. `test_hold_coordination.py::test_tn12_blocked_path_tag_construction_matches_certified_path` imports this helper, constructs a **real, non-stubbed** `CertificationPublisher` with a fake `HoldRepository`, calls the real `write_artifact(key, artifact)`, and asserts the resulting `Tagging=` string is byte-identical to `test_certified_path_tag_construction`'s CERTIFIED-path output under the same hold state. This is a genuine, non-stub-only proof chain — confirmed by direct read, not merely by test name |
| 15 | Category 3 exclusion, all 4 write methods | **PASS** | `test_repository.py`: `test_write_certjob_pending_carries_no_governance_fields`, `test_update_certjob_in_progress_carries_no_governance_fields`, `test_update_certjob_complete_carries_no_governance_fields`, `test_update_certjob_failed_carries_no_governance_fields` (all 4 methods, field-absence + no `hold_version`-containing key) plus `test_certjob_write_methods_perform_zero_hold_reads` (all 4 methods, zero hold reads). `test_engine.py`: `test_certification_job_write_methods_never_carry_governance_fields_full_flow` and `test_certification_job_write_methods_zero_hold_coordinated_transaction_construction` (full-flow, real engine) |
| 16 | Retrieval custody-independent, zero writes | **PASS** | `test_retrieve_cert_zero_custody_period_config_loader_calls` (zero `CustodyPeriodConfigLoader` calls, zero `HoldRepository` construction). `test_retrieve_cert_unaffected_by_certificate_configuration` asserts `_SpyCertRepository.write_calls == []` (covers `write_cert_metadata_complete`, `write_certjob_pending`, `update_certjob_in_progress`, `update_certjob_complete`, `update_certjob_failed` — all 5) and `_SpyCertPublisher.write_calls == []` (covers `write_artifact`) — all 6 write methods, not a subset |
| 17 | Shared phase-neutral guidance, no leak | **PASS** | Direct read of the 3 new `_error_next_step` branches (`result.py:466-486`): none names "certificate"/"intelligence"/"report"; text is generic ("evidentiary class and stage", "construction-time wiring defect", "concurrent legal-hold management"). `test_error_next_step_guidance_leaks_no_identifier_or_key` embeds a real fake `client_id`/`audit_id`/S3 key into a *triggering message* and asserts none appear in the rendered guidance — a genuine leak probe, not merely a length check |
| 18 | No issue #118 defect codified as accepted | **PASS** | Grep across all new/modified test files for stale-state/orphan/divergence patterns found only ordinary status assertions (e.g. `item["status"] == "PENDING"` as an expected initial-write value) and the explicit scope-boundary comment in `test_engine.py:580-582` documenting the exclusion — no test asserts a partial-success defect as passing behavior |
| 19 | Zero new Ruff findings vs. baseline | **PASS**, with one non-blocking precision note — see §2.2/§5 |
| 20 | All specified commands | **PASS** | See §2.1, §2.3, §2.4, §7 |

## 2.1 Canonical and Focused Test Commands

```
$ uv run pytest -q tests/unit/audit_platform_integrity/
275 passed in 0.55s

$ uv run pytest -q tests/unit/test_operator_cli_certify.py
21 passed in 0.38s

$ uv run pytest -q tests/unit/test_operator_cli_result.py
26 passed in 0.03s

$ uv run pytest --collect-only -q
2115 tests collected in 1.10s

$ uv run pytest -q
2113 passed, 2 skipped in 6.98s
```

Result: **PASS.** Exact match to the task brief's expected 2115
collected / 2113 passed / 2 skipped — no variance to reconcile.

## 2.2 Ruff Check — Independently Re-Derived Baseline Comparison

The implementation report's own "Corrective note" (§10, implementation
report) disclosed that an earlier pass of this same validation had
compared Ruff finding *counts* per file rather than each finding's
underlying rule/content, and had been fooled by a coincidental count
match masking a real substitution. This QA pass does not repeat that
mistake: `main` was checked out into an isolated `git worktree`
(`/tmp/qa_main_worktree`) and the identical `ruff check` command was run
there, then every individual finding (file, line, rule code, message
content) was compared against the branch's findings — not just totals.

Branch (current):
```
$ uv run ruff check <10 files>
Found 12 errors.
```
Distribution: `main.py` 7 (4×I001 @ lines 3/244/276/462, 3×E501 @ lines
253/282/523); `test_repository.py` 1 (E501 @ line 198); `test_publisher.py`
2 (E501 @ lines 32/347); `test_engine.py` 1 (E501 @ line 154);
`test_operator_cli_certify.py` 1 (E501 @ line 148); `publisher.py`,
`repository.py`, `result.py`, `test_operator_cli_result.py`,
`test_hold_coordination.py`: 0.

`main` baseline (isolated worktree, identical command):
```
$ uv run ruff check <same 9 pre-existing files>
Found 13 errors.
```
Distribution: `main.py` 7 (identical 4×I001/3×E501 rule pattern, at
pre-shift line numbers 3/244/276/462, 253/282/504); `test_repository.py`
1 (E501, pre-shift line 47); `test_publisher.py` 2 (E501, pre-shift lines
18/146); `test_engine.py` 1 (E501, pre-shift line 154); **`test_operator_cli_certify.py`
2** (1×I001 @ line 13 + 1×E501 @ line 127); others 0.

**Content-level reconciliation, not just count:**
- Every finding present on the branch was matched to an identical-content
  baseline finding (same docstring/line text, same rule code), confirming
  no new violation category was introduced anywhere — only line-number
  shifts caused by unrelated insertions earlier in each file.
- `test_operator_cli_certify.py` genuinely dropped from 2 baseline
  findings to 1 on the branch: the pre-existing `I001` (baseline line 13,
  an unsorted `from __future__ import annotations` import block) is
  **absent** on the branch — the branch's own import-block expansion
  (adding imports needed for the composition-contract tests) happened to
  leave the block correctly sorted. This matches the implementation
  report's corrective-note explanation exactly and was independently
  confirmed by content comparison, not assumed.
- **Precision note (corrected by dev-backend post-QA, see §5 for the
  correction record)**: `main.py`'s `I001` finding at line 462 sits inside
  the `certify` dispatch block — and on the branch, this is exactly the
  block A1.3d.4 modified (it added the `CustodyPeriodConfigLoader` and
  `HoldRepository` imports to this same already-unsorted block). This QA
  pass's original review of the implementation report found it
  characterized all 4 of `main.py`'s `I001` findings as sitting in
  "argparse and construction blocks this subphase does not touch," which
  was imprecise for this one entry, since the block *was* touched. This
  was never a blocking finding: the rule (`I001`, import-block-unsorted)
  was already firing on this exact block before the change and continues
  to fire after, at the same total per-file count (7) — no new violation
  category was introduced, and the two new imports were simply added into
  an import block that was already unsorted. The implementation report
  has since been corrected (§5) to state this precisely; re-verified
  accurate.

Result: **12 findings on the branch, all individually traceable by rule
and content to the 13-finding `main` baseline (the 13th being a
genuinely-resolved pre-existing issue, not a masked substitution).
Zero new findings.**

## 2.3 Ruff Format --check — Independently Re-Derived Baseline Comparison

Branch:
```
$ uv run ruff format --check <10 files>
Would reformat: repository.py, main.py, test_engine.py, test_publisher.py,
  test_repository.py, test_operator_cli_certify.py
6 files would be reformatted, 4 files already formatted.
```

`main` baseline (isolated worktree, same 9 pre-existing files):
```
$ uv run ruff format --check <9 files>
Would reformat: repository.py, main.py, test_engine.py, test_publisher.py,
  test_repository.py, test_operator_cli_certify.py
6 files would be reformatted, 3 files already formatted.
```

Identical dirty-file set (6/6, same files) on both branch and baseline —
the 4th clean file on the branch is the new `test_hold_coordination.py`,
which has no baseline counterpart. `publisher.py` and `result.py` remain
clean on both. Per-file `ruff format --diff` hunk counts were additionally
compared and found identical between branch and baseline for all 6 dirty
files (`repository.py` 4, `main.py` 6, `test_engine.py` 2,
`test_publisher.py` 1, `test_repository.py` 4, `test_operator_cli_certify.py`
1) — no new formatting drift introduced by this subphase's own added
code.

Result: **PASS. Exact match, no regression.**

## 2.4 `git diff --check main`

```
$ git diff --check main
(no output, exit 0)
```
Result: **Clean — no whitespace/EOL errors.**

## 3. Failed Tests

None. Zero test failures across the full suite or any focused subset.

## 4. Failure Classification

Not applicable — no failures occurred in this validation pass.

## 5. Observations

- No flakiness observed — the full suite and all focused subsets ran to
  completion deterministically; no rerun was required.
- **Observation 1 — stale diff-stat figures in the implementation report
  (documentation-record discrepancy, detected by QA, corrected by
  dev-backend, re-verified by QA — RESOLVED, never blocking)**: this QA
  pass's independent execution of `git diff --stat main` found
  `tests/unit/test_operator_cli_certify.py` at `328 +++++++-` (327
  insertions, 1 deletion) and a `1494 insertions(+), 85 deletions(-)`
  total, whereas the implementation report as originally read stated `327
  ++++++++...` (0 deletions) and an `84`-deletion total. Traced to the
  implementation report's own disclosed "Corrective note" (a post-hoc
  blank-line removal in that file, applied after the report's original
  diff-stat capture) — i.e. the report's stat simply predated its own
  documented fix. Flagged back to the orchestrator/dev-backend rather than
  silently reconciled. **Dev-backend has since corrected**
  `docs/backend/a1_3d4_phase7_certificate_hold_coordination_implementation_report.md`
  on this same branch to state `test_operator_cli_certify.py` as `+327/-1`
  and the total as `1494 insertions(+), 85 deletions(-)`, touching no
  source or test file. Independently re-verified by this QA pass via
  direct re-execution: `git diff --numstat main -- tests/unit/test_operator_cli_certify.py`
  → `327  1` and `git diff --numstat main | awk '{ins+=$1; del+=$2} END {print ins, del}'`
  → `1494 85` — both match the corrected report exactly. **Confirmed
  resolved.**
- **Observation 2 — imprecise `main.py` I001 characterization
  (documentation-record discrepancy, detected by QA, corrected by
  dev-backend, re-verified by QA — RESOLVED, never blocking)**: this QA
  pass found the implementation report characterized all 4 of `main.py`'s
  `I001` findings as sitting in "blocks this subphase does not touch,"
  which was imprecise for the finding at the `certify` dispatch block
  (line 462) — that block *was* modified by this subphase (the new
  `CustodyPeriodConfigLoader`/`HoldRepository` imports were added directly
  into it; independently re-confirmed via `git diff main --
  src/release_confidence_platform/operator_cli/main.py`, which shows the
  insertion at that exact block). The underlying Ruff violation was never
  new — same rule, same block, already present on the authorized baseline
  pre-change (independently confirmed in §2.2 above against an isolated
  `main` worktree) — so this never affected the "zero new findings"
  conclusion or the sign-off. Flagged back to the orchestrator/dev-backend
  as a documentation-precision note, not a code defect. **Dev-backend has
  since corrected** the same implementation report's "Validation
  Performed" section (the paragraph beginning "Distribution: 7 in
  `main.py`...") to state precisely: all four `I001` findings are
  baseline-pre-existing (none new); three sit in genuinely untouched
  blocks (module-level line 3, `retrieve report-*` line 244, `retrieve
  cert-*` line 276); the fourth (line 462, `certify` block) *was* modified
  by A1.3d.4, but its `I001` violation already existed on the authorized
  baseline, and this subphase's modification of that block introduced no
  new Ruff finding. Independently re-read and re-verified by this QA
  pass: the corrected paragraph now matches the code exactly. **Confirmed
  resolved.**
- Both observations above were documentation-accuracy discrepancies in
  the backend's own self-report, not defects in the implementation, the
  tests, or this QA pass's own technical findings. No application code,
  test file, or Ruff/pytest result changed as part of either correction —
  confirmed by re-running the two commands above and by `git status
  --short` (§7) showing an unchanged file set. This QA pass's underlying
  code/test validation (§2 above, all 20 acceptance items) is unaffected,
  and `[QA SIGN-OFF APPROVED]` stands unchanged.
- No other inconsistency found between the implementer's self-report and
  independently re-derived evidence (file inventory, pytest counts, and
  Ruff distribution all matched exactly on independent re-execution).

## 6. Regression Check

- **Full suite**: 2113 passed / 2 skipped vs. 2047 passed / 2 skipped
  baseline — zero regressions; delta of +66 is entirely new test cases,
  confirmed against the per-file collected-test-count table in the
  implementation report and independently reproduced by direct
  `pytest --collect-only -q` execution.
- **`engine.py`**: zero-line diff against `main` — confirmed.
- **`identity.py`**: zero-line diff against `main` — confirmed
  (`build_cert_s3_key` unchanged; the new parser is a read-time inverse
  living in `publisher.py`, not a modification to construction).
- **`test_engine_no_phase6_mutation.py`**: zero-line diff against `main`
  — confirmed; this file's Phase 6 SK-namespace non-mutation invariant is
  unaffected, and Category 3 `CertificationJob` coverage is correctly
  placed in `test_repository.py`/`test_engine.py` instead, per the
  Technical Design's explicit scope-precision correction (§20.2/§20.12).
- **`config/custody_periods.json`**: zero-line diff against `main`;
  `certificate` evidence class confirmed still an empty object `{}` — no
  custody-duration value introduced by this subphase.
- **`infra/`**: zero-line diff against `main` — no infrastructure,
  Lambda, or Serverless Framework change (Decision 10/Invariant 28
  preserved).
- **No deployment or activation occurred**: no `sls deploy`, no stage
  activation, no lifecycle-rule change — this is purely a code/test
  change on a feature branch, not yet merged or released.

## 7. Exact 14-File Final Scope Confirmation

`git status --short` **before** creating this pass's QA documents (13
entries: 12 in-scope + `AGENTS.md`):
```
 M src/release_confidence_platform/audit_platform_integrity/publisher.py
 M src/release_confidence_platform/audit_platform_integrity/repository.py
 M src/release_confidence_platform/operator_cli/main.py
 M src/release_confidence_platform/operator_cli/result.py
 M tests/unit/audit_platform_integrity/test_engine.py
 M tests/unit/audit_platform_integrity/test_publisher.py
 M tests/unit/audit_platform_integrity/test_repository.py
 M tests/unit/test_operator_cli_certify.py
 M tests/unit/test_operator_cli_result.py
?? AGENTS.md
?? docs/backend/a1_3d4_phase7_certificate_hold_coordination_implementation_plan.md
?? docs/backend/a1_3d4_phase7_certificate_hold_coordination_implementation_report.md
?? tests/unit/audit_platform_integrity/test_hold_coordination.py
```

`git status --short` **after** creating this pass's two QA documents (15
entries: 14 in-scope + `AGENTS.md`):
```
 M src/release_confidence_platform/audit_platform_integrity/publisher.py
 M src/release_confidence_platform/audit_platform_integrity/repository.py
 M src/release_confidence_platform/operator_cli/main.py
 M src/release_confidence_platform/operator_cli/result.py
 M tests/unit/audit_platform_integrity/test_engine.py
 M tests/unit/audit_platform_integrity/test_publisher.py
 M tests/unit/audit_platform_integrity/test_repository.py
 M tests/unit/test_operator_cli_certify.py
 M tests/unit/test_operator_cli_result.py
?? AGENTS.md
?? docs/backend/a1_3d4_phase7_certificate_hold_coordination_implementation_plan.md
?? docs/backend/a1_3d4_phase7_certificate_hold_coordination_implementation_report.md
?? docs/qa/a1_3d4_phase7_certificate_hold_coordination_test_plan.md
?? docs/qa/a1_3d4_phase7_certificate_hold_coordination_test_report.md
?? tests/unit/audit_platform_integrity/test_hold_coordination.py
```

Breakdown — exactly 14 in-scope paths relative to `main`:

| Category | Count | Files |
|---|---|---|
| Production, modified | 4 | `audit_platform_integrity/repository.py`, `publisher.py`, `operator_cli/main.py`, `operator_cli/result.py` |
| Tests, modified | 5 | `test_repository.py`, `test_engine.py`, `test_publisher.py`, `test_operator_cli_certify.py`, `test_operator_cli_result.py` |
| Tests, new | 1 | `test_hold_coordination.py` |
| Backend evidence records, new | 2 | `..._implementation_plan.md`, `..._implementation_report.md` |
| QA evidence records, new | 2 | `..._test_plan.md`, `..._test_report.md` (this file and its companion) |
| **Total** | **14** | |

`AGENTS.md` remains untracked (`??`) and unmodified throughout — confirmed
by direct comparison of the before/after `git status --short` snapshots
above; its line does not change between them.

`git diff --stat main` (executable/test files only — the QA docs are new
and untracked, no diff against `main` to show), executed directly by this
QA pass:
```
 .../audit_platform_integrity/publisher.py          | 114 ++++-
 .../audit_platform_integrity/repository.py         | 129 +++++-
 .../operator_cli/main.py                           |  21 +-
 .../operator_cli/result.py                         |  20 +
 tests/unit/audit_platform_integrity/test_engine.py | 164 +++++++
 .../audit_platform_integrity/test_publisher.py     | 237 ++++++++++-
 .../audit_platform_integrity/test_repository.py    | 472 ++++++++++++++++++---
 tests/unit/test_operator_cli_certify.py            | 328 +++++++++++++-
 tests/unit/test_operator_cli_result.py             |  94 ++++
 9 files changed, 1494 insertions(+), 85 deletions(-)
```
No executable (production or test) file changed as a result of adding
the two QA documents — this diff stat is unaffected by their creation
(confirmed identical before and after QA-doc creation within this pass).

**Reconciled variance from the implementation report's stated diff-stat
(RESOLVED — see Observation 1, §5)**: this QA pass's own live execution
found `test_operator_cli_certify.py` at `328 +++++++-` (327 insertions,
**1 deletion**; 85 total deletions), isolated via `git diff --stat main --
tests/unit/test_operator_cli_certify.py` → `1 file changed, 327
insertions(+), 1 deletion(-)`, whereas the implementation report as
originally read stated `327 ++++++++...` (0 deletions; 84 total
deletions). This was always fully explainable — the exact, expected
footprint of the implementation report's own disclosed "Corrective note"
(blank-line removal in `tests/unit/test_operator_cli_certify.py`, applied
after the report's original diff-stat capture) — a single blank-line
deletion with no replacement insertion produces precisely a +0/-1 delta
on top of an otherwise-unchanged 327 insertions, matching what is
independently observed here. No code, assertion, or fixture behavior was
ever affected. **Dev-backend has since corrected the implementation
report's stated figures to `+327/-1` and `1494 insertions(+), 85
deletions(-)`**, matching the live diff exactly; this QA pass re-ran both
`git diff --numstat main -- tests/unit/test_operator_cli_certify.py`
(→ `327  1`) and `git diff --numstat main | awk '{ins+=$1; del+=$2} END
{print ins, del}'` (→ `1494 85`) and confirms the corrected report is now
byte-accurate. Confirmed non-blocking throughout, now also confirmed
record-accurate.

## 8. QA Decision

All 20 acceptance items in
`docs/qa/a1_3d4_phase7_certificate_hold_coordination_test_plan.md` are
independently verified and pass:

- Full suite passes with zero regressions (2113 passed, 2 skipped, 2115
  collected — exact match to the expected numbers, no variance to
  reconcile).
- Lint posture independently re-derived (not merely trusted) against an
  isolated `main` worktree baseline, compared by rule/content rather than
  count alone — 12 findings, all traceable to the 13-finding baseline
  (one genuinely, verifiably resolved). Format posture identical: same 6
  dirty / 4 clean split, identical per-file diff-hunk counts.
- `git diff --check` is clean.
- Working tree contains exactly the authorized 14-file in-scope set;
  `AGENTS.md` untouched throughout.
- `engine.py`, `identity.py`, `test_engine_no_phase6_mutation.py`,
  `config/custody_periods.json`, and `infra/` all show zero diff against
  `main`.
- Every structural contract in ADR Decision 11/Invariant 31 and TD
  §20.8/§20.8.1/§20.11.1 was independently re-derived from the actual
  diff and actual test bodies (unconditional-Put preservation, exactly
  one hold `ConditionCheck`, fresh-per-retry governance computation, TTL
  held/unheld correctness, the 11-segment key parser's full malformation
  matrix, the TN-12 BLOCKED-path real-publisher tag-equality proof chain,
  Category 3 exclusion across all 4 `CertificationJob` write methods, and
  the shared phase-neutral, non-leaking error guidance) — no deviation
  found beyond the one documented non-blocking, documentation-precision
  observation (§5, Observation 1).

No blocking defects. No unresolved failures. No regressions. No scope
leakage beyond the two QA evidence records this task explicitly
authorized.

[QA SIGN-OFF APPROVED]
