# Bug Report

## 1. Summary

Phase 4A.7 Campaign 2 (three parallel 48-hour live audits) completed full audit lifecycle execution (`DRAFT → SCHEDULED → RUNNING → FINALIZING → COMPLETED`) successfully, but aggregation failed on all three audits with `failure_category=EVIDENCE_TRANSFORMING`, `reason_code=LINEAGE_MANIFEST_TOO_LARGE`.

**This is not a new defect.** It is the architecture's own documented, pre-approved fail-closed MVP behavior, triggered for the first time because live audit volume (191 runs / 955 raw results) crossed a ceiling that `docs/architecture/adr_phase_4_evidence_lineage_aggregation.md` explicitly anticipated and explicitly declined to solve for MVP scope. The prior `INVALID_RAW_RESULT_ENVELOPE` defect (PR #41) is confirmed resolved and is unrelated to this finding.

**Status:** Blocked / architecture-scope blocker (governance routing required — see Section 7)

## 2. Investigation Context

- **Detection source:** Operator-reported live Phase 4A.7 Campaign 2 results (three parallel 48-hour audits against live AWS dev infrastructure). Raw campaign evidence (CLI/DynamoDB output) was reported by the operator in conversation, not independently captured by this investigation — see Section 3 for what is operator-reported vs. independently verified.
- **Affected branch at time of investigation:** `bugfix/phase4a7-failure-summaries-pass-miscount` (unrelated open fix, PR #44, not touched by this investigation)
- **Related GitHub Issue:** #36 (Phase 4A.7 — Operational Validation Campaign)
- **Primary references:**
  - ADR: `docs/architecture/adr_phase_4_evidence_lineage_aggregation.md`
  - Technical design: `docs/architecture/phase_4_aggregation_layer_technical_design.md`
  - Schema: `docs/architecture/phase_4a_aggregation_schema.md`
  - Code: `src/release_confidence_platform/aggregation/lineage.py`, `orchestrator.py`, `constants.py`
  - Campaign 1 report (prior validation cycle): `docs/qa/phase4a7_campaign_01.md`

## 3. Observed Symptoms (as reported by operator, Campaign 2)

All three parallel audits reached `lifecycle_state=COMPLETED`. Example (Audit 2A):

- `source_run_count`: 191
- `source_raw_result_count`: 955
- Execution outcome: 191 `COMPLETED` runs
- Aggregation outcome: `status=FAILED`, `failure_category=EVIDENCE_TRANSFORMING`, `reason_code=LINEAGE_MANIFEST_TOO_LARGE`

This confirms the scheduler, orchestration, execution, raw-result generation, and aggregation-ingestion path are all functioning, and that the `INVALID_RAW_RESULT_ENVELOPE` defect fixed in PR #41 is resolved. The failure occurs later, during lineage manifest construction inside the aggregation transformation step.

## 4. Independently Verified Root Cause

`src/release_confidence_platform/aggregation/lineage.py:18-47` `build_manifest()` embeds **every** raw-result source ref for a manifest scope as one inline JSON array (`source_raw_result_refs`) inside a single dict. `src/release_confidence_platform/aggregation/orchestrator.py:463-537` `_build_persisted_records()` builds one such manifest at audit scope and one more **per endpoint**, and each is size-checked individually:

```
orchestrator.py:475  _fail_if_too_large(manifest, MAX_MANIFEST_BYTES, "LINEAGE_MANIFEST_TOO_LARGE")          # audit-wide
orchestrator.py:516  _fail_if_too_large(endpoint_manifest, MAX_MANIFEST_BYTES, "LINEAGE_MANIFEST_TOO_LARGE")  # per endpoint
```

`MAX_MANIFEST_BYTES = 300_000` (`aggregation/constants.py:60`) — a deliberate margin below DynamoDB's 400KB single-item hard limit, since each manifest is persisted as one DynamoDB item (`orchestrator.py:491-497`: `record_kind: "lineage_manifest", **manifest`).

`git log` confirms this design (`MAX_MANIFEST_BYTES`, the embed-all-refs `build_manifest` shape) has been unchanged since the original Phase 4 implementation commit (`8822752`) — this is original, deliberate MVP design, not a regression introduced by recent work.

### Scale ceiling (computed)

Using representative field lengths (S3 key ≈124 chars, UUID4 `run_id`, S3 version id, ISO-8601 timestamp, `endpoint_id`), each `source_raw_result_refs` entry serializes to ≈443-445 bytes. Binary-searching the byte budget:

| Refs in one manifest scope | Manifest size |
|---|---|
| 191 | ~85,400 bytes |
| 500 | ~222,900 bytes |
| **673** | **~299,900 bytes (at the ceiling)** |
| 700 | ~311,900 bytes (over) |
| 955 (Campaign 2 observed) | ~425,400 bytes (over by ~42%) |

**Approximate ceiling: ~670-700 raw-result refs per manifest scope** (audit-wide, or any single endpoint) before `MAX_MANIFEST_BYTES` is exceeded. This is consistent with Campaign 2's observed failure at 955 refs. If raw results are concentrated on few endpoints, individual endpoint-scope manifests can hit this ceiling even before the audit-wide manifest does.

## 5. ADR Cross-Reference — This Was Anticipated, Not Missed

`docs/architecture/adr_phase_4_evidence_lineage_aggregation.md` (Status: Accepted) already decided this exact tradeoff:

> "Phase 4 will not embed unbounded raw reference arrays on aggregate records... If the manifest or aggregate set would exceed safe MVP item/transaction limits, **aggregation fails before manifest/aggregate/completion-marker writes** unless a separately reviewed chunking/S3 manifest design is approved."

And under "Alternatives Considered → Chunk aggregate persistence in MVP":

> "Rejected for current scope. Chunking requires a complete protocol for manifest chunks, aggregate-set completion markers, partial retry reconciliation, and QA validation. **MVP behavior is fail-before-write when limits would be exceeded.**"

And under "Consequences → Costs and risks":

> "Large audits may fail aggregation until a chunked or S3 manifest design is separately approved."

`docs/architecture/phase_4_aggregation_layer_technical_design.md:788` restates the same: "Manifest size risk: large audits may exceed DynamoDB item/transaction limits; current MVP fails before writes until a chunked/S3 manifest design is separately reviewed," and line 809: "do not add chunking without a new reviewed design."

**Conclusion: Campaign 2 did not find a bug. It triggered the exact, named, pre-approved failure mode the architecture was designed to hit, the first time real audit volume exceeded it.** No evidence integrity was compromised — the system correctly failed closed rather than truncating lineage, silently dropping refs, or writing a partial aggregate set, exactly as the ADR requires.

## 6. Broader Phase 4A Scaling Review

A focused architecture review was conducted across the remaining 5 requested dimensions (scheduler, runner, storage, retrieval, evidence integrity), looking for the same unbounded-embed/unbounded-load pattern elsewhere. Two findings were independently spot-verified against source; the rest are reported as found (file:line cited per finding, not yet independently re-verified beyond the two below).

**Independently verified:**
- `src/release_confidence_platform/audit_scheduling/constants.py:13,20` — `DEFAULT_AUDIT_WINDOW_HOURS = 48`, `MAX_AUDIT_WINDOW_HOURS = 48`. `safeguards.py:117-118,126-127` hard-enforces this: any audit window over 48 hours raises `ValidationError("Audit window exceeds max", "AUDIT_WINDOW_TOO_LONG")`. **A literal single 7-day audit cannot be scheduled today.**
- `src/release_confidence_platform/retrieval/commands.py` — no `limit`/`page`/`paginat` flag exists on any `retrieve` subcommand (confirmed via search, zero matches).

**Reported findings (architecture-reviewer agent), by dimension:**

| Dimension | Top finding | Severity (48h → 7-day) |
|---|---|---|
| Scheduler | 48h `MAX_AUDIT_WINDOW_HOURS` hard cap — documented MVP limit, but means "7-day campaign" cannot be one continuous audit | High (scope-defining) |
| Runner/execution | `aggregation/orchestrator.py:401-444` `_load_records` reads raw evidence from S3 sequentially, one `read_json` per run, no batching/parallelism, inside a 300s Lambda timeout (`infra/serverless.yml:138`) | Medium → High |
| Storage | `storage/audit_metadata_client.py` and `retrieval/repository.py` paginate DynamoDB queries correctly (`LastEvaluatedKey` handled) but the *callers* (orchestrator, retrieval service) accumulate the full result set into memory before any size gate — same downstream effect as the lineage bug. Also: all of one client's audit metadata, occurrence claims, and run records share one DynamoDB partition key (`PK=CLIENT#{client_id}`) regardless of audit duration — not found documented as an accepted tradeoff in any ADR. | Medium |
| Retrieval | No CLI pagination/limit contract; `get_evidence_references` (`retrieval/service.py:524-551`) returns a manifest's `source_refs` 1:1 with no truncation — directly downstream of the same unbounded list that caused the original bug | Medium → High |
| Evidence integrity | Deterministic sort (`aggregation/engine.py:22`) and manifest hashing run on the full in-memory record set *before* the size gate, so CPU/memory cost is paid even for audits that will ultimately fail `LINEAGE_MANIFEST_TOO_LARGE`. Determinism guarantee itself does not degrade with scale — only the cost of producing it does. | Low/Medium |

Full agent report (file:line detail per finding) is preserved in this investigation's session transcript and should be promoted into an ADR-prep document if the user wants to proceed to remediation design.

## 7. Required Follow-Up (Governance Routing)

Per this project's Decision Hierarchy (Product Constitution > ADRs > Architecture Documents > Technical Design > Implementation Convenience), the existing ADR explicitly required a **separately reviewed and approved** chunking/S3 manifest design before any change to the current fail-before-write behavior.

1. **Definitional question — RESOLVED 2026-06-24:** "7-day campaign" is a sequence of chained 48-hour audits. `MAX_AUDIT_WINDOW_HOURS` is not being raised. A 2-hour processing/finalization grace period is adopted as the architectural target for aggregation/lineage/finalization completion after the audit window's `end_time` (policy decision, not yet an enforced mechanism — see ADR).
2. **Lineage manifest scalability design — ADR ACCEPTED 2026-06-24, Technical Design written 2026-06-24.** `docs/architecture/adr_phase_4a_lineage_manifest_pagination.md` (Status: Accepted) and `docs/architecture/phase_4a_lineage_manifest_pagination_technical_design.md` define the bounded-header + immutable-paginated-pages model, `LINEAGE_PAGE_SIZE=200` (worst-case validated), retry/resume protocol, hash canonicalization, v1/v2 reader compatibility, and the validation test plan. **Implementation is still blocked** pending final HITL sign-off on the technical design itself.
3. Whether the raw-evidence loader (`_load_records`) needs batched/parallel S3 reads to stay inside the Lambda timeout at higher volume — still open, not part of the lineage pagination ADR's scope.
4. Whether the engineering retrieval CLI/consumer contract needs an explicit pagination/size contract — still open; the lineage pagination ADR explicitly names this a **mandatory follow-up before Phase 5 consumer-facing evidence retrieval begins**.
5. Whether the single per-client DynamoDB partition key is an accepted MVP tradeoff — still open, no decision made.

**No implementation should proceed on item 2 until the technical design is reviewed/sign-off confirmed; items 3-5 remain undecided and are not blocking the lineage pagination work.**

## 8. Issue #36 Status

Issue #36 (open) is currently framed around "Operational Validation Campaign" success criteria, several of which (aggregation success, lineage intact, reproducibility) cannot be met until Item 2 above is resolved. Recommend reframing the open blocker from "Aggregation Envelope Blocker" (resolved by PR #41) to **"Lineage Manifest Scalability Blocker"** via an issue comment (not a title rewrite, since the title already correctly describes the campaign, not the blocker) — pending explicit confirmation, since posting to GitHub is a shared-visibility action.

Phase 4A.7 — and therefore Phase 4A — cannot close until a fresh long-duration campaign completes with aggregation `status=COMPLETED` and full lineage preservation, which requires Items 1-2 above to be resolved first.
