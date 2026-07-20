# Technical Design

## Evidence Governance Workstream A2 — Report Issuance Governance Enforcement

**Status:** Planning only. No implementation, code change, or PR is authorized by this document.
**Companion ADR:** `docs/architecture/adr_report_issuance_certification_gate.md`
**Companion Product Spec:** `docs/product/evidence_governance_workstream_a_product_spec.md`

---

## 1. Feature Overview

A2 introduces an "issuance" checkpoint — a new enforcement point, distinct from `ReportMetadata.status = COMPLETE`, that a Release Confidence Report's full content cannot be retrieved unless Phase 7 Audit Platform Integrity certification succeeded (`CertificationMetadata.terminal_state = CERTIFIED`, evaluated against the *current* report artifact) or all material limitations have been explicitly, durably disclosed. This closes a confirmed conflict between already-shipped Phase 6/7 behavior and the Product Constitution's own non-negotiable issuance rule, which today is honored entirely through operator discipline.

A2 introduces a new, third ownership domain — **Issuance Governance** — that reads Phase 6 and Phase 7 outputs read-only and writes only to its own new namespace. It does not modify `deterministic_reporting/` (Phase 6) or `audit_platform_integrity/` (Phase 7) internals, and does not touch any non-negotiable invariant in `docs/architecture/adr_phase7_certification_independence.md`.

---

## 2. Product Requirements Summary

| Requirement | Description |
| --- | --- |
| FR-A2-1 | Issuance checkpoint distinct from `ReportMetadata.status = COMPLETE` |
| FR-A2-2 | Requires `CertificationMetadata.terminal_state = CERTIFIED` (for the exact identity tuple) or a recorded explicit disclosure |
| FR-A2-3 | Absence of any `CertificationMetadata` record is treated as non-`CERTIFIED`, never an implicit pass |
| FR-A2-4 | Disclosure must reference `certificate_id`, `terminal_state`, and full `disclosed_failures` |
| FR-A2-5 | Checkpoint evaluates against the current/latest `CertificationMetadata` record; a force re-certification's new record governs |
| FR-A2-6 | Phase 6 completion unaffected; Phase 7 never required to write to any Phase 6 record |
| FR-A2-7 | No event-driven trigger for Phase 7 certification introduced |
| AC-A2-5 | Force re-certification (`--force`) — checkpoint must evaluate against the new record; old certificate artifact preserved |
| AC-A2-7 | Force report regeneration — design must explicitly state whether prior certification still governs |

---

## 3. Requirement-to-Architecture Mapping

| Requirement | Architecture Decision |
| --- | --- |
| FR-A2-1 | New `report_issuance_governance/` module; guard invoked at CLI dispatch, not inside Phase 6/7 internals |
| FR-A2-2, FR-A2-3 | `evaluate_issuance_checkpoint()` reads `CertificationMetadata` read-only via the existing `phase8_consumer_contract_v1` access pattern; absence or non-`CERTIFIED` requires a matching `DisclosureRecord` |
| FR-A2-4 | New `DisclosureRecord` schema: `certificate_id`, `terminal_state`, `acknowledged_failures` (server-computed, exact match to `CertificationMetadata.disclosed_failures`) |
| FR-A2-5, AC-A2-5 | `CertificationMetadata` is always the latest record by construction (`write_cert_metadata_complete` unconditional `PutItem`); checkpoint requires no extra logic — reading the fixed identity-tuple key always returns the current state |
| AC-A2-7 | Checkpoint additionally requires `CertificationMetadata.report_id == ReportMetadata.report_id` (current); mismatch is treated as non-`CERTIFIED`, requiring a `CERTIFIED_BUT_SUPERSEDED_REPORT` disclosure |
| FR-A2-6, FR-A2-7 | No modification to Phase 6/7 write paths; checkpoint is a synchronous, on-demand CLI-boundary guard, never a stream/event consumer |

---

## 4. Technical Scope

### Current Technical Scope

- New package `src/release_confidence_platform/report_issuance_governance/`: `models.py` (`DisclosureRecord`, `DisclosureEvent` Pydantic models), `identity.py` (ID generation, SK builders), `repository.py` (read-only `CertificationMetadata`/`ReportMetadata` access + `DisclosureRecord` read/write), `checkpoint.py` (`evaluate_issuance_checkpoint()` guard function + `IssuanceBlockedError` hierarchy), `service.py` (`IssuanceGovernanceService` — disclosure recording orchestration), `commands.py` (new `rcp issuance disclose` and `rcp issuance status` CLI commands).
- `src/release_confidence_platform/operator_cli/main.py`: modified to invoke `evaluate_issuance_checkpoint()` immediately before dispatching any `retrieve_command` other than `report-status` — i.e., all six commands backed by `ReportRetrievalService.get_report_dto()`/`get_report_artifact()` (`report-json`, `report-markdown`, `report-summary`, `report-endpoints`, `report-methodology`, `report-lineage`) — and to register the new `issuance` command group. **Corrected from an earlier draft of this document, which gated only `report-json`/`report-markdown`; architecture review traced `report_service.py` and found `report-summary`, `report-endpoints`, `report-methodology`, and `report-lineage` all call `get_report_dto()` and return the same full report content, just differently rendered. `report-status` is the sole exemption, verified DynamoDB-only with no S3 read.**
- No modification to `deterministic_reporting/` or `audit_platform_integrity/` source.

### Out of Scope

- The specific architectural mechanism is this document's own subject — already resolved above; no further mechanism-level ambiguity carried forward.
- Building an actual customer-facing delivery/export feature. No such feature exists today.
- Terminology reconciliation between "Audit Platform Integrity" and "Audit Process Integrity" (Workstream B2) — this design uses "Audit Platform Integrity" throughout.
- Any change to Phase 7's eight certification domains, terminal-state determination logic, or certificate schema (`cert_v1`).
- Any event-driven or automated triggering of Phase 7 certification itself.
- Legal hold, disposal, or any other A1 concern (covered in the companion A1 technical design; A1 and A2 are independent and do not share code, though both introduce new `MetadataTable` sort-key namespaces).

### Future Technical Considerations

- A future customer-facing delivery mechanism (Workstream E) must independently invoke `evaluate_issuance_checkpoint()`; this design does not automatically extend protection to code paths that do not call it.
- Extending the checkpoint to additional retrieval commands if their output is later judged customer-facing.

---

## 5. Architecture Overview

### 5.1 Platform Pipeline Position

Issuance Governance sits downstream of, and independent from, both Phase 6 and Phase 7 — it is not itself a pipeline phase, but a read-time composition layer invoked only when full report content is requested:

```
Phase 6 (Deterministic Reporting)          Phase 7 (Audit Platform Integrity)
   ReportMetadata.status = COMPLETE   ...      CertificationMetadata.terminal_state
   (unaffected by A2)                          (unaffected by A2; operator-invoked, unchanged)
        │                                              │
        │  read-only, at issuance time                 │  read-only, at issuance time
        └──────────────────┬───────────────────────────┘
                            ▼
              report_issuance_governance/checkpoint.py
              evaluate_issuance_checkpoint(identity tuple)
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
     CERTIFIED + report_id match    else: read DisclosureRecord
              │                           │
              ▼                           ▼
         ISSUANCE ALLOWED         match found & complete? ALLOWED
                                   else: IssuanceBlockedError
```

### 5.2 CLI Composition Point

```
operator_cli/main.py
  if retrieve_command.startswith("report-"):
      ... existing Phase 6 wiring (ReportRepository, ReportPublisher, ReportRetrievalService) ...
      if retrieve_command != "report-status":
          # Gates report-json, report-markdown, report-summary, report-endpoints,
          # report-methodology, report-lineage — every command backed by
          # get_report_dto()/get_report_artifact() (full S3 artifact read).
          # report-status is exempt: DynamoDB-only, no S3 read, no report content.
          evaluate_issuance_checkpoint(cert_repo, disclosure_repo, <identity tuple>)  # NEW — raises on block
      rendered = dispatch_report_retrieve(args, svc, formatter)   # existing, unmodified
```

`evaluate_issuance_checkpoint` is the only new call in this function; `dispatch_report_retrieve`, `ReportRetrievalService`, and every Phase 6/7 module remain byte-for-byte unmodified. The gating condition is an exemption list of one (`!= "report-status"`), not an inclusion list of six, specifically so that if a future `report-*` command is added to `deterministic_reporting/report_retrieve_commands.py` and it, too, resolves to `get_report_dto()`/`get_report_artifact()`, it is gated by default rather than requiring an explicit opt-in that could be forgotten — a new DynamoDB-only diagnostic command would need to be explicitly added to the exemption, which is the safer default direction for a governance-enforcement checkpoint.

### 5.3 Read/Write Separation

- Issuance Governance reads `CertificationMetadata` using precisely the `phase8_consumer_contract_v1` access pattern (single `GetItem` by identity-tuple key; never reads `CertificationJob`) — it is architecturally a second Phase 7 consumer alongside Phase 8, bound by the same restrictions Phase 8 already honors.
- Issuance Governance reads `ReportMetadata` using precisely the existing Phase 6/Phase 7 access pattern (single `GetItem` by identity-tuple key).
- Issuance Governance writes only to its own new `#DISC#` sort-key namespace. It never writes to any Phase 6 or Phase 7 sort-key namespace, satisfying FR-A2-6 and Non-Negotiable Invariant 5 of `adr_phase7_certification_independence.md`.

---

## 6. System Components

| Component | Responsibility |
| --- | --- |
| `report_issuance_governance/models.py` | Pydantic models: `DisclosureRecord`, `DisclosureEvent` |
| `report_issuance_governance/identity.py` | ID generation (`disc_` prefix); SK builders for the `#DISC#` namespace |
| `report_issuance_governance/repository.py` | Read-only `GetItem` for `CertificationMetadata` (Phase 7 SK pattern) and `ReportMetadata` (Phase 6 SK pattern); read/write for `DisclosureRecord`/`DisclosureEvent` |
| `report_issuance_governance/checkpoint.py` | `evaluate_issuance_checkpoint()` — the guard function; `IssuanceBlockedError` and subclasses |
| `report_issuance_governance/service.py` (`IssuanceGovernanceService`) | `record_disclosure()` — computes `disclosure_reason` and `acknowledged_failures` server-side, writes `DisclosureEvent` + `DisclosureRecord` |
| `report_issuance_governance/commands.py` | `rcp issuance disclose` (write), `rcp issuance status` (read-only lookup of current disclosure/checkpoint state) CLI |
| `operator_cli/main.py` (modified) | Invokes the checkpoint inline before dispatch of any `report-*` command except `report-status` (`report-json`, `report-markdown`, `report-summary`, `report-endpoints`, `report-methodology`, `report-lineage`); registers the `issuance` command group |

---

## 7. Data Models

### 7.1 `DisclosureRecord` (current-state record)

**Purpose:** Authoritative current disclosure for a given `(identity tuple, cert_version)` combination. Analogous in pattern to `ReportMetadata`/`CertificationMetadata` (one current-state record per key, overwritten on each new disclosure action).

**Primary Key:**
- PK: `CLIENT#{client_id}`
- SK: `AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#RPT#{report_version}#DISC#{cert_version}#META`

This SK pattern extends the identical structural qualifiers already used by `ReportMetadata` and `CertificationMetadata` (Section 3 of `phase_6_report_schema.md`; Section 5 of `phase_7_phase8_consumer_contract.md`), adding the new `#DISC#{cert_version}#META` terminal segment. It does not collide with `#RPTJOB#`, `#RPT#...#META`, `#CERTJOB#`, or `#CERT#...#META` — verified against the combined Sort Key Prefix Index in `phase_6_report_schema.md` §10.

**Fields:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` / `SK` | String | Yes | As above |
| `record_type` | String | Yes | `disclosure_record` |
| `disclosure_id` | String | Yes | Reference to the most recent `DisclosureEvent` (prefix `disc_`) |
| `client_id` / `audit_id` / `audit_execution_id` / `config_version` / `aggregation_version` / `intelligence_version` / `report_version` / `cert_version` | String | Yes | Full identity tuple, carried verbatim |
| `disclosure_reason` | String | Yes | Bounded set: `NO_CERTIFICATION_RECORD` \| `NON_CERTIFIED_TERMINAL_STATE` \| `CERTIFIED_BUT_SUPERSEDED_REPORT` |
| `governing_certificate_id` | String | No | The `CertificationMetadata.certificate_id` this disclosure was written against; absent only when `disclosure_reason = NO_CERTIFICATION_RECORD` |
| `governing_terminal_state` | String | No | The `CertificationMetadata.terminal_state` at disclosure time; absent only when `disclosure_reason = NO_CERTIFICATION_RECORD` |
| `governing_report_id` | String | Yes | `ReportMetadata.report_id` this disclosure covers — the report content it authorizes issuance of |
| `acknowledged_failures` | List[String] | Yes | Server-computed exact copy of `CertificationMetadata.disclosed_failures` at disclosure time; empty list when `disclosure_reason` is not `NON_CERTIFIED_TERMINAL_STATE` |
| `justification` | String | Yes | Operator-supplied free-text justification (required, non-empty) |
| `disclosed_by` | String | Yes | Opaque operator identity string |
| `disclosed_at` | String | Yes | UTC ISO-8601 |

**Ownership:** One record per `(client_id, audit_id, audit_execution_id, config_version, aggregation_version, intelligence_version, report_version, cert_version)`. Written on first disclosure via conditional put; overwritten on each subsequent disclosure action for the same key (e.g., after a force re-certification changes the governing certificate, a new disclosure supersedes the old one at the same SK).

**Lifecycle:** Created on first `rcp issuance disclose` invocation. Overwritten (never appended in place) on each subsequent disclosure for the same identity-tuple/cert_version combination. Never deleted; not subject to A1's custody-period mechanism by default (a disclosure is a governance decision record, analogous to `LegalHoldEvent` in A1 — this parallel is noted but A1 and A2 do not share code or infrastructure).

### 7.2 `DisclosureEvent` (immutable log)

**Purpose:** Immutable audit log of every disclosure action, mirroring the platform's Job-log convention (`ReportJob`, `CertificationJob`) and A1's `LegalHoldEvent` pattern.

**Primary Key:**
- PK: `CLIENT#{client_id}`
- SK: `AUDIT#{audit_id}#DISC#{disclosure_id}`

**Fields:** `record_type` (`disclosure_event`), `disclosure_id`, full identity tuple, `disclosure_reason`, `governing_certificate_id`, `governing_terminal_state`, `governing_report_id`, `acknowledged_failures`, `justification`, `disclosed_by`, `disclosed_at`.

**Ownership:** Scoped to `client_id`. Written once per disclosure action via conditional put. Never mutated after write.

---

## 8. API Contracts

### Command: `rcp issuance disclose`

**Purpose:** Record an explicit, structured disclosure authorizing issuance of a report whose certification is absent, non-`CERTIFIED`, or superseded by a report regeneration.

**Authentication / Authorization:** Operator CLI access only, same trust boundary as all existing `rcp` commands. No new authorization model introduced — consistent with A2's Out-of-Scope statement that no customer-facing delivery or auth mechanism is being built.

**Request Parameters:** `--client-id`, `--audit-id`, `--execution`, `--config-version`, `--aggregation-version`, `--intelligence-version`, `--report-version`, `--cert-version` (default `cert_v1`), `--stage` (all required, following the exact argument set already used by `rcp certify audit` and `rcp retrieve report-*`), `--justification` (required, free text), `--actor` (required).

**Request Body:** N/A (CLI arguments only).

**Response Body:** `disclosure_id`, `disclosure_reason` (computed, not operator-supplied), `governing_certificate_id`, `acknowledged_failures`, `disclosed_at`.

**Success Status Codes:** Exit code `0`.

**Error Status Codes:** `INVALID_IDENTIFIER`, `REPORT_NOT_FOUND` (no `ReportMetadata` exists for the identity tuple — nothing to disclose against), `DISCLOSURE_NOT_REQUIRED` (the current `CertificationMetadata` is `CERTIFIED` with a matching `report_id` — disclosure is a no-op error, not silently accepted, since inviting an unnecessary disclosure could mask a future real gap), `STORAGE_ERROR`.

**Validation Rules:** `justification` must be non-empty. `disclosure_reason` and `acknowledged_failures` are never accepted as operator input — they are always computed server-side from the current `CertificationMetadata`/`ReportMetadata` state at the moment of invocation, eliminating the possibility of a partial or fabricated disclosure (the edge case explicitly called out in the Product Spec: "a disclosed-limitation record that only partially covers the `disclosed_failures` list... must not satisfy the disclosure requirement").

**Side Effects:** Writes `DisclosureEvent` (immutable) + upserts `DisclosureRecord` (current-state) for the identity tuple + `cert_version`.

**Idempotency / Duplicate Handling:** Re-invoking `disclose` for the same identity tuple after nothing has changed (same governing certificate, same report) overwrites the `DisclosureRecord` with an identical payload except `disclosure_id`/`disclosed_at`/`disclosed_by` — safe, non-destructive, and always append-only at the `DisclosureEvent` log level regardless of how many times invoked.

### Command: `rcp issuance status`

**Purpose:** Read-only lookup of current issuance checkpoint state for an identity tuple — "would a gated `report-*` retrieval (`report-json`, `report-markdown`, `report-summary`, `report-endpoints`, `report-methodology`, `report-lineage`) be allowed right now, and why."

**Authentication / Authorization:** Same as `disclose`; read-only.

**Request Parameters:** Same identity-tuple arguments as `disclose`, minus `--justification`/`--actor`.

**Response Body:** `issuance_status` (`ALLOWED` \| `BLOCKED`), `reason` (one of the `disclosure_reason` values, or `CERTIFIED` if allowed via certification), `governing_certificate_id` (if any), `disclosure` (the current `DisclosureRecord` content, if one exists and is current — satisfies AC-A2-4's "disclosure record must be retrievable alongside the issued report content").

**Success Status Codes:** Exit code `0` (returns `BLOCKED` as a normal, successful read — this command never itself blocks; it reports the checkpoint's would-be decision).

**Error Status Codes:** `INVALID_IDENTIFIER`, `STORAGE_ERROR`.

**Side Effects:** None (read-only).

### Guard Function: `evaluate_issuance_checkpoint()`

Not a CLI command — an internal guard function invoked by `operator_cli/main.py` before dispatch of any gated `report-*` command (all six except `report-status`), and reused by `rcp issuance status` for its read-only preview.

**Contract:**
```
evaluate_issuance_checkpoint(
    cert_repository, report_repository, disclosure_repository,
    client_id, audit_id, audit_execution_id, config_version,
    aggregation_version, intelligence_version, report_version, cert_version,
) -> None   # returns silently if allowed

Raises:
    IssuanceBlockedNoCertificationError    — no CertificationMetadata record exists (FR-A2-3)
    IssuanceBlockedNonCertifiedError       — terminal_state != CERTIFIED, no matching disclosure
    IssuanceBlockedSupersededReportError   — CERTIFIED but report_id mismatch, no matching disclosure
```

Each exception is a distinct, structured, distinguishable error type (subclassing a common `IssuanceBlockedError(EngineError)`, following the existing `core/exceptions.py` hierarchy pattern), satisfying AC-A2-3's "must fail with a structured, distinguishable error."

**Evaluation logic (concrete rule, resolving AC-A2-5 and AC-A2-7):**

```
cert = cert_repository.get_cert_metadata(identity tuple, cert_version)   # read-only, Phase 8 pattern
report = report_repository.get_report_metadata(identity tuple)            # read-only, existing pattern

if cert is None:
    disclosure = disclosure_repository.get_disclosure(identity tuple, cert_version)
    if disclosure and disclosure.disclosure_reason == "NO_CERTIFICATION_RECORD"
                   and disclosure.governing_report_id == report.report_id:
        return  # allowed
    raise IssuanceBlockedNoCertificationError(...)

if cert.terminal_state != "CERTIFIED":
    disclosure = disclosure_repository.get_disclosure(identity tuple, cert_version)
    if (disclosure and disclosure.disclosure_reason == "NON_CERTIFIED_TERMINAL_STATE"
            and disclosure.governing_certificate_id == cert.certificate_id
            and disclosure.acknowledged_failures == cert.disclosed_failures
            and disclosure.governing_report_id == report.report_id):
        return  # allowed
    raise IssuanceBlockedNonCertifiedError(...)

# terminal_state == CERTIFIED — check report freshness (AC-A2-7)
if cert.report_id != report.report_id:
    disclosure = disclosure_repository.get_disclosure(identity tuple, cert_version)
    if (disclosure and disclosure.disclosure_reason == "CERTIFIED_BUT_SUPERSEDED_REPORT"
            and disclosure.governing_certificate_id == cert.certificate_id
            and disclosure.governing_report_id == report.report_id):
        return  # allowed
    raise IssuanceBlockedSupersededReportError(...)

return  # allowed — CERTIFIED and governs the current report artifact
```

Every disclosure match requires `governing_report_id == report.report_id` (the *current* report), so a disclosure written before a subsequent force report regeneration does not silently carry forward — it must be re-recorded, exactly mirroring how a stale `CERTIFIED` state itself does not carry forward.

---

## 9. Frontend Impact

None. RCP has no customer-facing or operator web UI; all interaction is via the `rcp` CLI. No UI states, components, or client-side integration apply.

---

## 10. Backend Logic

### 10.1 Responsibilities

- Evaluate, at the moment any gated `report-*` command is requested (`report-json`, `report-markdown`, `report-summary`, `report-endpoints`, `report-methodology`, `report-lineage` — every command that loads the full S3 report artifact), whether the current report artifact for the identity tuple is certified against itself or has a complete, current disclosure on file.
- Compute `disclosure_reason` and `acknowledged_failures` deterministically from Phase 6/Phase 7 state, never accepting them as operator input, to make partial or fabricated disclosure structurally impossible rather than merely validated against.

### 10.2 Validation Flow

- CLI-boundary validation (`validate_identifier`) before any repository call, consistent with every existing CLI command.
- `evaluate_issuance_checkpoint` performs no writes; `IssuanceGovernanceService.record_disclosure` re-reads `CertificationMetadata`/`ReportMetadata` at write time (not trusting any value the CLI may have cached from an earlier `status` call), so a disclosure always reflects the true current state at the moment of recording, not a stale read.

### 10.3 Business Rules

- `CertificationMetadata` absence, non-`CERTIFIED` state, and `report_id` mismatch on an otherwise-`CERTIFIED` record are the three, and only three, conditions requiring disclosure (`disclosure_reason` bounded set).
- A disclosure is scoped to a specific `(certificate_id or none, report_id)` pair; it does not transfer across a force re-certification (new `certificate_id`) or a force report regeneration (new `report_id`).
- `acknowledged_failures` must exactly equal `CertificationMetadata.disclosed_failures` at write time — enforced structurally by server-side computation, with a Pydantic validator (mirroring `audit_platform_integrity/models.py`'s existing validator pattern) as defense-in-depth.

### 10.4 Persistence Flow

**Sequence — issuance-gated retrieval (allowed path):**

```
rcp retrieve report-json --client-id C --audit-id A --execution E ... --stage S
  │  (identical checkpoint invocation for report-markdown, report-summary, report-endpoints,
  │   report-methodology, report-lineage — only report-status skips this path entirely)
  ├─ operator_cli/main.py: retrieve_command startswith "report-"
  │    └─ retrieve_command != "report-status"?
  │         └─ evaluate_issuance_checkpoint(...)
  │              ├─ GetItem CertificationMetadata  → terminal_state=CERTIFIED, report_id matches
  │              └─ return (allowed, no exception)
  └─ dispatch_report_retrieve(args, svc, formatter)   [existing, unmodified Phase 6 path]
       └─ full report JSON returned
```

**Sequence — issuance-gated retrieval (blocked path):**

```
rcp retrieve report-summary ...   # any of the six gated commands, not only report-json
  │
  ├─ evaluate_issuance_checkpoint(...)
  │    ├─ GetItem CertificationMetadata → None (never certified)
  │    ├─ GetItem DisclosureRecord → None
  │    └─ raise IssuanceBlockedNoCertificationError
  └─ CLI catches, prints structured error, exit code != 0
       (dispatch_report_retrieve is never called — no report content, full or partial-rendered, is returned)
```

**Sequence — recording a disclosure:**

```
rcp issuance disclose --client-id C --audit-id A --execution E ... --justification "..." --actor "..."
  │
  ├─ validate_identifier(client_id, audit_id)
  ├─ IssuanceGovernanceService.record_disclosure(...)
  │    ├─ GetItem ReportMetadata → REPORT_NOT_FOUND if absent
  │    ├─ GetItem CertificationMetadata
  │    ├─ compute disclosure_reason (NO_CERTIFICATION_RECORD | NON_CERTIFIED_TERMINAL_STATE
  │    │                              | CERTIFIED_BUT_SUPERSEDED_REPORT)
  │    │    └─ if CERTIFIED and report_id matches: raise DISCLOSURE_NOT_REQUIRED
  │    ├─ acknowledged_failures = cert.disclosed_failures if present else []
  │    ├─ write DisclosureEvent (immutable)
  │    └─ upsert DisclosureRecord (current-state, keyed by identity tuple + cert_version)
  └─ return summary
```

### 10.5 Error Handling

- `IssuanceBlockedError` subclasses are caught at the `operator_cli/main.py` dispatch layer using the same error-to-exit-code pattern already used for `ValidationError`/`StorageError` elsewhere in that module — no new error-handling architecture is introduced, only new error types within the existing hierarchy.
- A failure to read `CertificationMetadata` or `ReportMetadata` due to infrastructure error (`StorageError`) fails closed — the checkpoint never treats a read failure as "allowed by default." This is the correct default given FR-A2-3's explicit prohibition on implicit passes.

---

## 11. File Structure

```
src/release_confidence_platform/report_issuance_governance/
    __init__.py
    constants.py        # disclosure_reason bounded set, ID prefix (disc_), SK segment constant (#DISC#)
    identity.py          # generate_disclosure_id()
    models.py             # DisclosureRecord, DisclosureEvent (Pydantic)
    repository.py         # read-only CertificationMetadata/ReportMetadata GetItem; DisclosureRecord/Event read+write
    checkpoint.py          # evaluate_issuance_checkpoint(), IssuanceBlockedError hierarchy
    service.py              # IssuanceGovernanceService.record_disclosure()
    commands.py              # rcp issuance disclose|status CLI

src/release_confidence_platform/operator_cli/main.py   # modified: checkpoint invocation + issuance command wiring
```

No file under `deterministic_reporting/` or `audit_platform_integrity/` is created, modified, or deleted.

---

## 12. Security

- **No new external attack surface.** All new CLI commands are operator-only, at the same trust boundary as every existing `rcp` command. No customer-facing or network-exposed interface is introduced, consistent with A2's explicit Out-of-Scope statement.
- **IAM scope for `report_issuance_governance/repository.py`:** requires `dynamodb:GetItem` on `MetadataTable` scoped to Phase 6/Phase 7 SK patterns (read-only — never `PutItem`/`UpdateItem`/`DeleteItem` against those namespaces) and `dynamodb:GetItem`/`PutItem` scoped to its own `#DISC#` namespace only. This mirrors the exact restriction shape already enforced in `audit_platform_integrity/repository.py`'s `_assert_phase7_sk` guard — this design should carry forward the same style of write-target assertion (`_assert_issuance_sk`) before any `PutItem`/`UpdateItem` call, guaranteeing at the code level, not just by convention, that Issuance Governance can never write to a Phase 6 or Phase 7 sort key.
- **Fail-closed default.** Every blocked path (no certification, non-`CERTIFIED`, superseded report, infrastructure read failure) results in a raised exception and no report content returned. There is no code path that returns report content by default when a lookup fails or is inconclusive.
- **No sensitive data introduced.** `DisclosureRecord`/`DisclosureEvent` fields are identifiers, bounded enum values, timestamps, and free-text operator justification — no raw request/response bodies, headers, tokens, or PII.
- **Sanitization boundary compliance (`adr_sanitization_boundary.md`).** `client_id`, `audit_id`, `certificate_id`, and `report_id` are canonical identifier fields carried into `DisclosureRecord`/`DisclosureEvent` and used to construct `PK`/`SK`. Per that ADR, `sanitize()` must never be applied to these fields before persistence, only to structured log output and human-readable CLI rendering. `report_issuance_governance/repository.py` must follow the same convention already established in `audit_platform_integrity/repository.py`, which performs no `sanitize()` call on any item dict passed to `PutItem`/`UpdateItem`.
- **Misuse risk — disclosure as a rubber stamp.** Because `disclosure_reason` and `acknowledged_failures` are always server-computed (never operator-supplied), an operator cannot construct a disclosure that misrepresents the certification state. The only operator-controlled content is the free-text `justification`, which has no bearing on whether issuance is technically allowed — it is a documentation field, not a bypass parameter.
- **Accepted risk — the checkpoint is a CLI-layer control, not a resource-layer one.** An operator with direct AWS API access (`aws s3 cp` against the report artifact's known S3 key, or a raw DynamoDB `GetItem`/`Scan`) using the same credentials the `rcp` CLI already requires can read the same underlying `RawResultsBucket`/`MetadataTable` content without passing through `evaluate_issuance_checkpoint()` at all. This is not a gap this design closes — every existing `rcp` command in this platform is enforced only at the CLI layer, with no independent server-side authorization boundary between an operator's AWS credentials and the underlying resources, and A2 does not change that trust model. The checkpoint raises the bar for the intended retrieval path; it is explicitly not designed to prevent an operator with direct AWS access from bypassing it by other means. Stated here so a reviewer or operator does not have to infer it.

---

## 13. Reliability

- **No new asynchronous infrastructure.** Unlike A1, A2 introduces no Lambda, stream, or event source — `evaluate_issuance_checkpoint` is a synchronous, in-process function called inline during CLI dispatch. There is no eventual-consistency window to reason about; every read reflects the current DynamoDB state at the instant of the CLI invocation.
- **Read amplification.** Each gated retrieval now performs up to three `GetItem` calls (`ReportMetadata`, `CertificationMetadata`, `DisclosureRecord`) instead of one. This is a bounded, constant-factor cost (DynamoDB point lookups, not queries or scans) and has no meaningful latency or cost impact at the platform's current scale.
- **Fail-closed on infrastructure error.** A `StorageError` during any of the three reads propagates as a hard failure (report content is not returned), never silently defaulting to "allowed." This trades availability for correctness in the specific way the Product Constitution requires — issuance is a trust gate, not a best-effort convenience feature.
- **Monitoring:** structured log events for every checkpoint evaluation outcome (allowed / blocked-and-why) and every `record_disclosure` call, consistent with `docs/architecture/structured_logging.md`, giving operators and compliance reviewers an observable trail of every issuance decision, not only the ones that were explicitly disclosed.

---

## 14. Dependencies

- **`phase7_consumer_contract_v1` / `phase8_consumer_contract_v1` stability.** The checkpoint's `CertificationMetadata` read depends on the same stable field set (`terminal_state`, `certificate_id`, `report_id`, `disclosed_failures`) Phase 8 already depends on. Any future breaking change to that contract requires updating this checkpoint alongside Phase 8, per the existing contract-versioning governance process in `phase_7_phase8_consumer_contract.md` §7.
- **No customer-facing delivery mechanism exists yet.** The checkpoint is designed against the currently-existing engineering retrieval CLI commands as the initial (and currently only) enforcement points, per the Product Spec's own flagged dependency (Section 11, A2). A future delivery mechanism (Workstream E) must independently invoke `evaluate_issuance_checkpoint()`.
- **Terminology.** Uses "Audit Platform Integrity" throughout per the current locked roadmap term; reconciliation with "Audit Process Integrity" (Workstream B2) is not addressed here.

---

## 15. Assumptions

**Resolved (previously flagged as an assumption requiring confirmation; now a direct code-inspection finding, not a judgment call):** The Product Spec's Section 12 assumption provisionally named `retrieval/service.py` and the commands `rcp retrieve report-json`/`report-markdown` as the issuance attachment points. Direct code inspection during this planning pass establishes that `retrieval/service.py` (`RetrievalService`) is the **Phase 4A Engineering Retrieval** module — it serves aggregation-layer diagnostic queries (job status, lineage manifests, timelines) and never touches `ReportMetadata` or full report content. The actual `report-*` commands are implemented in `deterministic_reporting/report_retrieve_commands.py` (parser + dispatch table) and `deterministic_reporting/report_service.py` (`ReportRetrievalService`), wired at `operator_cli/main.py`'s `if retrieve_command.startswith("report-"):` block. This design attaches the checkpoint at the corrected location.

Architecture review additionally traced `report_service.py` method boundaries directly and found that `report-summary`, `report-endpoints`, `report-methodology`, and `report-lineage` all call `get_report_dto()` — the identical full-artifact load `report-json` serializes wholesale — while only `report-status` calls the DynamoDB-only `get_report_status()`. **This retracts the earlier narrower scoping assumption (gating only `report-json`/`report-markdown`).** The checkpoint gates all six commands backed by `get_report_dto()`/`get_report_artifact()` and exempts only `report-status`. This is now a direct, verifiable consequence of `report_service.py`'s method boundaries, not a discretionary scoping choice requiring further Product Strategy confirmation — the "which operations constitute issuance" question the Product Spec flagged as provisional is resolved by the code itself: any operation returning the full parsed report DTO is issuance; the one operation that does not (`report-status`) is not.

**Assumption requiring confirmation (`cert_version` argument default):** This design assumes `rcp issuance disclose`/`rcp issuance status` accept an optional `--cert-version` argument defaulting to `cert_v1`, mirroring `rcp certify audit`'s existing default. If a future `cert_v2` is introduced, the checkpoint's SK construction (which includes `#CERT#{cert_version}#META` and `#DISC#{cert_version}#META`) must be re-evaluated against the new version's identity-tuple shape; this is a straightforward consequence of the platform's existing versioning discipline, not a new risk, but is noted as an implementation-time detail requiring confirmation of the exact default value convention.

---

## 16. Risks / Open Questions

- **Risk (resolved by this revision):** an earlier draft of this design narrowed "issuance" to exactly two CLI commands (`report-json`, `report-markdown`), on the incorrect premise that the other five `report-*` commands returned only partial/diagnostic content. Architecture review traced `report_service.py` and found `report-summary`, `report-endpoints`, `report-methodology`, and `report-lineage` all resolve to the same full-artifact read as `report-json`, meaning the narrower scoping would have left an operator able to reconstruct the entire substantive report through ungated commands and never trip the checkpoint. The gating condition is now `retrieve_command != "report-status"` (Section 5.2) — an exemption list of one, verified DynamoDB-only command, rather than an inclusion list of two. This is no longer an open Product Strategy question; it is a code-verified scoping rule.
- **Residual risk:** the checkpoint's protection is scoped to what `operator_cli/main.py` calls today. If `deterministic_reporting/report_retrieve_commands.py` gains a new `report-*` command in the future that resolves to a full-artifact read, it is gated by default under the `!= "report-status"` exemption-list design (Section 5.2) — but if a future command is added to an entirely different dispatch path outside the `report-*` family (e.g., a hypothetical `rcp export` command), it would not automatically inherit this protection and must independently invoke `evaluate_issuance_checkpoint()`.
- **Risk:** a disclosure's `justification` field has no structural validation beyond non-empty. This is intentional (justification is a documentation field, not a control), but means the *quality* of a disclosure's human-readable rationale is entirely operator-dependent — acceptable given A1/A2's explicit exclusion of any new authorization/review workflow, but worth surfacing to Product Strategy as a potential future enhancement (e.g., a required-reviewer field), explicitly out of scope for A2 as currently specified.
- **Open dependency:** Workstream E (customer-facing delivery) will need to independently wire the checkpoint once it exists; not resolved here per the Product Spec's explicit scope boundary.
- **Open dependency:** Workstream B2 terminology reconciliation; not resolved here.
- **Open question:** should `DisclosureRecord`/`DisclosureEvent` be exempt from A1's custody-period mechanism, the same way A1's `LegalHoldEvent`/`DisposalRecord` are exempt from their own mechanism? This design assumes yes (a disclosure is a governance decision record analogous to a legal hold event, not disposable evidence) but does not formally specify A1/A2 interaction, since the two workstreams are independent by design; if A1 and A2 are both implemented, this interaction should be explicitly confirmed rather than left to default TTL-field-absence behavior alone.

---

## 17. Implementation Notes

- Implement `report_issuance_governance/` as a fully independent package first, with unit tests against fixture `CertificationMetadata`/`ReportMetadata`/`DisclosureRecord` payloads (following the fixture-based testing pattern already used for Phase 7's `cert_v1` compatibility gate test), before touching `operator_cli/main.py`.
- The `operator_cli/main.py` change should be the smallest possible diff: one new guard-function call inserted before the existing `dispatch_report_retrieve` call, plus new parser registration for the `issuance` command group. No existing line in that function should need to change beyond that insertion.
- QA/Test Strategy (next SDLC stage) should explicitly cover: AC-A2-1 through AC-A2-7 as literal test cases, the concurrent-issuance-during-force-recertification scenario (Decision 5 of the companion ADR), and a regression test asserting `deterministic_reporting/` and `audit_platform_integrity/` source trees are unmodified by this workstream (a structural guarantee worth asserting explicitly, given how central "do not touch Phase 6/7 internals" is to this design's compliance with `adr_phase7_certification_independence.md`).
