# Phase 4A.7 — Operational Validation Campaign 2

**Campaign type:** Scale validation — first live aggregation cycle at production-representative volume
**Date:** 2026-06-24
**Branch at time of campaign:** `main` (post-PR #40, pre-PR #45)
**AWS account:** 463470948609
**AWS region:** us-east-1
**DynamoDB table:** `release-confidence-platform-dev-metadata`
**Purpose:** Validate full audit lifecycle and aggregation pipeline at production-representative execution volume (48-hour audits, multiple endpoints, ~190 executions per audit).

---

## 1. Context

Campaign 1 (2026-06-17) established infrastructure connectivity and CLI operability but could not satisfy Phase 4A.7 closure criteria because no audit in the live environment had a completed aggregation cycle. Campaign 2 was the first campaign to run a full audit-to-aggregation lifecycle from scratch.

---

## 2. Audits Executed

Three independent 48-hour audits were executed in parallel against live AWS infrastructure:

| Audit | Executions | Evidence References | Aggregation Outcome |
|-------|-----------|---------------------|---------------------|
| Audit 1 | ~191 | ~955 | FAILED — `LINEAGE_MANIFEST_TOO_LARGE` |
| Audit 2 | ~192 | ~960 | FAILED — `LINEAGE_MANIFEST_TOO_LARGE` |
| Audit 3 | ~192 | ~960 | FAILED — `LINEAGE_MANIFEST_TOO_LARGE` |

Note: Raw audit identifiers, aggregation job IDs, and CLI JSON output for Campaign 2 were not formally captured as §6.3 artifacts. This is an acknowledged documentary gap in the Phase 4A record. The root cause analysis and failure evidence are documented in the bug report below.

---

## 3. Campaign Success Criteria Assessment

| Criteria | Campaign 2 Status | Notes |
|----------|-------------------|-------|
| Lifecycle reaches COMPLETED deterministically | **PASS** | All 3 audits reached `lifecycle_state=COMPLETED` — full DRAFT→SCHEDULED→RUNNING→FINALIZING→COMPLETED progression confirmed |
| Aggregation executes successfully | **FAILED** | `AggregationJob.status=FAILED` on all 3 audits |
| Aggregation artifacts persist | **FAILED** | No `AggregateSetCompletion` marker; no aggregate records written |
| Engineering Retrieval CLI returns deterministic results | **PARTIAL** | CLI operational; all commands connected to DynamoDB without error. Data null/failed because aggregation did not complete |
| Evidence lineage intact | **FAILED** | No lineage manifest written |
| Aggregation reproducibility | **NOT MET** | Cannot test DUPLICATE_COMPLETED path — no aggregation completed |
| Structured logging validated | **NOT MET** | No aggregation log records written |
| Retry behavior validated | **NOT MET** | Lambda failed before any successful write |
| No operational regressions | **PASS** | Unit and integration suite clean at time of campaign (pre-4A.7 TDD additions) |

**Primary failure:** All three audits failed with `failure_category=EVIDENCE_TRANSFORMING`, `reason_code=LINEAGE_MANIFEST_TOO_LARGE`.

---

## 4. Root Cause

`lineage_manifest_v1` embeds all raw-result refs for a manifest scope (audit-wide + per-endpoint) in a single DynamoDB item. The `MAX_MANIFEST_BYTES = 300,000` ceiling is reached at approximately 670–700 refs/scope (using typical field lengths) or as low as 275 refs/scope at worst-case identifier field lengths.

Campaign 2's ~955 refs/audit exceeded this ceiling for the first time in any live execution.

This was not a new defect. The fail-closed behavior (`LINEAGE_MANIFEST_TOO_LARGE`) was explicitly pre-approved in the original ADR (`adr_phase_4_evidence_lineage_aggregation.md`) as MVP behavior, with chunking/S3 manifest deferred to "a separately reviewed chunking/S3 manifest design." Campaign 2 was the first live volume to cross the ceiling.

See full root cause analysis: `docs/bugs/phase4a7_lineage_manifest_scalability_blocker.md`

---

## 5. Action Taken

Following Campaign 2's failures:

1. Issue #36 comment posted: reframed the blocker from `Aggregation Envelope Blocker` (resolved by PR #41) to `Lineage Manifest Scalability Blocker` (open).
2. ADR `docs/architecture/adr_phase_4a_lineage_manifest_pagination.md` — Status: Accepted (2026-06-24, HITL-approved).
3. Technical design `docs/architecture/phase_4a_lineage_manifest_pagination_technical_design.md` — HITL-approved with Phase 4A operational boundary clarification.
4. PR #45 (`bugfix/phase4a7-lineage-manifest-pagination`) implemented `lineage_manifest_v2`, merged 2026-06-24.

Campaign 3 (2026-06-29) validated the fix at Campaign 2 scale — all three audits passed.

---

## 6. Campaign 2 Result

**Overall campaign result: FAILED — Phase 4A.7 closure requirements not satisfied**

Campaign 2 confirmed:
- Audit lifecycle (DRAFT → COMPLETED) is deterministic and working correctly at production volume
- Aggregation Lambda is deployed and responding
- `lineage_manifest_v1` is the sole blocker at this execution scale

The Campaign 2 failure is fully attributed to a known, pre-approved MVP design limitation, not to a code defect introduced in Phase 4A. The fix (PR #45) was validated by Campaign 3.
