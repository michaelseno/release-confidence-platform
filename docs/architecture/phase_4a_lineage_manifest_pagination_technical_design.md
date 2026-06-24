# Technical Design: Phase 4A Lineage Manifest Pagination

## Purpose

Defines the implementation-ready detail required by `docs/architecture/adr_phase_4a_lineage_manifest_pagination.md` (Accepted) before any code may change: exact page-size constant, conditional-put retry/resume protocol, `manifest_hash` canonicalization rules, v1/v2 reader compatibility behavior, and the validation test plan. This document does not authorize implementation by itself — it is the gate the ADR named; once it is reviewed alongside the ADR, implementation may proceed on a dedicated branch.

## 0. Phase 4A Operational Boundary (HITL clarification, 2026-06-24)

Explicit restatement, scoped to this technical design, of the boundary already decided in the ADR:

- `MAX_AUDIT_WINDOW_HOURS` remains 48. Not changed by this design.
- **Evidence collection must stop at exactly the 48-hour boundary.** No new audit executions (baseline, burst, or repeated occurrence schedules) may start after the 48-hour boundary. This is enforced today by construction — `audit_scheduling/builders.py` computes all occurrence schedules within the audit window — and nothing in this design touches that path.
- A separate processing/finalization grace period may exist, proposed at 2 hours. **Aggregation, lineage page generation, artifact persistence, retrieval materialization, and cleanup may continue during that grace period.** This is exactly the work this design changes: the page-writing phase (Section 4) and header/transaction write may take longer than today's single-shot write, and that additional time is expected to fit inside this grace period, not the audit window itself.
- **The grace period does not redefine the audit as a 50-hour audit.** The audit's `audit_window` (`start_time`/`end_time`), `lifecycle_state` semantics, and evidence-collection cutoff are unchanged at exactly 48 hours. The grace period is a backend processing allowance for everything that happens *after* evidence collection ends — it has no effect on scheduling, occurrence counts, or what counts as in-window evidence. Nothing in this design adds a field, schedule, or code path that treats the grace period as part of the audit window.

This section exists so that anyone implementing or reviewing this design has the same explicit boundary in front of them as the ADR, without needing to cross-reference back to it.

## 1. Page-size constant

### Correction to the ADR's illustrative value

The ADR's "400 refs/page, illustrative" starting point was sized against *representative* field lengths (UUIDs, typical S3 keys). It is not safe against the lengths the platform actually *permits*. Recomputing with worst-case enforced identifier lengths:

| Field | Enforced max | Source |
|---|---|---|
| `client_id`, `audit_id`, `run_id` | 128 chars | `IDENTIFIER_PATTERN = r"^[A-Za-z0-9_.-]{1,128}$"` (`core/validators.py:13`) |
| `endpoint_id` | 128 chars | `MAX_ENDPOINT_ID_LENGTH = 128` (`aggregation/constants.py:64`) |
| `s3_version_id` | No documented hard max (AWS-opaque) | Conservative assumption: 200 chars, pending empirical confirmation from live S3 version IDs |
| `raw_result_s3_key` (derived) | `len("raw-results/") + 128 + 1 + 128 + 1 + 128 + len("/results.json")` = 411 chars worst case | `RAW_RESULT_KEY_TEMPLATE` (`core/constants/engine.py:42`) |

A worst-case page item (all identifiers at max length, `manifest_scope="endpoint:{128-char-id}"`, page-level fields included) was measured by binary search:

```
275 refs  → 299,448 bytes  (under cap)
276 refs  → 300,533 bytes  (over MAX_MANIFEST_BYTES=300,000)
```

**Worst-case ceiling: 275 refs/page.** (Computed against every identifier field — client_id, audit_id, run_id, endpoint_id, audit_execution_id, config_version, aggregation_job_id — at its IDENTIFIER_PATTERN-enforced 128-char max, not just the raw-result fields.) The ADR's illustrative 400 would have failed in the worst case — this is exactly the kind of error a fixed, byte-validated constant must avoid, since page size cannot be allowed to depend on which client/audit/run/endpoint happens to be in play.

### Decision

**`LINEAGE_PAGE_SIZE = 200`** (fixed ref count per page, not byte-packed).

Rationale: 200 is ~73% of the worst-case 275-ref ceiling, leaving comfortable margin for (a) the `s3_version_id` length assumption being wrong in either direction, (b) minor future field additions to the ref schema, and (c) JSON encoding overhead variance. In realistic conditions (UUID-length run/version ids, typical client/audit naming), actual page bytes will be far below this — the constant is sized for the worst case the platform *allows*, not the case it *typically* sees.

**Action item before this constant is finalized for production:** confirm real observed `s3_version_id` length from live campaign data (Campaign 2's S3 bucket) and re-run the worst-case calculation if materially different from the 200-char assumption. If real version IDs are shorter, 200 remains valid with even more margin; if a live value is found longer than assumed, recompute the ceiling before relying on `LINEAGE_PAGE_SIZE = 200`.

A new constant `MAX_MANIFEST_PAGE_REF_COUNT = 275` (the validated worst-case ceiling) should also be added and asserted against in a unit test, so any future change to ref schema fields or identifier length limits that shifts the worst case is caught by a failing test rather than discovered in production.

## 2. Page schema

Header (replaces today's `lineage_manifest_v1` record at the same SK):

```json
{
  "PK": "CLIENT#{client_id}",
  "SK": "AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#LINEAGE#{manifest_scope}",
  "record_kind": "lineage_manifest",
  "manifest_version": "lineage_manifest_v2",
  "manifest_scope": "audit | endpoint:{endpoint_id}",
  "client_id": "...", "audit_id": "...", "audit_execution_id": "...",
  "config_version": "...", "aggregation_version": "agg_v1", "aggregation_job_id": "...",
  "created_at": "<UTC ISO-8601>",
  "source_ref_count": 955,
  "lineage_page_count": 5,
  "page_size": 200,
  "manifest_hash": "<sha256 hex>"
}
```

Page (new child item, one per page, immutable):

```json
{
  "PK": "CLIENT#{client_id}",
  "SK": "AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#LINEAGE#{manifest_scope}#PAGE#{page_index}",
  "record_kind": "lineage_manifest_page",
  "manifest_version": "lineage_manifest_v2",
  "manifest_scope": "audit | endpoint:{endpoint_id}",
  "client_id": "...", "audit_id": "...", "audit_execution_id": "...",
  "config_version": "...", "aggregation_version": "agg_v1", "aggregation_job_id": "...",
  "created_at": "<UTC ISO-8601, same as header>",
  "page_index": 0,
  "page_ref_count": 200,
  "page_hash": "<sha256 hex>",
  "source_raw_result_refs": [ /* up to LINEAGE_PAGE_SIZE refs, same item schema as v1 */ ]
}
```

`page_index` is zero-based, assigned by slicing the existing canonical sort (`sorted(records, key=lambda r: r.ref_identity)`, unchanged) into fixed-size `LINEAGE_PAGE_SIZE` chunks in order. The last page may have fewer than `LINEAGE_PAGE_SIZE` refs. This guarantees: identical raw evidence → identical sort → identical page boundaries → identical page contents, regardless of input ordering or retry.

## 3. `manifest_hash` canonicalization rules

Two-level hash, both computed with `json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")` then SHA-256 — i.e., the existing `canonical_json_hash()` (`lineage.py:13-15`) is reused unchanged, just applied at two levels instead of one:

1. **`page_hash`** = `canonical_json_hash(hashable)`, where `hashable` is the page's evidence-derived fields only: `manifest_version, record_kind, manifest_scope, client_id, audit_id, audit_execution_id, config_version, aggregation_version, page_index, page_ref_count, source_raw_result_refs`. **`aggregation_job_id` and `created_at` are deliberately excluded** — they are still persisted as fields on the page item (for write-attempt traceability), but excluded from the hash input.
2. **`manifest_hash`** (header-level) = `canonical_json_hash({**hashable, "page_hashes": [page_hash for page_index in 0..lineage_page_count-1, in order]})`, where header `hashable` similarly excludes `aggregation_job_id`/`created_at`.

**Why the exclusion (found during implementation, not anticipated in the original draft of this section):** the retry/resume protocol in §4 detects "this page already exists from a prior attempt" by comparing the freshly-recomputed `page_hash` against the persisted one. `aggregation_job_id` and `created_at` are attempt-specific — a retry uses a new `job_id` and a new wall-clock timestamp even though the underlying raw evidence is identical. If those fields were included in the hash, *every* retry would produce a different hash than the original attempt, so the resume comparison would always report a mismatch — the protocol would never be able to resume, only ever fail closed on retry. Excluding them makes both `page_hash` and `manifest_hash` pure functions of the raw evidence: identical evidence → identical hash, regardless of which attempt or timestamp produced it. Pinned by `test_build_manifest_page_hash_stable_across_different_job_id_and_timestamp` and `test_build_manifest_header_v2_hash_stable_across_different_job_id_and_timestamp` in `tests/unit/aggregation/test_lineage_pagination.py`.

This makes `manifest_hash` a function of the header's own bounded fields plus the *ordered* sequence of every page's hash. Full verification chain for any consumer: `header.manifest_hash` → recompute from header fields + claimed `page_hashes` list → fetch each page by `page_index` → recompute each `page_hash` from that page's own content → compare. This is a flat ordered hash-of-hashes (sufficient here; no need for a full Merkle tree since partial/logarithmic proofs are not a requirement — full reconstruction is the only verification mode this platform needs, consistent with "Raw evidence is the source of truth" / no partial-trust consumption model).

`source_raw_result_refs` ordering within a page, and page ordering within a scope, are both already-deterministic (`ref_identity` sort, unchanged) — no new ordering logic is introduced, only a partition of the existing order into fixed-size pages.

## 4. Conditional-put retry/resume protocol

Reuses the existing write-once idiom already in `aggregation/repository.py:172-183` (`_put_once`, `ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)"`, raising `ConditionalWriteError` on conflict).

For each manifest scope (`audit`, then each `endpoint:{endpoint_id}` in sorted order — matching today's iteration order in `orchestrator.py:503`):

1. Compute the full deterministic page set for that scope (in memory; same `_load_records` → sort → slice pipeline as today, just sliced into `LINEAGE_PAGE_SIZE` chunks instead of one block).
2. For `page_index` in `0..lineage_page_count-1`: attempt `_put_once(page_item)`.
   - **Success:** continue to next page.
   - **`ConditionalWriteError` (item already exists):** fetch the existing item by key, recompute this page's content/hash from the current in-memory record set, and compare `page_hash`. If equal → treat as already-written by a prior attempt, continue (this is the resume path). If **not equal** → raise a new evidence-producing failure (`LINEAGE_PAGE_HASH_MISMATCH`, added to `EVIDENCE_PRODUCING_REASON_CODES`) — this should only happen if raw evidence changed between attempts, which must never happen given raw-evidence immutability, so this is an integrity violation, not a retry, and must fail closed rather than overwrite.
3. Once all pages for all scopes are confirmed written (freshly or from a prior attempt), proceed to the existing single `transact_write_items` call — unchanged in shape except that it now writes bounded headers instead of full v1 manifests.

This makes page-writing idempotent and resumable across Lambda retries/timeouts without a new queue, lock, or coordination mechanism — consistent with this codebase's existing pattern of using conditional writes for idempotency (e.g. `put_job_once`, `put_audit_execution_identity_once`) rather than introducing new infrastructure (mirrors the original ADR's rejected-alternative reasoning for not adding a new DLQ/queue).

**Residual risk, not solved by this design:** if a job fails after writing some pages but is never retried (e.g., operator abandons it), those pages remain as orphaned-but-harmless immutable items (never referenced by a header, since the header is only written in the final transaction). This is acceptable — it matches today's behavior where a failed job leaves no aggregate/manifest records at all; orphaned pages are inert until a successful retry reattaches them via a byte-identical recomputation, or they simply age out as part of normal data lifecycle (no special cleanup is in scope for this design).

## 5. v1/v2 reader compatibility

Add a single reader entry point, `read_lineage_manifest(repository, pk, sk)`, used by every current and future lineage consumer (retrieval service, future Phase 5 consumer contract), so version-branching logic lives in exactly one place:

```python
def read_lineage_manifest(repository, pk, sk):
    item = repository.get_item(pk, sk)
    if item is None:
        return None
    version = item.get("manifest_version")
    if version == "lineage_manifest_v1":
        return LineageManifestView(header=item, refs=tuple(item["source_raw_result_refs"]))
    if version == "lineage_manifest_v2":
        return LineageManifestView(header=item, refs=None, load_refs=lambda: _load_v2_pages(repository, pk, sk, item["lineage_page_count"]))
    raise ValidationError("Unknown manifest version", "UNSUPPORTED_MANIFEST_VERSION")
```

- `v1` records are read exactly as today — no migration, no rewrite, fully backward compatible, consistent with "no migration of existing v1 records."
- `v2` records: the header alone is sufficient for any consumer that only needs `source_ref_count` / `lineage_page_count` / `manifest_hash` (e.g., the existing `aggregation-lineage` CLI summary). Consumers that need the actual ref list (e.g., `get_evidence_references`) call `load_refs()`, which queries pages by `SK` prefix (`begins_with`, reusing the existing `_query_begins` pagination idiom already in `retrieval/repository.py`) and concatenates in `page_index` order.
- This reader is the only place that needs to know both versions exist. `retrieval/service.py` and any future Phase 5 consumer call `read_lineage_manifest()` and never branch on version themselves.
- **Explicitly not addressed here (per ADR, mandatory Phase 5 follow-up):** `load_refs()` returning a fully concatenated, unbounded list is itself the same unbounded-output risk flagged in the broader scaling review. This design only makes the *existence* of multi-page lineage retrievable; it does not add a pagination contract for *consumers* of `load_refs()`. That remains the separately-tracked retrieval-pagination decision required before Phase 5.

## 6. Diagnostic enrichment (ADR Decision item 6)

`_fail_if_too_large()` (`orchestrator.py:822-824`) gains a `context: dict[str, Any]` parameter:

```python
def _fail_if_too_large(item, max_bytes, reason, *, context):
    size = len(json.dumps(item, sort_keys=True, default=str).encode("utf-8"))
    if size > max_bytes:
        raise ValidationError("Aggregation item too large", reason, context={**context, "estimated_size_bytes": size, "max_bytes": max_bytes})
```

Call sites pass `context={"manifest_scope": manifest["manifest_scope"], "source_ref_count": manifest["source_ref_count"], "page_size": LINEAGE_PAGE_SIZE}`. The generic failure handler (`orchestrator.py:352-369`) merges `getattr(exc, "context", {})` into both `error_summary` (persisted) and the `aggregation_job_failed` structured log event (`orchestrator.py:371-385`) — satisfying the ADR's requirement to distinguish audit-wide growth from endpoint-scoped growth without a live debugging session.

## 7. Validation test plan

| Test | Asserts |
|---|---|
| Page partition correctness | Synthetic 955-ref record set (matching Campaign 2) → exactly `ceil(955/200) = 5` pages; last page has 155 refs; union of all page refs equals the original set exactly, no duplicates, no omissions. |
| Determinism under input reordering | Same 955-ref set fed in two different (shuffled) input orders → byte-identical header JSON and byte-identical per-page JSON (excluding nothing — full byte identity). |
| Worst-case size regression guard | Page built with all identifiers at 128-char max and a 200-char `s3_version_id`, at `LINEAGE_PAGE_SIZE=200` refs → asserts resulting item size stays under `MAX_MANIFEST_BYTES`; also assert `MAX_MANIFEST_PAGE_REF_COUNT` (275) is the documented ceiling so a future field addition that shifts it fails this test rather than failing silently in production. |
| Retry/idempotency, no duplication | Simulate failure after 2 of 5 pages written; retry; assert final state has exactly 5 pages, all `page_hash` values match fresh recomputation, completion marker written exactly once. |
| Integrity violation on mismatch | Forge an existing page item with a `page_hash` that does not match fresh recomputation; assert the orchestrator fails closed with `LINEAGE_PAGE_HASH_MISMATCH` rather than silently accepting or overwriting. |
| v1/v2 reader compatibility | Seed one `lineage_manifest_v1` record and one `lineage_manifest_v2` header+pages set in the same fixture table; assert `read_lineage_manifest()` returns equivalent, correctly-ordered ref lists for both. |
| End-to-end aggregation at Campaign-2 scale | Integration test (extending `tests/integration/test_phase4a4_aggregation_persistence_integration.py` pattern) with 955+ synthetic raw results: aggregation reaches `COMPLETED`, not `FAILED`/`LINEAGE_MANIFEST_TOO_LARGE`; header + correct page count persisted; retrieval reconstructs the full ref list matching input exactly. |
| Diagnostic payload | Force a `LINEAGE_MANIFEST_TOO_LARGE` failure (e.g., temporarily lower `MAX_MANIFEST_BYTES` in test scope) and assert `error_summary` and the structured log event both contain `manifest_scope`, `source_ref_count`, `estimated_size_bytes`, `max_bytes`, `page_size`. |

## Open items for live-data confirmation before production rollout

1. Real observed `s3_version_id` length distribution from Campaign 2's S3 bucket (the 200-char assumption is conservative but unverified against this platform's actual AWS account/region behavior).
2. Real observed `client_id`/`audit_id`/`run_id`/`endpoint_id` length distribution in practice (worst case is 128 chars each by validation rule, but typical naming conventions in this repo's own fixtures/campaigns run far shorter — confirming this doesn't change the constant, since `LINEAGE_PAGE_SIZE=200` is already sized for the worst case, but is useful context for understanding real headroom).

## Traceability

- ADR: `docs/architecture/adr_phase_4a_lineage_manifest_pagination.md`
- Bug report: `docs/bugs/phase4a7_lineage_manifest_scalability_blocker.md`
- Existing conditional-write idiom: `aggregation/repository.py:172-183`
- Existing pagination idiom: `retrieval/repository.py` `_query_begins`
- Existing canonical hash helper: `aggregation/lineage.py:13-15`
