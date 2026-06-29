# Phase 4A — Completion Summary and Lessons Learned

**Phase:** 4A — Deterministic Aggregation Foundation and Engineering Retrieval Layer
**Completion date:** 2026-06-29
**GitHub Issues:** #30–#36
**Status:** COMPLETE — all subphases merged, Campaign 3 passed, HITL gate pending

---

## 1. Phase 4A Objective

Phase 4A formalized the Phase 4 aggregation core, added the Engineering Retrieval CLI, defined the Phase 5 consumer contract, and eliminated the `src/`–`packages/` divergence before Phase 5 begins.

Phase 4A is NOT a synthetic testing or dashboard-first deliverable. It is a deterministic, evidence-backed aggregation foundation with full audit repeatability and a read-only diagnostic CLI for engineering use.

---

## 2. Subphase Completion Record

| Subphase | Issue | Merged PR | Completion |
|----------|-------|-----------|------------|
| 4A.1 Documentation | #30 | PR #37 | 2026-06-16 |
| 4A.2 Aggregation Schema | #31 | PR #37 | 2026-06-16 |
| 4A.3 Phase 5 Consumer Contract | #32 | PR #37 | 2026-06-16 |
| 4A.4 Aggregation Persistence | #33 | PR #38 | 2026-06-19 |
| 4A.5 Engineering Retrieval CLI | #34 | PR #39 | 2026-06-20 |
| 4A.6 Operational Hardening | #35 | PR #40 | 2026-06-21 |
| 4A.7 Validation Campaign | #36 | — (operational) | 2026-06-29 |

### Mid-campaign Bugfix PRs (Phase 4A.7)

| Issue Found | PR | Description |
|-------------|----|-------------|
| Aggregation envelope miscount | PR #41 | `failure-summaries` total_failures included runs with no evidence |
| Failure summaries PASS miscount | PR #44 | `retrieve failure-summaries` counted PASS outcomes in `total_failures` |
| Lineage manifest scalability blocker | PR #45 | `lineage_manifest_v2` — paginated lineage to replace single-item v1 |

---

## 3. Validation Campaign History

### Campaign 1 (2026-06-17) — INCOMPLETE

No aggregation cycle existed in the live AWS environment. The audit used for validation predated the aggregation Lambda deployment. Infrastructure and CLI connectivity confirmed. Did not satisfy Phase 4A.7 closure criteria.

See: `docs/qa/phase4a7_campaign_01.md`

### Campaign 2 (2026-06-24) — FAILED

Three parallel 48-hour audits (191–192 executions, ~955 evidence references each) completed the full lifecycle successfully but failed aggregation on all three with `failure_category=EVIDENCE_TRANSFORMING`, `reason_code=LINEAGE_MANIFEST_TOO_LARGE`.

Root cause: `lineage_manifest_v1` embeds all raw-result refs for a manifest scope in a single DynamoDB item. The 400KB per-item limit is reached at approximately 670–700 refs/scope. Campaign 2 audits reached 955 refs. This was pre-approved MVP fail-closed behavior from the original ADR; it was never triggered before Campaign 2.

Fix: `lineage_manifest_v2` — new ADR (`adr_phase_4a_lineage_manifest_pagination.md`) + technical design + PR #45. Separately, PR #44 fixed the `failure-summaries` PASS miscount discovered during Campaign 2 retrieval analysis.

See: `docs/bugs/phase4a7_lineage_manifest_scalability_blocker.md`

### Campaign 3 (2026-06-29) — PASS

Three independent production-like audits (191–192 executions, 955–960 evidence references each). All three reached aggregation `status=COMPLETED` with full lineage intact. `LINEAGE_MANIFEST_TOO_LARGE` not observed. 2,875 total evidence references validated across 3 audits with consistent manifest hashes and zero lineage mismatches.

See: `docs/qa/phase4a7_campaign_03.md`

---

## 4. Test Suite Growth

| Phase | Test Count |
|-------|-----------|
| Phase 4A.6 (pre-4A.7 TDD) | 467 |
| Phase 4A.7 completion | 602 |
| Net new tests | +135 |

Notable new test suites added during Phase 4A.7:
- `tests/unit/aggregation/test_lineage_pagination.py` — 15 tests (worst-case ceiling regression pinned at 275 refs/page, hash-stability across retries, page-boundary determinism)
- `tests/unit/aggregation/test_orchestrator_lineage_pagination.py` — 4 tests (955-ref end-to-end, retry-resume, hash-mismatch fail-closed, diagnostic context propagation)
- Retrieval v1/v2 compatibility tests added to `tests/unit/retrieval/test_retrieval_commands.py`

---

## 5. Architecture Decisions (Phase 4A)

| ADR | Decision |
|-----|----------|
| `adr_phase_4a_engineering_retrieval_consumer_contract.md` | Engineering CLI is read-only diagnostic tooling; authoritative evidence resides in immutable aggregation artifacts |
| `adr_phase_4a_lineage_manifest_pagination.md` | `lineage_manifest_v2` — bounded header + immutable paginated pages; v1 records remain readable, unmigrated |

---

## 6. Lessons Learned

### 6.1 Live Environment Gaps Are Invisible to Unit Tests

All three Phase 4A.7 campaign blockers were undetectable by the unit and integration suite:
- Campaign 1: The aggregation Lambda was not deployed to dev when the only COMPLETED audit was created. Unit tests assume infrastructure exists.
- Campaign 2: The `lineage_manifest_v1` byte ceiling is only reachable at real scale (~955 refs). Unit test fakes use minimal fixtures (1–5 records). The unit suite had no fixture at Campaign 2 scale.
- Campaign 2: The `failure-summaries` PASS miscount was latent in the retrieval service since 4A.5 but was only observable with real data containing PASS results.

**Implication for Phase 5:** Live validation campaigns against real AWS data are a necessary quality gate, not optional coverage. Unit test fixtures should include a documented "minimum realistic scale" rule: any test involving aggregation correctness should include at least one fixture at the expected production scale for that dimension.

### 6.2 MVP Fail-Closed Behavior Requires a Scale Budget

The `lineage_manifest_v1` design was deliberately approved at MVP with a documented fail-closed safety valve (`LINEAGE_MANIFEST_TOO_LARGE`). The fail-closed behavior did its job — no data was corrupted. However, the scale budget for that design was not tracked against real audit execution rates. The first live audit at production-representative scale (Campaign 2) immediately exceeded the ceiling.

**Implication for Phase 5:** Every MVP design with a documented ceiling should have a corresponding live measurement commitment: "at what scale does this ceiling become a blocker?" and a tracking entry in the follow-up backlog.

### 6.3 Hash-Stability Requires Separating Attempt-Specific Fields

The initial `lineage_manifest_v2` implementation included `aggregation_job_id` and `created_at` in the `page_hash` and `manifest_hash` inputs. Because these fields differ between retry attempts (new job ID, new wall-clock timestamp), a retry would always compute a different hash than the stored page from the prior attempt — making every retry incorrectly report `LINEAGE_PAGE_HASH_MISMATCH` and fail closed.

The fix is to compute hashes exclusively over evidence-derived fields (fields that are pure functions of the raw evidence content) and exclude attempt-specific metadata fields. TDD surfaced this defect before the code shipped: `test_retry_resumes_after_partial_page_write_crash_without_duplication` FAILED against the initial implementation.

**Implication for Phase 5:** Any hash used in a retry/resume idempotency protocol must be defined over fields that are stable across attempts. This rule is now documented in `phase_4a_lineage_manifest_pagination_technical_design.md §3` and pinned by a regression test.

### 6.4 Pre-Existing Bugs Surface During New Development

The `get_evidence_references()` `source_refs` field-name bug was latent from Phase 4A.5. It was silently returning empty results for all v1 manifests. It was found only when writing the v1/v2 compatibility tests for `lineage_manifest_v2`. The existing test had a vacuous assertion loop that never exercised the actual ref values.

**Implication for Phase 5:** When adding v2 readers, always test the v1 path end-to-end with a real fixture value assertion — not just "no error." A test that passes without actually checking values provides false confidence.

---

## 7. Deferred Follow-Up Items (Not Phase 4A Blockers)

These items were identified during Phase 4A.7 and explicitly deferred to Phase 5 per the ADR and engineering review.

| Item | Priority | Source |
|------|----------|--------|
| Retrieval CLI pagination for `evidence-references` and `aggregation-results` | **Mandatory before Phase 5** | `adr_phase_4a_lineage_manifest_pagination.md` §4, mandatory follow-up |
| `lifecycle-transitions` retrieval gap (reads `LIFECYCLE#` SK prefix but lifecycle history stored in root record `lifecycle_history` list) | Medium — Phase 5 retrieval spec | Campaign 1 anomaly, documented |
| Single per-client DynamoDB partition key hot-partition risk at high audit volume | Low — accepted MVP tradeoff | Broader scaling review |
| Sequential S3 reads in `_load_records` within Lambda timeout | Low — within budget at current scale | Broader scaling review |
| `lineage_manifest_v1` records not migrated to v2 | Informational — v1 remains readable via reader branch | By design; migration not required for Phase 5 |

---

## 8. Phase 5 Entry Conditions

Phase 5 must not begin until:

1. Phase 4A.7 HITL gate is approved (this document + Campaign 3 QA sign-off)
2. Retrieval CLI pagination is designed and implemented (ADR-mandated Phase 5 prerequisite)
3. All 602 Phase 4A tests continue to pass on main

Phase 5 may not reopen or modify Phase 4A implementation without:
- A new ADR or ADR amendment
- A new branch
- A new HITL gate

---

## 9. Phase 4A Artifacts Index

### Product and Architecture

- `docs/product/phase_4a_aggregation_foundation_product_spec.md`
- `docs/architecture/phase_4a_aggregation_foundation_technical_design.md`
- `docs/architecture/phase_4a_aggregation_schema.md`
- `docs/architecture/phase_4a_phase5_consumer_contract.md`
- `docs/architecture/adr_phase_4a_engineering_retrieval_consumer_contract.md`
- `docs/architecture/adr_phase_4a_lineage_manifest_pagination.md`
- `docs/architecture/phase_4a_lineage_manifest_pagination_technical_design.md`

### QA

- `docs/qa/phase_4a_aggregation_foundation_test_plan.md`
- `docs/qa/phase4a5_qa_report.md`
- `docs/qa/phase4a6_qa_report.md`
- `docs/qa/phase4a7_campaign_01.md`
- `docs/qa/phase4a7_campaign_02.md`
- `docs/qa/phase4a7_campaign_03.md`

### Bugs

- `docs/bugs/phase4a7_lineage_manifest_scalability_blocker.md`

### Release

- `docs/release/phase4a6_pr.md`
- `docs/release/phase4a_closure.md` (this document)
