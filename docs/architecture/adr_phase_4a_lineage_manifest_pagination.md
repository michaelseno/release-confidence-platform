# ADR: Phase 4A Lineage Manifest Pagination (Bounded Manifest Header + Immutable Pages)

## Status

Accepted — direction approved by HITL 2026-06-24, with three required clarifications incorporated (Phase 4A audit boundary & processing grace period; lineage-failure diagnostics; retrieval-pagination exclusion strengthened to a mandatory Phase 5 follow-up — see below). This amends, but does not reverse, `docs/architecture/adr_phase_4_evidence_lineage_aggregation.md` (still Accepted): that ADR correctly decided lineage must never be embedded unbounded on aggregate records and must fail-before-write rather than truncate or silently drop references. This ADR is the "separately reviewed chunking/S3 manifest design" that the original ADR explicitly deferred.

**Implementation remains blocked.** Per HITL direction, no implementation may begin until a Technical Design document defines: the exact page-size constant, the conditional-put retry/resume protocol, `manifest_hash` canonicalization rules, v1/v2 reader compatibility behavior, and validation tests for 955+ refs and page-boundary determinism. See `docs/architecture/phase_4a_lineage_manifest_pagination_technical_design.md`.

## Context

Phase 4A.7 live validation (Campaign 2, three parallel 48-hour audits) reached `lifecycle_state=COMPLETED` successfully on all three audits, then failed aggregation on all three with `reason_code=LINEAGE_MANIFEST_TOO_LARGE`. Root cause (see `docs/bugs/phase4a7_lineage_manifest_scalability_blocker.md`):

- `build_manifest()` (`src/release_confidence_platform/aggregation/lineage.py:18-47`) embeds every raw-result source ref for a manifest scope (audit-wide, and separately per endpoint) inline in one dict, persisted as a single DynamoDB item.
- `MAX_MANIFEST_BYTES = 300_000` (`aggregation/constants.py:60`) is a deliberate margin below DynamoDB's 400KB single-item hard limit.
- Computed ceiling: ~670-700 raw-result refs per manifest scope before the cap is exceeded (representative field-length model). Campaign 2 observed 955 refs in one audit-scope manifest — ~42% over the ceiling.
- This was a known, accepted MVP risk, not a regression: `adr_phase_4_evidence_lineage_aggregation.md` explicitly rejected chunking for MVP scope and mandated fail-before-write instead, deferring a chunked/paginated design to separate review. This ADR is that review.
- Per HITL decision (2026-06-24), "7-day campaign" validation means a sequence of chained 48-hour audits, not one continuous window — so the design target is headroom beyond the 48-hour ceiling already observed (955 refs), not an unbounded continuous-audit volume.
- A related, separately-tracked finding from the same investigation's broader scaling review: the retrieval CLI has no pagination/size contract today (`retrieval/commands.py`, `retrieval/service.py:524-551` `get_evidence_references`), so even a bounded write-side manifest could still produce unbounded read-side output. That is explicitly **out of scope** for this ADR (this ADR only changes how lineage is *persisted*, not how it is *retrieved/paginated for consumers*) but is a **mandatory follow-up decision required before Phase 5 consumer-facing evidence retrieval begins** — Phase 5 cannot safely expose `get_evidence_references` or any equivalent lineage-reading path to consumers without an explicit retrieval-side pagination/size contract, regardless of whether the underlying manifest is v1 or v2.

### Phase 4A Audit Boundary & Processing Grace Period (HITL clarification, 2026-06-24)

To remove ambiguity about what scale this redesign must support, the following boundary is now explicit:

- `MAX_AUDIT_WINDOW_HOURS` remains 48 (`audit_scheduling/constants.py:13,20`; hard-enforced in `safeguards.py:117-118,126-127` via `AUDIT_WINDOW_TOO_LONG`). Not raised by this ADR.
- A continuous 7-day single audit is explicitly out of scope for Phase 4A. "7-day campaign" means a sequence of independently-scheduled, chained 48-hour audits, consistent with Issue #36's own closure criteria ("multiple independent 48-hour audit campaigns").
- **New: a 2-hour processing/finalization grace period** is adopted as the architectural target for how long aggregation, lineage manifest construction (including the paginated writes this ADR introduces), and finalization completion are expected to take after an audit window's `end_time`.
- No new evidence collection (baseline, burst, or repeated occurrence schedules) may start after the 48-hour boundary. This is already structurally guaranteed today — `audit_scheduling/builders.py` bounds all occurrence schedules within the audit window — so this clause formalizes existing behavior rather than changing it.
- Aggregation, lineage manifest writes, and finalization completion may continue executing during the grace period.
- **Honesty check against current code:** today, `build_finalization()` (`audit_scheduling/builders.py:269-294`) schedules the finalization trigger to fire at exactly `audit_window["end_time"]`, with no grace buffer, and there is no code-level timeout/SLA enforcing any processing bound afterward. This ADR adopts 2 hours as the architectural target/expectation against which future operational monitoring should be measured — it is a policy decision, not yet an enforced mechanism. Whether/how to enforce it (e.g., an alarm if aggregation hasn't reached `COMPLETED`/`FAILED` within the grace period) is a separate operational-hardening decision, outside this ADR's implementation scope.

## Decision

Replace the single-item, fully-embedded lineage manifest (`lineage_manifest_v1`) with a two-part model for any manifest scope whose ref count exceeds the page size: a small, bounded **manifest header** plus one or more immutable **manifest pages**, introduced as `lineage_manifest_v2`. `lineage_manifest_v1` records already written remain valid and are never migrated (immutable, never mutated, per existing policy).

1. **Manifest header** (replaces the v1 record at the same SK): bounded fields only — `manifest_version` (`lineage_manifest_v2`), `manifest_scope`, `client_id`, `audit_id`, `audit_execution_id`, `config_version`, `aggregation_version`, `aggregation_job_id`, `created_at`, `source_ref_count`, `lineage_page_count`, `page_size`, `manifest_hash`. No `source_raw_result_refs` array on the header. `manifest_hash` is computed deterministically over the canonical header fields plus the ordered list of per-page hashes (not over raw ref content directly) — so an aggregate or completion record can prove the full manifest's integrity via the header alone, without holding every page in memory.

2. **Manifest pages** — new child item per page, immutable, written once:
   ```
   SK: AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#LINEAGE#{manifest_scope}#PAGE#{page_index}
   ```
   Each page holds a deterministic, canonically-ordered slice of `source_raw_result_refs` (same sort key as today — `ref_identity` — so page boundaries are stable and reproducible across re-aggregation of the same evidence), plus `page_index`, `page_ref_count`, `page_hash` (hash of that page's own ref content), and the same scope/identity fields as the header for independent verification.

3. **Fixed page size, not byte-fitted.** Pages are sized by a fixed ref-count constant (recommended starting point: 400 refs/page — comfortably under the ~670-700 byte ceiling computed for this codebase's field lengths, leaving margin for longer S3 keys/endpoint ids than the representative model used). A fixed count (rather than packing pages to the byte limit) keeps page assignment simple and deterministic. The exact constant is a technical-design-phase decision, tuned against real observed key/id lengths, not finalized by this ADR.

4. **Two-phase write, not a single larger transaction.** Lineage pages are written via their own idempotent conditional-put step, one page at a time, **before** the aggregate-set transaction. The aggregate-set transaction (`transact_write_items`) only ever writes: the bounded manifest header(s), aggregate records, and the `AggregateSetCompletion` marker — never raw ref arrays. This decouples lineage size from `MAX_AGGREGATE_RECORDS` (100 items/transaction) and `MAX_AGGREGATE_TRANSACTION_BYTES`: page count no longer competes with aggregate/endpoint record count for the same transaction budget. If any page write fails partway, the job fails closed (`EVIDENCE_TRANSFORMING`, retryable) before the aggregate-set transaction is attempted — pages are conditional-put (write-once) so a retry safely resumes without duplicating already-written pages. The exact retry/idempotency reconciliation protocol (how a retried job detects which pages already exist) is a technical-design-phase deliverable, not finalized here.

5. **Evidence integrity unchanged.** No ref is ever sampled, truncated, or dropped. `source_ref_count` continues to be the exact total; `lineage_page_count * page_size >= source_ref_count` is a verifiable invariant. Determinism is preserved: identical raw evidence always produces identical headers, identical page contents, and identical hashes.

6. **Lineage-failure diagnostics (HITL clarification, 2026-06-24).** `_fail_if_too_large()` (`orchestrator.py:822-824`) currently raises `ValidationError("Aggregation item too large", reason)` with no contextual payload, and the generic failure handler (`orchestrator.py:352-369`) persists only `{reason_code, component, aggregation_job_id}` to `error_summary` — today it is impossible to tell from a `LINEAGE_MANIFEST_TOO_LARGE` failure which scope failed or by how much, which blocks distinguishing audit-wide growth from endpoint-concentrated growth. Going forward, any `LINEAGE_MANIFEST_TOO_LARGE` (or future lineage-failure) diagnostic must capture: `manifest_scope` (`audit` or which specific `endpoint:{endpoint_id}`), `source_ref_count`, estimated serialized size at failure time, `MAX_MANIFEST_BYTES`, and `page_size` (once v2's page size is defined). Exact diagnostic payload shape (error_summary fields vs. structured log fields vs. both) is a Technical Design deliverable.

## Alternatives Considered

### Raise `MAX_MANIFEST_BYTES` instead of pagination

Rejected. The cap is a margin below DynamoDB's hard 400KB per-item limit, not an arbitrary policy choice — it cannot be raised meaningfully, only chunked around. Matches the explicit user constraint: "do not simply increase limits without understanding scaling behavior."

### Move the full manifest to a single S3 object

Considered, deferred rather than rejected. An S3-backed manifest would remove the DynamoDB item-size ceiling entirely and was the "separately reviewed S3 manifest design" the original ADR named as an alternative to chunking. Deferred for now because: (a) it introduces a second storage system into the lineage read path, requiring new IAM scoping and a retrieval-side S3 read contract; (b) DynamoDB pagination (this ADR's approach) reuses existing query/pagination patterns already proven elsewhere in this codebase (`retrieval/repository.py`, `storage/audit_metadata_client.py`); (c) it does not obviously simplify the idempotency/retry protocol relative to paginated DynamoDB items. Worth revisiting if page counts grow large enough that per-page DynamoDB write/read volume itself becomes a cost or throughput concern.

### Sample or truncate raw result references when over budget

Rejected outright. Violates the Evidence Principles (raw evidence is the source of truth; no derived conclusion without traceability) and the user's explicit constraint not to "truncate lineage silently" or "drop references." Not seriously considered as a candidate.

### Dynamically pack pages to the exact byte budget instead of a fixed ref count

Rejected for MVP of this redesign. Byte-packing requires serializing-to-measure during the write path (as today's `_fail_if_too_large` already does) and produces page boundaries that shift if field lengths change slightly between runs, complicating reasoning about determinism. A fixed ref-count page size is simpler to reason about and verify; it trades a small amount of page-utilization efficiency for determinism and simplicity, consistent with this project's preference for explainable, auditable behavior over optimization.

### Keep a single audit-wide manifest and drop endpoint-scoped manifests

Rejected. The original ADR (`adr_phase_4_evidence_lineage_aggregation.md`, "Use only an audit-wide lineage manifest for endpoint aggregates") already rejected this for losing exact per-endpoint lineage. Nothing in this investigation changes that reasoning — endpoint-scoped manifests still get the same pagination treatment as the audit-wide manifest.

## Consequences

Benefits:

- Removes the `LINEAGE_MANIFEST_TOO_LARGE` ceiling as a function of DynamoDB single-item size; the new ceiling is governed by page count, not embedded byte size, and pages can scale to arbitrarily large `source_ref_count` within a manifest scope.
- Preserves complete, unsampled, hashable, deterministic lineage — no change to evidence integrity guarantees.
- Decouples lineage size from the aggregate-set transaction's 100-item/3.8MB budget, removing a second, related ceiling that would otherwise still bite as endpoint count or ref count grows.
- Reuses existing DynamoDB query/pagination idioms already present in this codebase rather than introducing new infrastructure.

Costs and risks:

- Increases total write operations per aggregation run (one conditional-put per page, before the main transaction) and total item count per audit in the metadata table.
- Requires a new idempotency/retry reconciliation protocol for partially-written page sets — this is real complexity the original ADR flagged as the reason chunking was rejected for MVP; this ADR accepts that complexity is now necessary, but defers the detailed protocol to technical design.
- `lineage_manifest_v1` and `lineage_manifest_v2` coexist; any reader of lineage records (engineering retrieval, future Phase 5 consumers) must handle both versions. This is consistent with the existing aggregation-versioning policy ("future semantic changes must write a new version rather than updating existing records") but is new surface area for the retrieval layer.
- Does not by itself fix the retrieval-side unbounded-output risk (`get_evidence_references` returning all refs with no pagination) — that remains a separate, tracked follow-up decision.
- Fixed page-size constant will need empirical tuning once real S3 key/endpoint-id/run-id lengths from live campaigns are available; the 400-ref starting point in this ADR is illustrative, not load-tested.

## Traceability

- Bug report / root cause: `docs/bugs/phase4a7_lineage_manifest_scalability_blocker.md`
- Amended ADR (still Accepted, not superseded): `docs/architecture/adr_phase_4_evidence_lineage_aggregation.md`
- Schema (pre-pagination): `docs/architecture/phase_4a_aggregation_schema.md` §3.4 LineageManifest
- Technical design (pre-pagination): `docs/architecture/phase_4_aggregation_layer_technical_design.md`
- Related open issue: GitHub #36 (Phase 4A.7 — Operational Validation Campaign)

## Next Steps (post-approval)

**Gate: implementation may not begin until a Technical Design document defines all five of the following (per HITL direction, 2026-06-24):**

1. Exact page-size constant (this ADR's earlier illustrative 400-ref starting point was not validated against worst-case enforced identifier lengths; see Technical Design for the corrected value).
2. Conditional-put retry/resume protocol for partially-written page sets.
3. `manifest_hash` canonicalization rules (exact serialization the hash is computed over, at both page and header level).
4. v1/v2 reader compatibility behavior for engineering retrieval and future Phase 5 consumers.
5. Validation test plan covering 955+ refs (matching or exceeding Campaign 2's observed volume) and page-boundary determinism.

Status of this deliverable: `docs/architecture/phase_4a_lineage_manifest_pagination_technical_design.md`.

Once the Technical Design satisfies all five, implementation proceeds on a dedicated branch, incrementally, with regression coverage matching the test plan, plus the lineage-failure diagnostic enrichment from Decision item 6. QA validation against a live audit with ref count at or beyond 955 is required before Phase 4A.7 can be reattempted.
