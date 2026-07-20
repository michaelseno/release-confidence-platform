# Implementation Report

## 1. Summary of Changes

Implemented the `evidence_retention/` package's foundational layer for
Workstream A1.1 (GitHub Issue #93): three Pydantic data models (`LegalHold`,
`LegalHoldEvent`, `DisposalRecord`) matching Technical Design Section 7.1–7.3
field-for-field, and two DynamoDB repositories (`HoldRepository`,
`DisposalRepository`) each guarded by a namespace-exclusive SK-write
assertion (`_assert_retention_sk`, `_assert_disposal_sk`) modeled directly on
`_assert_phase7_sk` in `audit_platform_integrity/repository.py:49`. No
infrastructure, service orchestration, CLI, Lambda, or cross-cutting
write-path change was made — all explicitly out of scope for this subphase.

## 2. Files Modified

All new files; no existing file was modified.

- `src/release_confidence_platform/evidence_retention/__init__.py` — empty,
  mirroring `audit_platform_integrity/__init__.py`.
- `src/release_confidence_platform/evidence_retention/constants.py` — record
  type literals, ID prefixes, bounded value sets (`HOLD_STATUSES`,
  `HOLD_ACTIONS`, `EVIDENCE_CLASSES`, `DISPOSAL_MECHANISMS`), S3 legal-hold
  tag key/value constants, and the two SK-namespace markers
  (`LEGALHOLD_SK_MARKER`, `DISPOSAL_SK_MARKER`).
- `src/release_confidence_platform/evidence_retention/identity.py` —
  `generate_hold_id()`, `generate_disposal_id()` (uuid4 hex, `hold_`/`disp_`
  prefixes), mirroring `audit_platform_integrity/identity.py`.
- `src/release_confidence_platform/evidence_retention/models.py` —
  `LegalHold`, `LegalHoldEvent`, `DisposalRecord` Pydantic models with
  `to_dict()`.
- `src/release_confidence_platform/evidence_retention/hold_repository.py` —
  `HoldRepository` + `_assert_retention_sk()`.
- `src/release_confidence_platform/evidence_retention/disposal_repository.py`
  — `DisposalRepository` + `_assert_disposal_sk()`.
- `tests/unit/evidence_retention/__init__.py`, `test_models.py`,
  `test_hold_repository.py`, `test_disposal_repository.py` — new test suite.

## 3. API Contract Implementation

No API contract changes. This subphase introduces no CLI commands, HTTP
endpoints, or Lambda handlers.

## 4. Data / Persistence Implementation

Three new DynamoDB record types, additive-only (no existing table or record
shape changed):

- **`LegalHold`** (current-state) — PK `CLIENT#{client_id}`, SK
  `AUDIT#{audit_id}#LEGALHOLD`. Fields exactly per Technical Design Section
  7.1: `record_type="legal_hold"`, `client_id`, `audit_id`, `status`
  (`ACTIVE`|`RELEASED`), `hold_id`, `placed_at`, `placed_by`, `reason`,
  `released_at`/`released_by` (optional, required together when
  `status=RELEASED`), `hold_count` (>=1).
- **`LegalHoldEvent`** (immutable log) — PK `CLIENT#{client_id}`, SK
  `AUDIT#{audit_id}#LEGALHOLD#{hold_id}`. Fields per Section 7.2:
  `record_type="legal_hold_event"`, `hold_id`, `client_id`, `audit_id`,
  `action` (`PLACE`|`RELEASE`), `actor`, `reason`, `timestamp`,
  `s3_versions_retagged_count`, `dynamodb_items_updated_count` (both >=0).
- **`DisposalRecord`** — PK `CLIENT#{client_id}`, SK
  `AUDIT#{audit_id}#DISPOSAL#{disposal_id}`. Fields per Section 7.3:
  `record_type="disposal_record"`, `disposal_id`, `client_id`, `audit_id`,
  `evidence_class` (bounded set of 6), `disposal_mechanism` (bounded set of
  3), `disposed_identity_ref`, `disposed_at`, `recorded_at`,
  `source_created_at`/`custody_period_days_applied` (optional). **Never
  carries `ttl_disposal_at`** — enforced structurally: `put_disposal_record()`
  constructs no such key, verified by
  `test_put_disposal_record_calls_put_once`'s explicit
  `assert "ttl_disposal_at" not in item`.

Repository write behavior:

- `HoldRepository.write_hold_event()` — conditional `PutItem`
  (`attribute_not_exists(PK) AND attribute_not_exists(SK)`), matching the
  `_put_once` convention in `audit_platform_integrity/repository.py` and
  `deterministic_reporting/repository.py`. Raises `ConditionalWriteError` on
  duplicate `hold_id`.
- `HoldRepository.upsert_hold()` — unconditional `PutItem` (overwrite),
  matching `CertificationRepository.write_cert_metadata_complete()`'s
  precedent for a single current-state record per identity.
- `HoldRepository.get_legal_hold()` / `get_legal_hold_event()` — plain
  `GetItem` reads.
- `DisposalRepository.put_disposal_record()` — conditional `PutItem`
  (same `_put_once` pattern), making at-least-once event redelivery
  idempotent per Technical Design Section 13.
- `DisposalRepository.get_disposal_record()` — plain `GetItem` read.

Both repositories use the existing low-level DynamoDB client + codec pattern
(`storage/dynamodb_codec.py`'s `encode_dynamodb_call_kwargs` /
`decode_dynamodb_response` / `storage_error_from_dynamodb_client_error`),
identical in structure to `CertificationRepository`/`ReportRepository`.

## 5. Key Logic Implemented

**`_assert_retention_sk(sk)`** (in `hold_repository.py`): raises
`AssertionError` unless `sk` contains `LEGALHOLD_SK_MARKER` (`"#LEGALHOLD"`)
and does not contain `DISPOSAL_SK_MARKER` (`"#DISPOSAL"`). Called before every
write in `HoldRepository`.

**`_assert_disposal_sk(sk)`** (in `disposal_repository.py`): the symmetric
guard — raises unless `sk` contains `"#DISPOSAL"` and does not contain
`"#LEGALHOLD"`. Called before every write in `DisposalRepository`.

The two markers are deliberately defined **without** a trailing `#`
(`"#LEGALHOLD"` / `"#DISPOSAL"`, not `"#LEGALHOLD#"` / `"#DISPOSAL#"`). The
`LegalHold` current-state record's SK terminates exactly at
`...#LEGALHOLD` with no further segment, so a trailing-`#` marker would fail
to match it, while `LegalHoldEvent`'s SK continues as
`...#LEGALHOLD#{hold_id}`. The marker as defined matches both shapes as a
substring. This is documented in `constants.py` and exercised directly by
`test_assert_retention_sk_accepts_legal_hold_current_state_sk` (no trailing
segment) and `test_assert_retention_sk_accepts_legal_hold_event_sk` (with
trailing segment).

## 6. Security / Authorization Implemented

- No new attack surface — no CLI, no network-facing code in this subphase.
- SK-write guards are the code-level enforcement of ADR Non-Negotiable
  Invariant 6, verified by negative tests in both directions (a
  `#DISPOSAL`-shaped key is rejected by `_assert_retention_sk`, and a
  `#LEGALHOLD`-shaped key — both the current-state and event-log shapes —
  is rejected by `_assert_disposal_sk`).
- `sanitize()` is never called on any persistence-bound dict in either
  repository, consistent with the sanitization-boundary ADR referenced in
  Technical Design Section 12 and the established convention in
  `audit_platform_integrity/repository.py` / `deterministic_reporting/repository.py`
  (verified: neither reference file calls `sanitize()` either).
- No secrets, tokens, or PII are introduced by any model field.

## 7. Error Handling Implemented

- `AssertionError` from both SK guards — programming-error guard, not
  user-facing validation (matches Phase 6/7 convention exactly).
- `ConditionalWriteError` (a `StorageError` subclass) on duplicate write
  attempts for both `LegalHoldEvent` and `DisposalRecord` (write-once
  records), defined locally in each repository module — mirroring the
  duplicated-per-module `ConditionalWriteError` definition already present
  in `audit_platform_integrity/repository.py` and
  `deterministic_reporting/repository.py` (not a new shared exception type).
- All other DynamoDB client/request failures are translated via the existing
  `storage_error_from_dynamodb_client_error` / `_request_error` helpers,
  identical to the two reference repositories.
- Pydantic `ValidationError` on any out-of-bounds field value (unknown
  `status`/`action`/`evidence_class`/`disposal_mechanism`/`record_type`,
  negative counts, `hold_count < 1`, `recorded_at` before `disposed_at`,
  `released_at`/`released_by` missing when `status=RELEASED`).

## 8. Observability / Logging

No structured logging is added in this subphase — neither reference
repository (`CertificationRepository`, `ReportRepository`) performs logging
directly; the surrounding service/engine layer is where structured log
events are emitted in this codebase's existing convention. `RetentionService`
(A1.2/A1.3, out of scope here) is the appropriate place for the
`place_legal_hold`/`release_legal_hold` structured log events Technical
Design Section 13 calls for.

## 9. Assumptions Made

1. **SK-marker/tag-constant file placement (resolved, not escalated).**
   Technical Design Section 6's component table attributes "tag key/value
   constants" and "SK-namespace constants" to `identity.py`, while Section
   11's file-structure listing attributes "evidence_class values, tag keys,
   ID prefixes, SK-namespace markers" to `constants.py`. I followed Section
   11 (the more specific, authoritative file-content listing) and put all of
   these in `constants.py`, keeping `identity.py` limited to the two ID
   generator functions — this also matches the existing
   `audit_platform_integrity` split (`constants.py` holds constants,
   `identity.py` holds generator functions that import from it).

2. **`HoldRepository` scope narrowed relative to Technical Design Section 6's
   full component description (flagged, not silently resolved).** Section 6
   states `HoldRepository`'s responsibility includes "S3
   `ListObjectVersions`/`PutObjectTagging`/`GetObjectTagging` for hold
   re-tagging" and (via the Section 10.4 sequence diagram) implies a
   cross-cutting DynamoDB `Query` + per-item `UpdateItem REMOVE
   ttl_disposal_at` across *every* item under an audit identity's partition
   — which necessarily includes items whose SK belongs to other phases
   (`RunMetadata`, `ReportMetadata`, etc.), not `#LEGALHOLD`-shaped SKs. The
   explicit dispatch brief for this subphase, however, describes
   `HoldRepository` as reading/writing **only** the `#LEGALHOLD#` namespace,
   guarded to raise on "any other namespace." Implementing the S3 tagging
   sweep or the cross-cutting TTL-removal query *inside* `HoldRepository`
   would either bypass `_assert_retention_sk()` entirely for those calls or
   require weakening the guard to accept arbitrary SKs — either of which
   defeats the guard's purpose and contradicts the dispatch brief's explicit
   framing. I resolved this by scoping `HoldRepository` strictly to
   `LegalHold`/`LegalHoldEvent` CRUD (as the dispatch brief describes) and
   documenting in the module docstring that the cross-cutting sweep
   operations are deferred to whichever later subphase implements
   `RetentionService`, which will need a separate, differently-scoped access
   path (not through `HoldRepository`'s guarded methods) for those two
   operations. **This should be explicitly confirmed by the architect before
   A1.2/A1.3 design proceeds**, since it means `RetentionService`'s eventual
   dependency graph is not "uses `HoldRepository` only" for 100% of its
   described responsibilities — only for the `LegalHold`/`LegalHoldEvent`
   part of them.

3. **`upsert_hold()` write semantics.** Technical Design Section 7.1 says
   `LegalHold` is "written on first placement via conditional put; updated on
   every subsequent place/release cycle." I implemented a single
   unconditional `PutItem`-based `upsert_hold()` method for both the first
   and subsequent writes (matching `CertificationRepository.
  write_cert_metadata_complete()`'s precedent — "PutItem overwrites any
  existing record" — for the platform's other single-current-record-per-
  identity type), rather than adding conditional-vs-unconditional branching
  inside the repository. The "first write should be conditional" nuance is a
  business-logic/race-avoidance concern for the calling `RetentionService`
  (which will read `get_legal_hold()` first to decide create-vs-update
  semantics and compute `hold_count`), not something this repository method
  needs to branch on internally. This is a low-risk implementation
  simplification, not a change to any field, type, or externally observable
  contract.

4. **`recorded_at >= disposed_at` model-level validation.** Technical Design
   Section 7.3 states `recorded_at` is "always ≥ `disposed_at`, may lag by
   the eventual-consistency window." I added this as a `model_validator` on
   `DisposalRecord` (parsing both as ISO-8601 and comparing chronologically,
   not lexically) since it is a stated invariant of the record shape, similar
   in spirit to the `checks_passed <= checks_performed` validator already
   present in `audit_platform_integrity/models.py`. This is a data-integrity
   check, not a new business rule — it rejects only physically-impossible
   record construction (recording awareness of a disposal before AWS's own
   reported deletion timestamp).

No assumption above affects external behavior, security, billing, or API
contracts — items 1, 3, and 4 are implementation-detail choices consistent
with existing codebase precedent; item 2 is a scope boundary explicitly
flagged for confirmation rather than silently narrowed.

## 10. Validation Performed

New test suite (60 tests, all passing):

```
$ uv run pytest tests/unit/evidence_retention/ -v
============================= test session starts ==============================
platform darwin -- Python 3.11.11, pytest-8.4.2, pluggy-1.6.0
...
collected 60 items
... (60 individual PASSED lines) ...
============================== 60 passed in 0.59s ==============================
```

Full existing suite (no regression):

```
$ uv run pytest --ignore=tests/unit/deterministic_reporting/test_formatters_pdf.py -q
........................................................................ [  4%]
... (1459 total) ...
1459 passed in 1.89s
```

Note: `tests/unit/deterministic_reporting/test_formatters_pdf.py` fails to
*collect* in this environment with `ModuleNotFoundError: No module named
'fpdf'` — this is a pre-existing local `.venv` gap (the optional `fpdf2`
dependency declared in `pyproject.toml` is not installed in this checkout's
virtualenv) and is unrelated to this change: the module imports
`deterministic_reporting/formatters/pdf.py`, which this dispatch never
touched. Confirmed by inspection that the import chain has no path through
`evidence_retention/`. Full run including that file:

```
$ uv run pytest -q
... ERROR collecting tests/unit/deterministic_reporting/test_formatters_pdf.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

Lint:

```
$ uv run ruff check src/release_confidence_platform/evidence_retention/ tests/unit/evidence_retention/
All checks passed!
```

`ruff format --check` reports 4 of the 6 new `src/` files "would be
reformatted" (collapsing some multi-line `raise ValueError(...)` blocks to
single lines). This is not a regression specific to this change: running the
same check against the reference files this package's style was modeled on
(`audit_platform_integrity/repository.py`, `.../models.py`) shows the
identical pre-existing drift in this checkout — both reference files also
"would be reformatted" by the same command. I preserved the existing
multi-line `raise` style (matching the files I was told to mirror precisely)
rather than auto-reformatting, since doing so would make the new files
diverge stylistically from the exact pattern they were modeled on. Flagging
this for the orchestrator/QA rather than silently resolving it either way.

## 11. Known Limitations / Follow-Ups

- `HoldRepository` does not (and per Assumption 2 above, should not without
  further architectural confirmation) implement the S3 object-version
  tagging methods or the cross-cutting DynamoDB TTL-removal query that
  Technical Design Section 6 attributes to it — these require a separate,
  less-restricted access path and belong to whichever subphase implements
  `RetentionService`.
- No `RetentionService`, CLI, Lambda handler, or infra change exists yet —
  by design, per this dispatch's explicit scope.
- The custody-period duration remains fully unset anywhere in this codebase,
  per AC-A1-5 — no test or fixture in this subphase assumes or hardcodes a
  duration value.
- `ruff format --check` drift noted in Section 10 is pre-existing repo-wide
  and not introduced by this change; not treated as a blocking issue but
  flagged for awareness.

## 12. Commit Status

Not committed. Per the dispatch instructions, the working tree is left as-is
for human/QA review before commit.
