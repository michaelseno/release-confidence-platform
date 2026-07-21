# Technical Design

## Evidence Governance Workstream A1 — Evidence Retention Enforcement

**Status:** Planning only. No implementation, code change, or PR is authorized by this document.
**Companion ADR:** `docs/architecture/adr_evidence_retention_disposal_enforcement.md`
**Companion Product Spec:** `docs/product/evidence_governance_workstream_a_product_spec.md`

**Governance note (pre-A1.3 amendment):** A1.1 and A1.2 are implemented, merged, and QA-validated. Product Strategy withheld A1.3 execution authorization pending correction of a materially incomplete write-path inventory in this document (§11 previously listed 7 rows / 2 fully-specified methods against 32 actual write call sites in the repository) and resolution of the governed-record-boundary ambiguity that inventory exposed. §11 has been replaced with an independently re-verified inventory, and §18 is the new, required governed revision covering the governed-record boundary, structural exclusions, regeneration semantics, the dual-tree write-path hazard, `configs/` classification, an unconstrained update method, backlog-scope reconfirmation, and a revised implementation estimate. Read §18 before proposing A1.3.

---

## 1. Feature Overview

A1 replaces today's unconditional, indefinite retention of everything in `RawResultsBucket` (S3) and `MetadataTable` (DynamoDB) with a technically enforced custody-period disposal mechanism, a legal-hold override, and a durable disposal record — closing a confirmed conflict between already-shipped Phase 1–7 behavior and the Evidence Governance Baseline's default ("evidence shall not outlive its authorized governance purpose").

A1 is a correction to existing infrastructure and a new, cross-cutting enforcement layer — it is not owned by, and does not modify, any existing phase's business logic. It introduces one new package (`evidence_retention/`), four new DynamoDB record types, two new S3/DynamoDB infrastructure primitives (Lifecycle configuration, TTL + Streams), and one new Lambda.

---

## 2. Product Requirements Summary

| Requirement | Description |
| --- | --- |
| FR-A1-1 | Enforced expiration for every `RawResultsBucket` object, unless legal hold active |
| FR-A1-2 | Enforced expiration for every `MetadataTable` record, unless legal hold active |
| FR-A1-3 | Expiration derived from externally supplied custody-period configuration, never hardcoded |
| FR-A1-4 | Place/release legal hold scoped to `client_id` + `audit_id`; held evidence never disposed while active |
| FR-A1-5 | Durable, queryable record of every automatic disposal action |
| FR-A1-6 | Enforcement applies uniformly to evidence from any phase (1–7), no per-phase opt-in |
| AC-A1-7 | Noncurrent S3 object versions must also expire, not only current versions |
| AC-A1-8 | Design must explicitly state backlog (pre-Workstream-A evidence) handling |

---

## 3. Requirement-to-Architecture Mapping

| Requirement | Architecture Decision |
| --- | --- |
| FR-A1-1, AC-A1-7 | `RawResultsBucket` `LifecycleConfiguration`: **four** per-evidence-class rules (`raw-results/`, `intelligence/`, `reports/`, `integrity/` — implemented in A1.2), each independently tag-filtered `Expiration` + `NoncurrentVersionExpiration` scoped to `rcp-legal-hold=false` and its own evidence-class key prefix, each with its own `Days`/`NoncurrentDays` from `custody_period_days.<class>` |
| FR-A1-2 | `MetadataTable` TTL attribute `ttl_disposal_at`; removed (not mutated to a sentinel) while a hold is active |
| FR-A1-3 | Custody-period value sourced from `infra/serverless.yml` `custom.custodyPeriodDays.<class>.${stage}` — one independent parameter per evidence class, no shared or default value across classes; consumed by the corresponding per-class CFN lifecycle rule (§3 row above) and by Lambda environment variables at write time |
| FR-A1-4 | New `LegalHold` / `LegalHoldEvent` DynamoDB records; new `CustodySweepClient` re-tags S3 object versions across all four evidence-class prefixes and removes/restores `ttl_disposal_at` on other phases' DynamoDB records |
| FR-A1-5 | New `DisposalRecord` DynamoDB type, written by a new `evidenceDisposalRecorder` Lambda consuming DynamoDB Streams (TTL path) and S3 Event Notifications (Lifecycle path) |
| FR-A1-6 | Four per-evidence-class S3 lifecycle rules (collectively covering the whole bucket) and one table-wide TTL attribute; no per-phase filter or opt-in required — "uniform coverage" means every evidence class is covered by some rule, not that all evidence classes share one rule or one duration |
| AC-A1-8 | Explicit backlog recommendation below, flagged as Assumption Requiring Confirmation |

---

## 4. Technical Scope

### Current Technical Scope

- `infra/resources/s3.yml`: add `LifecycleConfiguration` to `RawResultsBucket` — **four independent rules, one per evidence class** (`raw-results/`, `intelligence/`, `reports/`, `integrity/`), each tag-filtered `Expiration` + `NoncurrentVersionExpiration` scoped to `rcp-legal-hold=false` and its own evidence-class key prefix, each consuming its own `custom.custodyPeriodDays.<class>.${stage}` value (implemented in A1.2 — see §3, §12); add S3 Event Notification configuration for `s3:LifecycleExpiration:*` routed to EventBridge.
- `infra/resources/dynamodb.yml`: add `TimeToLiveSpecification` (attribute `ttl_disposal_at`) and `StreamSpecification` (`NEW_AND_OLD_IMAGES`) to `MetadataTable`.
- `infra/serverless.yml`: new `evidenceDisposalRecorder` Lambda function (DynamoDB Streams + EventBridge S3-notification triggers); new `custom.custodyPeriodDays` per-evidence-class, per-stage configuration block (value left unset — see Section 15).
- New package `src/release_confidence_platform/evidence_retention/`: `models.py` (Pydantic models for `LegalHold`, `LegalHoldEvent`, `DisposalRecord`), `hold_repository.py` (`HoldRepository` — DynamoDB access for `LegalHold`/`LegalHoldEvent` only, SK-guarded to `#LEGALHOLD#`; **A1.1, implemented**), `disposal_repository.py` (`DisposalRepository` — DynamoDB write for disposal records only, SK-guarded to `#DISPOSAL#`, used exclusively by the Lambda), `custody_sweep_client.py` (`CustodySweepClient` — the S3 per-version tagging sweep and the cross-phase `ttl_disposal_at` removal/restore on other phases' DynamoDB records; operation-guarded, not SK-guarded — see Section 5.2; **A1.2/A1.3 scope**), `service.py` (`RetentionService` — hold placement/release orchestration, depends on **both** `HoldRepository` and `CustodySweepClient`; **A1.2/A1.3 scope**), `identity.py` (ID generation, tag-key constants, SK-namespace constants), `commands.py` (new `rcp retention hold place|release|status` CLI group), `disposal_recorder.py` (Lambda handler logic invoked by the new Lambda, depends on `DisposalRepository` only). The `HoldRepository`/`DisposalRepository`/`CustodySweepClient` three-way split, and the mutually exclusive guards on each, are a direct fix for the write-path contradiction identified in architecture review — see Section 5.2 (amended following A1.1 QA validation to name `CustodySweepClient` explicitly; A1.1 itself implemented only `HoldRepository`/`DisposalRepository`, correctly deferring the sweep).
- Every existing phase write path that persists to `RawResultsBucket` or `MetadataTable` gains: (a) S3 object tagging (`rcp-legal-hold=false`, `rcp-evidence-class={class}`) at `PutObject` time; (b) `custody_expires_at` / `ttl_disposal_at` computation at DynamoDB item-write time. This touches every phase's write call sites but adds fields/tags only — no existing field, record shape, or write condition is altered. Confirmed by direct code inspection, the touched write paths are:
  - **Phase 1/2/3 raw execution evidence** — `packages/storage/s3_client.py` (`S3StorageClient.write_raw_results_once`, the sole `PutObject` call site for raw evidence) and `packages/storage/dynamodb_client.py` (`DynamoDBMetadataClient.put_started_once`, the sole `PutItem` call site for `RUN` records); both invoked from `apps/backend/orchestrator/service.py` (confirmed call sites at approximately lines 102, 222, 238, and 630). This is the largest and most sensitive evidence class and was the original motivation for Workstream A — see Section 11/17 for the corrected, exhaustive enumeration.
  - **Phase 4 aggregation** — `src/release_confidence_platform/aggregation/repository.py`.
  - **Phase 5 intelligence** — `src/release_confidence_platform/reliability_intelligence/repository.py`.
  - **Phase 6 reporting** — `src/release_confidence_platform/deterministic_reporting/repository.py` (DynamoDB) and `.../publisher.py` (S3).
  - **Phase 7 certification** — `src/release_confidence_platform/audit_platform_integrity/repository.py`.

### Out of Scope

- The exact custody-period duration value(s) (Product Strategy decision, tracked separately).
- Evidence profiles / minimization-at-persistence-time (Evidence Governance Baseline 2.2).
- Backup, replica, or archive storage outside `RawResultsBucket` and `MetadataTable` (none exist today).
- Legal hold *authorization* policy — who may place/release a hold, and under what business process. Only the technical override mechanism is designed here.
- Any change to any phase's business logic, scoring, aggregation, intelligence derivation, reporting, or certification behavior.

### Future Technical Considerations

- A formal Evidence Package artifact incorporating disposal metadata (Evidence Governance Baseline 2.1/2.7) — not designed here.
- A future customer authentication/authorization boundary that legal hold authorization could attach to.
- Differentiated custody periods by customer contract rather than by evidence class alone (Workstream B/C).

---

## 5. Architecture Overview

### 5.1 Platform Position

`evidence_retention/` is a cross-cutting layer, not a pipeline phase. It sits alongside every phase rather than after any one of them:

```
Phase 1/2 (raw evidence) ─┐
Phase 4 (aggregates)      ─┤
Phase 5 (intelligence)    ─┼──> [tag/TTL fields set at write time] ──> RawResultsBucket / MetadataTable
Phase 6 (reports)         ─┤                                              │
Phase 7 (certificates)    ─┘                                              │
                                                                            ▼
                                                          S3 Lifecycle (daily sweep) / DynamoDB TTL (~48h best-effort)
                                                                            │
                                                     ┌──────────────────────┴──────────────────────┐
                                                     ▼                                              ▼
                                        S3 Event Notification (LifecycleExpiration)     DynamoDB Streams (REMOVE, TTL principal)
                                                     │                                              │
                                                     └──────────────────> evidenceDisposalRecorder <─┘
                                                                            │
                                                                            ▼
                                                                     DisposalRecord (MetadataTable, #DISPOSAL#)

evidence_retention/service.py (RetentionService)
   ├──uses──> HoldRepository (SK-guarded to #LEGALHOLD# only)
   │             place_legal_hold / release_legal_hold  ──> LegalHold + LegalHoldEvent (MetadataTable, #LEGALHOLD#)
   └──uses──> CustodySweepClient (operation-guarded: ttl_disposal_at-only updates; tagging-only S3 calls;
                                   explicitly excluded from #LEGALHOLD#/#DISPOSAL#)
                 ├─ retags S3 object versions across all evidence-class prefixes (rcp-legal-hold tag)
                 └─ removes/restores ttl_disposal_at on other phases' DynamoDB items (RunMetadata, ReportMetadata, etc.)

evidence_retention/disposal_recorder.py ──uses──> DisposalRepository (SK-guarded to #DISPOSAL# only)
   (RetentionService has no dependency on DisposalRepository, and vice versa — see below.
    CustodySweepClient is likewise never imported by disposal_recorder.py.)
```

### 5.2 Read/Write Separation

**Amendment note (post-A1.1 implementation):** an earlier revision of this section attributed the S3 per-version re-tagging sweep and the cross-phase `ttl_disposal_at` removal/restore to `HoldRepository`, while simultaneously specifying that `HoldRepository`'s `_assert_retention_sk()` guard rejects any SK that isn't `#LEGALHOLD#`-shaped. Those two claims are mutually exclusive: the cross-phase sweep is, by construction, a write to `RunMetadata`/`AggregationJob`/`ReportMetadata`/`CertificationMetadata`/etc. SKs — none of which are `#LEGALHOLD#`-shaped — so the guard as specified would reject exactly the operation the section attributed to that class. A1.1 (data models + repository layer) correctly implemented `HoldRepository` scoped strictly to `LegalHold`/`LegalHoldEvent` CRUD, matching §7.1/§7.2 and keeping `_assert_retention_sk()` strict per ADR Non-Negotiable Invariant 6, and QA validated this as the correct call. This section is amended below to name the second, differently-scoped component (`CustodySweepClient`) that A1.2/A1.3 must introduce for the sweep operations — it was always implied by the product requirements (FR-A1-4) but was never given its own name or component boundary in the original revision, which is what produced the contradiction.

- No existing phase's repository or engine code is modified. Only write call sites gain two additional fields/tags at the point of an already-existing write; no existing conditional-write logic, sort key, or record shape changes.
- **`HoldRepository` writes only to the `#LEGALHOLD#` sort-key namespace.** Its write methods call `_assert_retention_sk()` before every `PutItem`/`UpdateItem`, which raises `AssertionError` if the target SK contains `#DISPOSAL#` (or anything other than `#LEGALHOLD#`) — mirroring `_assert_phase7_sk` in `audit_platform_integrity/repository.py:49`, which guards Phase 7's writes against straying outside `#CERTJOB#`/`#CERT#`. `HoldRepository` has no method capable of touching S3 or any other phase's DynamoDB SK. This is exactly what A1.1 implemented.
- **`CustodySweepClient` (new in this amendment — A1.2/A1.3 scope) is the second, differently-scoped access path `RetentionService` needs.** It performs: (a) the S3 per-version tagging sweep (`ListObjectVersions`/`GetObjectTagging`/`PutObjectTagging` across every S3 prefix under an audit identity, spanning all evidence classes — `raw-results/`, `intelligence/`, `reports/`, `integrity/`), and (b) the cross-phase DynamoDB query + `UpdateItem` to remove/restore the `ttl_disposal_at` attribute on *other phases'* records (`RunMetadata`, Phase 4/5 job and metadata records, `ReportMetadata`, `CertificationMetadata`, etc.). It is deliberately **not** a "repository" in the SK-guarded sense used elsewhere in this design — it legitimately must write to SKs outside any single namespace, so an SK-shape guard like `_assert_retention_sk`/`_assert_disposal_sk` would be the wrong tool and would incorrectly reject its normal operation (this is precisely the contradiction being corrected). Its safety boundary is enforced differently, by operation shape rather than SK shape: `_assert_custody_field_only_update()` inspects every DynamoDB `UpdateExpression` it is about to issue and raises `AssertionError` if the expression touches any attribute other than `ttl_disposal_at`, or if the target SK contains `#LEGALHOLD#` or `#DISPOSAL#` (those two namespaces remain exclusively `HoldRepository`'s and `DisposalRepository`'s respectively — `CustodySweepClient` must not touch them either, even though it may touch everything else). On the S3 side, the class exposes only tagging-API methods (`ListObjectVersions`, `GetObjectTagging`, `PutObjectTagging`) — it has no `put_object`/`delete_object` method at all, so it cannot write or delete evidence content by construction, not merely by IAM restriction.
- **`RetentionService` (A1.2/A1.3 scope) depends on both `HoldRepository` and `CustodySweepClient`** — two distinct dependencies, not one. `place_legal_hold()`/`release_legal_hold()` write `LegalHold`/`LegalHoldEvent` via `HoldRepository`, then invoke `CustodySweepClient` for the S3 re-tagging sweep and the cross-phase `ttl_disposal_at` removal/restore. `RetentionService` has no dependency on `DisposalRepository`.
- **`#DISPOSAL#` is written exclusively by `evidenceDisposalRecorder`**, via a separate `DisposalRepository` class that neither `RetentionService` nor `CustodySweepClient` ever imports. `DisposalRepository`'s write method calls the symmetric guard `_assert_disposal_sk()`, which raises `AssertionError` if the target SK contains `#LEGALHOLD#`. `evidenceDisposalRecorder` never deletes, updates, or reads any evidence content itself (S3 event payloads and DynamoDB stream `OLD_IMAGE` payloads carry everything needed); its only DynamoDB write is a conditional `PutItem` of a new `DisposalRecord`.
- This is now a three-component split — `HoldRepository` (SK-guarded to `#LEGALHOLD#`), `DisposalRepository` (SK-guarded to `#DISPOSAL#`), and `CustodySweepClient` (operation-guarded to `ttl_disposal_at`-only updates and tagging-only S3 calls, explicitly excluded from both guarded namespaces) — and is the code-level enforcement of Non-Negotiable Invariant 6 in the companion ADR. As with Phase 7's `_assert_phase7_sk`, every one of these guards is a programming-error guard, not an IAM-enforced boundary — DynamoDB IAM cannot condition `PutItem`/`UpdateItem` on sort-key substrings or on which attribute an `UpdateExpression` touches, only on the partition key. IAM is configured as defense-in-depth (Section 12) but the primary guarantee is structural, at the code level.

---

## 6. System Components

| Component | Responsibility |
| --- | --- |
| `evidence_retention/models.py` | Pydantic models: `LegalHold`, `LegalHoldEvent`, `DisposalRecord` |
| `evidence_retention/identity.py` | ID generation (`hold_`, `disp_` prefixes); tag key/value constants (`rcp-legal-hold`, `rcp-evidence-class`); SK-namespace constants (`#LEGALHOLD#`, `#DISPOSAL#`) |
| `evidence_retention/hold_repository.py` (`HoldRepository`) | **A1.1, implemented.** DynamoDB read/write for `LegalHold`/`LegalHoldEvent` only — no S3 access, no cross-phase DynamoDB access. Every write call is preceded by `_assert_retention_sk()`, an SK-write guard modeled directly on `_assert_phase7_sk` in `audit_platform_integrity/repository.py:49` — it asserts the target SK contains `#LEGALHOLD#` and does **not** contain `#DISPOSAL#`, raising `AssertionError` otherwise. This class has no `PutItem` method capable of constructing a `#DISPOSAL#`-shaped SK, and (per this amendment) no method capable of touching S3 or any other phase's SK either — those responsibilities belong to `CustodySweepClient` below. |
| `evidence_retention/disposal_repository.py` (`DisposalRepository`) | **A1.1, implemented.** DynamoDB write for `DisposalRecord` only — used exclusively by `disposal_recorder.py`. Every write call is preceded by the symmetric guard `_assert_disposal_sk()`, asserting the target SK contains `#DISPOSAL#` and does **not** contain `#LEGALHOLD#`. This class has no method capable of writing a `LegalHold`/`LegalHoldEvent`-shaped item. `RetentionService` never imports this class. |
| `evidence_retention/custody_sweep_client.py` (`CustodySweepClient`) | **New in this amendment — A1.2/A1.3 scope.** The second, differently-scoped access path `RetentionService` needs, separate from `HoldRepository`. Performs (a) the S3 per-version tagging sweep (`ListObjectVersions`/`GetObjectTagging`/`PutObjectTagging` only — no `put_object`/`delete_object` method exists on this class) across every evidence-class S3 prefix under an audit identity, and (b) the cross-phase DynamoDB query + `UpdateItem` to remove/restore `ttl_disposal_at` on *other phases'* records (`RunMetadata`, Phase 4/5 job/metadata records, `ReportMetadata`, `CertificationMetadata`, etc.). Deliberately **not** SK-guarded like `HoldRepository`/`DisposalRepository` — it must legitimately write to SKs outside any single namespace, so an SK-shape guard is the wrong tool here. Instead, every `UpdateItem` call is preceded by `_assert_custody_field_only_update()`, which raises `AssertionError` if the `UpdateExpression` touches any attribute other than `ttl_disposal_at`, or if the target SK contains `#LEGALHOLD#` or `#DISPOSAL#` (those two namespaces remain off-limits to this class too, even though it may touch everything else). |
| `evidence_retention/service.py` (`RetentionService`) | **A1.2/A1.3 scope.** `place_legal_hold()`, `release_legal_hold()`, `get_hold_status()` — orchestrates `HoldRepository` (for `LegalHold`/`LegalHoldEvent` writes) **and** `CustodySweepClient` (for the S3 sweep and cross-phase `ttl_disposal_at` mutation); has no dependency on `DisposalRepository` |
| `evidence_retention/commands.py` | `rcp retention hold place\|release\|status` CLI parser + dispatch, following the existing `commands.py` pattern (e.g. `audit_platform_integrity/commands.py`) |
| `evidence_retention/disposal_recorder.py` | Lambda handler: parses DynamoDB Streams `REMOVE` events (filtered to `userIdentity.principalId == "dynamodb.amazonaws.com"`) and S3 `LifecycleExpiration` EventBridge events; writes `DisposalRecord` via `DisposalRepository` only |
| `infra/resources/s3.yml` (modified) | `RawResultsBucket.LifecycleConfiguration`; `NotificationConfiguration` (EventBridge) |
| `infra/resources/dynamodb.yml` (modified) | `MetadataTable.TimeToLiveSpecification`; `StreamSpecification` |
| `evidenceDisposalRecorderDLQ` (new, SQS) | Failure destination for both `evidenceDisposalRecorder` event source mappings — the DynamoDB Streams event source mapping's `DestinationConfig.OnFailure` and the EventBridge rule target's `DeadLetterConfig`. Holds any event that exhausted its retry budget without a successful `DisposalRecord` write. |
| `evidenceDisposalRecorderDLQAlarm` (new, CloudWatch Alarm) | Alarms on `AWS/SQS ApproximateNumberOfMessagesVisible > 0` for `evidenceDisposalRecorderDLQ`, so a dropped disposal-recording attempt is an observed, alerted condition rather than a silent gap in FR-A1-5's durable-record guarantee. |
| `infra/serverless.yml` (modified) | New `evidenceDisposalRecorder` function (with `onError`/event-source-mapping `DestinationConfig` wired to the DLQ, `bisectBatchOnFunctionError: true`, and a bounded `maximumRetryAttempts`); new `evidenceDisposalRecorderDLQ` SQS resource and alarm; new `custom.custodyPeriodDays.*` config block; IAM statements for the new Lambda (DynamoDB Streams read, `MetadataTable` `PutItem` scoped to `#DISPOSAL#` writes only, S3 tagging read, SQS `SendMessage` to the DLQ) |

---

## 7. Data Models

### 7.1 `LegalHold` (current-state record)

**Purpose:** Authoritative current hold status for a given audit identity. Analogous in pattern to `ReportMetadata` (one current-state record per identity, updated in place).

**Primary Key:**
- PK: `CLIENT#{client_id}`
- SK: `AUDIT#{audit_id}#LEGALHOLD`

**Fields:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` / `SK` | String | Yes | As above |
| `record_type` | String | Yes | `legal_hold` |
| `client_id` / `audit_id` | String | Yes | Scoping identity |
| `status` | String | Yes | `ACTIVE` \| `RELEASED` |
| `hold_id` | String | Yes | Reference to the most recent `LegalHoldEvent` (prefix `hold_`) |
| `placed_at` | String | Yes | UTC ISO-8601, first placement |
| `placed_by` | String | Yes | Opaque operator identity string (authorization policy out of scope) |
| `reason` | String | Yes | Free-text operator-supplied justification |
| `released_at` | String | No | UTC ISO-8601; present when `status = RELEASED` |
| `released_by` | String | No | Present when `status = RELEASED` |
| `hold_count` | Number | Yes | Count of place/release cycles; starts at `1` |

**Ownership:** One record per `(client_id, audit_id)`. Written on first placement via conditional put; updated on every subsequent place/release cycle.

**Lifecycle:** Created `ACTIVE` on first `place_legal_hold`. Transitions to `RELEASED` on `release_legal_hold`. May be re-placed (`RELEASED` → `ACTIVE`) any number of times; `hold_count` increments each cycle. Never deleted; never subject to `ttl_disposal_at` (a hold record is a governance artifact, not evidence).

### 7.2 `LegalHoldEvent` (immutable log)

**Purpose:** Immutable audit log of every place/release action, mirroring the platform's existing Job-log convention (`ReportJob`, `CertificationJob`, `IntelligenceJob`).

**Primary Key:**
- PK: `CLIENT#{client_id}`
- SK: `AUDIT#{audit_id}#LEGALHOLD#{hold_id}`

**Fields:** `record_type` (`legal_hold_event`), `hold_id`, `client_id`, `audit_id`, `action` (`PLACE` \| `RELEASE`), `actor`, `reason`, `timestamp`, `s3_versions_retagged_count` (Number, populated after the re-tagging sweep completes), `dynamodb_items_updated_count` (Number).

**Ownership:** Scoped to `client_id`. Written once per action via conditional put. Never mutated after write.

**Lifecycle:** Write-once, append-only. Never deleted; never subject to `ttl_disposal_at`.

### 7.3 `DisposalRecord`

**Purpose:** Durable, queryable evidence that a specific disposal action occurred — the FR-A1-5 / AC-A1-6 requirement. One record per disposed S3 object-version or DynamoDB item.

**Primary Key:**
- PK: `CLIENT#{client_id}`
- SK: `AUDIT#{audit_id}#DISPOSAL#{disposal_id}`

**Fields:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` / `SK` | String | Yes | As above |
| `record_type` | String | Yes | `disposal_record` |
| `disposal_id` | String | Yes | Opaque ID (prefix `disp_`) |
| `client_id` / `audit_id` | String | Yes | Scoping identity, extracted from the disposed item/object key |
| `evidence_class` | String | Yes | `raw_evidence` \| `aggregate_metadata` \| `intelligence` \| `report` \| `certificate` \| `metadata_generic` |
| `disposal_mechanism` | String | Yes | `S3_LIFECYCLE_EXPIRATION` \| `S3_LIFECYCLE_NONCURRENT_VERSION_EXPIRATION` \| `DYNAMODB_TTL` |
| `disposed_identity_ref` | String | Yes | S3 key (+ version id, if noncurrent) or DynamoDB `PK#SK` of the disposed item |
| `source_created_at` | String | No | Original record/object creation timestamp, when available from the event payload (`OLD_IMAGE` for DynamoDB) |
| `custody_period_days_applied` | Number | No | The custody-period value in effect at disposal, when derivable from the event payload |
| `disposed_at` | String | Yes | UTC ISO-8601; AWS's own best-available deletion timestamp (from the stream/event record) |
| `recorded_at` | String | Yes | UTC ISO-8601; when `evidenceDisposalRecorder` wrote this record (always ≥ `disposed_at`, may lag by the eventual-consistency window) |

**Ownership:** Scoped to `client_id`/`audit_id`, derived from the disposed item's own identity fields. Written once via conditional put **exclusively by `DisposalRepository`, used only by `evidenceDisposalRecorder`** — no other code path in this design (including `RetentionService`/`HoldRepository`) has a method capable of constructing this write; see Section 5.2 for the enforcing SK-write guard. Never mutated after write. **Never carries a `ttl_disposal_at` attribute** — see Non-Negotiable Invariant 1 in the companion ADR.

**Lifecycle:** Write-once, append-only, permanent (or subject to a separate, independently governed compliance-record retention policy — not the evidence custody-period mechanism this ADR defines; explicitly out of scope for A1).

### 7.4 Modified Fields on Existing Records (No Schema-Breaking Change)

Every existing DynamoDB record type that persists to `MetadataTable` (`RunMetadata`, `AggregationJob`/`AggregateSetCompletion`/aggregate records, `IntelligenceJob`/`IntelligenceMetadata`, `ReportJob`/`ReportMetadata`, `CertificationJob`/`CertificationMetadata`, and any others) gains two **additive, optional** fields:

| Field | Type | Description |
| --- | --- | --- |
| `custody_expires_at` | Number (epoch seconds) | `created_at + custody_period_seconds` for the record's evidence class; computed once at write time, never mutated by hold state changes |
| `ttl_disposal_at` | Number (epoch seconds) | The DynamoDB TTL attribute. Equal to `custody_expires_at` under normal conditions; `REMOVE`d while a legal hold is active; restored to `MAX(custody_expires_at, now)` on release |

This is additive-only per `docs/architecture/naming_and_schema_versioning.md`'s existing versioning discipline — no existing field is renamed, removed, or reinterpreted, and no existing `report_version`/`aggregation_version`/`intelligence_version`/`cert_version` schema boundary is crossed. No new record version is required for this change.

---

## 8. API Contracts

A1 introduces CLI commands only (no HTTP API exists in this platform). Each is documented using the platform's CLI-as-API convention (parser + dispatch, following `audit_platform_integrity/commands.py`).

### Command: `rcp retention hold place`

**Purpose:** Place a legal hold on an audit identity, exempting its evidence from automatic disposal.

**Authentication / Authorization:** Operator CLI access only (same trust boundary as all existing `rcp` commands). Legal hold *authorization policy* (who may invoke this) is explicitly out of scope for A1 per the Product Spec; this command performs no additional authorization check beyond existing CLI access.

**Request Parameters:** `--client-id` (required), `--audit-id` (required), `--stage` (required, `dev`\|`staging`\|`prod`), `--reason` (required, free text), `--actor` (required, opaque operator identity string).

**Request Body:** N/A (CLI arguments only).

**Response Body:** JSON/human summary: `hold_id`, `status=ACTIVE`, `placed_at`, `s3_versions_retagged_count`, `dynamodb_items_updated_count`.

**Success Status Codes:** Exit code `0`.

**Error Status Codes:** `INVALID_IDENTIFIER` (client_id/audit_id fail `validate_identifier`), `HOLD_ALREADY_ACTIVE` (idempotent no-op with a warning, not a hard failure — re-placing an active hold is safe), `STORAGE_ERROR` (DynamoDB/S3 infrastructure failure during the re-tagging sweep — see Reliability).

**Validation Rules:** `client_id`/`audit_id` validated via the existing `validate_identifier` utility. `reason` must be non-empty.

**Side Effects:** Via `HoldRepository` — writes `LegalHoldEvent` (immutable) + upserts `LegalHold` (current-state) to `ACTIVE`. Via `CustodySweepClient` — re-tags every extant S3 object version under the audit identity's key prefixes (`raw-results/`, `intelligence/`, `reports/`, `integrity/`, each scoped by `{client_id}/{audit_id}/`) to `rcp-legal-hold=true`; `UpdateItem REMOVE ttl_disposal_at` (via `_assert_custody_field_only_update()`) on every other-phase DynamoDB item under `PK=CLIENT#{client_id}`, `SK begins_with AUDIT#{audit_id}`.

**Idempotency / Duplicate Handling:** Re-invoking `place` while already `ACTIVE` is a safe no-op that re-runs the re-tagging sweep (self-healing if a prior sweep was interrupted) and writes a new `LegalHoldEvent`, incrementing `hold_count`.

### Command: `rcp retention hold release`

**Purpose:** Release an active legal hold, resuming custody-period enforcement for the audit identity's evidence.

**Authentication / Authorization:** Same as `place`.

**Request Parameters:** `--client-id`, `--audit-id`, `--stage`, `--actor` (all required).

**Response Body:** `hold_id`, `status=RELEASED`, `released_at`, counts as above.

**Success Status Codes:** Exit code `0`.

**Error Status Codes:** `INVALID_IDENTIFIER`, `HOLD_NOT_ACTIVE` (no active hold exists — hard failure, since releasing a non-existent hold is an operator error worth surfacing, not silently ignored), `STORAGE_ERROR`.

**Validation Rules:** As above.

**Side Effects:** Via `HoldRepository` — writes `LegalHoldEvent` + updates `LegalHold` to `RELEASED`. Via `CustodySweepClient` — re-tags S3 object versions back to `rcp-legal-hold=false`; restores `ttl_disposal_at = MAX(custody_expires_at, now)` on every matching other-phase DynamoDB item.

**Idempotency / Duplicate Handling:** Re-invoking `release` when already `RELEASED` returns `HOLD_NOT_ACTIVE` — not silently accepted, since a second release attempt likely indicates operator confusion about current state and `hold status` is available to check first.

### Command: `rcp retention hold status`

**Purpose:** Read-only lookup of current hold state for an audit identity.

**Authentication / Authorization:** Same as `place`/`release`; read-only, no write side effects.

**Request Parameters:** `--client-id`, `--audit-id`, `--stage` (all required).

**Response Body:** `status`, `hold_id`, `placed_at`, `released_at` (if applicable), `hold_count`.

**Success Status Codes:** Exit code `0` (including the "no hold ever placed" case, returned as `status=NEVER_HELD`, not an error).

**Error Status Codes:** `INVALID_IDENTIFIER`, `STORAGE_ERROR`.

**Side Effects:** None (read-only).

**Idempotency:** N/A — pure read.

---

## 9. Frontend Impact

None. RCP has no customer-facing or operator web UI; all interaction is via the `rcp` CLI. No UI states, components, or client-side integration apply.

---

## 10. Backend Logic

### 10.1 Responsibilities

- Ensure every write to `RawResultsBucket`/`MetadataTable`, regardless of originating phase, carries the fields/tags the disposal mechanism depends on (`rcp-legal-hold`, `rcp-evidence-class`, `custody_expires_at`, `ttl_disposal_at`).
- Orchestrate legal hold placement/release as a bulk, potentially long-running operation across both storage systems, with idempotent, resumable semantics.
- React to AWS-native disposal events (never poll or assume synchronous deletion) and produce exactly one `DisposalRecord` per disposed item/version.

### 10.2 Validation Flow

- CLI-boundary validation (`validate_identifier` on `client_id`/`audit_id`) before any `RetentionService` call, consistent with every existing CLI command in this platform (`audit_platform_integrity/commands.py`, `deterministic_reporting/report_retrieve_commands.py`).
- `evidenceDisposalRecorder` validates event provenance before writing a `DisposalRecord`: for DynamoDB Streams, only `REMOVE` events with `userIdentity.principalId == "dynamodb.amazonaws.com"` are processed (application-initiated deletes, if any exist in the future, are explicitly excluded from this path); for S3, only `s3:LifecycleExpiration:*` event names are processed.

### 10.3 Business Rules

- A `DisposalRecord` is never itself subject to `ttl_disposal_at`.
- `custody_expires_at` is set once at write time and never recomputed by hold state changes; only `ttl_disposal_at` is mutated by hold placement/release.
- S3 legal-hold tagging must cover every extant object version, not only the current version, because S3 object tags are per-version.
- Legal hold release restores `ttl_disposal_at` clamped to `MAX(custody_expires_at, now)`, never silently skipping already-elapsed custody.

### 10.4 Persistence Flow

**Sequence — evidence write path (any phase), custody fields added:**

```
Phase N repository.write_X(...)
  │
  ├─ compute custody_expires_at = created_at_epoch + custody_period_seconds[evidence_class]
  ├─ set ttl_disposal_at = custody_expires_at
  ├─ PutItem(..., custody_expires_at=..., ttl_disposal_at=...)     [DynamoDB records]
  └─ PutObject(..., Tagging="rcp-legal-hold=false&rcp-evidence-class={class}")  [S3 objects]
```

**Sequence — legal hold placement:**

```
rcp retention hold place --client-id C --audit-id A --reason "..." --actor "..."
  │
  ├─ validate_identifier(client_id, audit_id)
  ├─ RetentionService.place_legal_hold(...)   # uses HoldRepository + CustodySweepClient — no dependency on DisposalRepository
  │    ├─ HoldRepository.write_hold_event(...)   [_assert_retention_sk(sk) before write] → LegalHoldEvent (PLACE)
  │    ├─ HoldRepository.upsert_hold(...)        [_assert_retention_sk(sk) before write] → LegalHold (status=ACTIVE)
  │    ├─ CustodySweepClient.remove_ttl_disposal_at(client_id=C, audit_id=A)
  │    │    ├─ Query MetadataTable: PK=CLIENT#C, SK begins_with AUDIT#A   (other phases' SKs — RunMetadata, ReportMetadata, etc.)
  │    │    └─ for each item with ttl_disposal_at present:
  │    │         └─ _assert_custody_field_only_update(sk, expr)  →  UpdateItem REMOVE ttl_disposal_at
  │    └─ CustodySweepClient.retag_s3_versions(client_id=C, audit_id=A, legal_hold=True)
  │         └─ for each S3 prefix in {raw-results, intelligence, reports, integrity}/C/A/:
  │              └─ ListObjectVersions → for each version: PutObjectTagging(rcp-legal-hold=true)
  └─ return summary (counts)
```

**Sequence — disposal recording (TTL path):**

```
DynamoDB TTL sweep deletes item (async, best-effort, ~within 48h of ttl_disposal_at)
  │
  ▼
DynamoDB Streams REMOVE event (userIdentity.principalId = dynamodb.amazonaws.com)
  │
  ▼
evidenceDisposalRecorder Lambda
  ├─ filter: is TTL-driven REMOVE? (else discard)
  ├─ extract client_id/audit_id/evidence_class/created_at from OLD_IMAGE
  ├─ generate disposal_id
  └─ DisposalRepository.put_disposal_record(...)
       ├─ _assert_disposal_sk(sk)   # raises if sk does not target #DISPOSAL# or targets #LEGALHOLD#
       └─ PutItem DisposalRecord (conditional; disposal_mechanism=DYNAMODB_TTL)

  # on failure after exhausting MaximumRetryAttempts: event routes to evidenceDisposalRecorderDLQ
  # (DestinationConfig.OnFailure) → evidenceDisposalRecorderDLQAlarm fires on nonzero queue depth
```

**Sequence — disposal recording (S3 Lifecycle path):**

```
S3 Lifecycle daily sweep expires/deletes object (current or noncurrent version)
  │
  ▼
S3 Event Notification (s3:LifecycleExpiration:Delete / :DeleteMarkerCreated) → EventBridge
  │
  ▼
evidenceDisposalRecorder Lambda
  ├─ extract client_id/audit_id/evidence_class from S3 key path segments
  ├─ generate disposal_id
  └─ DisposalRepository.put_disposal_record(...)
       ├─ _assert_disposal_sk(sk)
       └─ PutItem DisposalRecord (conditional; disposal_mechanism=S3_LIFECYCLE_EXPIRATION | ..._NONCURRENT_VERSION_EXPIRATION)

  # on failure: EventBridge target DeadLetterConfig routes to evidenceDisposalRecorderDLQ
```

### 10.5 Error Handling

- Partial failure during a legal hold sweep (e.g., S3 re-tagging fails partway through a large object set) does not roll back already-completed steps; `place`/`release` are designed to be safely re-invoked (idempotent) to resume/complete the sweep. `LegalHoldEvent` records the counts actually achieved, not just attempted, so partial completion is observable.
- `evidenceDisposalRecorder` failures (e.g., a malformed event payload) are logged via structured logging (per `docs/architecture/structured_logging.md`) and do not block the Lambda's event source mapping from processing subsequent events; a conditional put (`attribute_not_exists`) on `DisposalRecord` guards against duplicate records if an event is redelivered (at-least-once delivery is standard for both DynamoDB Streams and EventBridge).

---

## 11. File Structure

```
src/release_confidence_platform/evidence_retention/
    __init__.py
    constants.py             # evidence_class values, tag keys, ID prefixes, SK-namespace markers
    identity.py               # generate_hold_id(), generate_disposal_id()
    models.py                  # LegalHold, LegalHoldEvent, DisposalRecord (Pydantic)
    hold_repository.py         # HoldRepository — DynamoDB only, SK-guarded to #LEGALHOLD# only (_assert_retention_sk)
                                #   [A1.1 — implemented]
    disposal_repository.py     # DisposalRepository — DynamoDB write, SK-guarded to #DISPOSAL# only (_assert_disposal_sk)
                                #   [A1.1 — implemented]
    custody_sweep_client.py     # CustodySweepClient — S3 tagging sweep + cross-phase ttl_disposal_at removal/restore;
                                 #   operation-guarded (_assert_custody_field_only_update), not SK-guarded
                                 #   [A1.2/A1.3 — new in this amendment]
    service.py                   # RetentionService — place/release orchestration (depends on HoldRepository
                                  #   AND CustodySweepClient) [A1.2/A1.3]
    disposal_recorder.py         # Lambda handler: DynamoDB Streams + S3 EventBridge event parsing (depends on
                                  #   DisposalRepository only)
    commands.py                   # rcp retention hold place|release|status CLI

apps/backend/handlers/
    evidence_disposal_recorder_handler.py   # thin Lambda entrypoint wrapping disposal_recorder.py

infra/resources/
    s3.yml            # + LifecycleConfiguration, + NotificationConfiguration (modified)
    dynamodb.yml      # + TimeToLiveSpecification, + StreamSpecification (modified)
    evidence-retention-dlq.yml  # (new) evidenceDisposalRecorderDLQ (SQS) + DLQ depth CloudWatch alarm

infra/serverless.yml  # + evidenceDisposalRecorder function (with DLQ DestinationConfig, bisectBatchOnFunctionError,
                       #   maximumRetryAttempts), + custom.custodyPeriodDays block (modified)
```

**AMENDMENT (post-A1.2, pre-A1.3 — governed revision):** the table this replaced was self-described as "confirmed, exhaustive" and named only 7 rows / 2 fully-specified methods. An independent, ground-truth investigation of the actual repository (not this document's own prior inventory) found **32 distinct write call sites** across the repo, including a dual-tree duplication hazard, three materially different regeneration patterns, and at least one write method (`AggregationRepository.update_job`) with no field allowlist at all. Product Strategy withheld A1.3 execution authorization pending this correction. The table below is the independently re-verified replacement. **It is still not labeled "exhaustive."** Per Product Strategy's explicit instruction, that label is earned only after QA independently reconciles this table against the repository as its own, separate verification step — this document's author (Solution Architect) re-verified the prior investigation's claims directly against the code (see per-row notes and the correction below), but a second independent pass is required before "exhaustive" is asserted.

**One correction to the ground-truth investigation found during re-verification:** the investigation's item 4 framed `AuditMetadataRepository` as a "dual-tree hazard" identically to `RunMetadata`'s write path. Direct inspection shows this conflates two different situations. `AuditMetadataRepository` genuinely is duplicated near-identically in `packages/storage/audit_metadata_client.py` and `src/release_confidence_platform/storage/audit_metadata_client.py`, and **both copies are live** — the `packages/` copy via Lambda handlers (`scheduled_execution_handler.py`, `audit_finalization_handler.py`, both importing `packages.storage.audit_metadata_client.AuditMetadataRepository` directly), the `src/` copy via the CLI (`operator_cli/services.py` → `AwsClientFactory` → `release_confidence_platform.storage.audit_metadata_client.AuditMetadataRepository`). This part of the finding is confirmed. However, `RunMetadata`'s write path (items 1–2 below, `DynamoDBMetadataClient.put_started_once`/`update_terminal`) is **not** dual-tree in the same way: `src/release_confidence_platform/storage/dynamodb_client.py` contains a near-identical copy of `DynamoDBMetadataClient`, but tracing every live call site (`apps/backend/handlers/orchestrator_handler.py`, which is the only Lambda that constructs a `RUN`-record client and passes it into `apps/backend/orchestrator/service.py` via dependency injection) found it is constructed exclusively from `packages.storage.dynamodb_client.DynamoDBMetadataClient` and `packages.storage.s3_client.S3StorageClient`. `src/release_confidence_platform/storage/aws_client_factory.py` — the CLI's own client factory — has no method that constructs `DynamoDBMetadataClient` at all. The `src/` copy of `DynamoDBMetadataClient`/`S3StorageClient` therefore appears to be unwired dead code for the `RUN`-record write path specifically, referenced only by test files. This distinction matters directly for this amendment's governed-record classification (§18.1) and dual-tree resolution (§18.5): `RunMetadata` is the one record type in this inventory both classified as custody-bearing (§18.1, Category 2) and touched by any "dual-tree" claim, and it turns out to have only one live write path, not two.

### Verified Write-Path Inventory (32 call sites)

Columns follow the owning-phase / source / record-type / storage / semantics / existing-condition shape requested for this amendment. **Proposed custody-metadata behavior and proposed legal-hold behavior are not repeated per row** — they are governed entirely by which of the six categories in §18.1 a row's record type is classified into, defined once there rather than 32 times here, to keep this table an auditable fact table rather than a redundant one. Applicable test coverage is defined in §18.9. Every row's Category number is a forward reference to §18.1.

**Phase 1/2/3 — raw execution evidence and audit lifecycle/scheduling (13 call sites)**

| # | Source (file :: method) | Record / Object | Storage | Semantics | Existing Condition | Category (§18.1) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `packages/storage/dynamodb_client.py::DynamoDBMetadataClient.put_started_once` (called from `apps/backend/orchestrator/service.py:102`) | RunMetadata, `PK=CLIENT#{client_id}` `SK=AUDIT#{audit_id}#RUN#{run_id}` | DynamoDB | CREATE | `attribute_not_exists(PK) AND attribute_not_exists(SK)` | 2 — evidence-derived artifact |
| 2 | `packages/storage/dynamodb_client.py::update_terminal` (called from `service.py:238,630`) | RunMetadata, same key | DynamoDB | FINALIZATION (sets `status`/`completed_at`/`raw_result_s3_key`/`failure_summary`) | `attribute_exists(PK) AND attribute_exists(SK)` | 2 |
| 3 | `packages/storage/s3_client.py::S3StorageClient.write_raw_results_once` (called from `service.py:222`) | Raw result envelope, `raw-results/{client_id}/{audit_id}/{run_id}/results.json` | S3 | CREATE (unique key every time — existence check via `object_exists` before `put_object`) | Pre-write existence check (not a DynamoDB condition; S3 has no native conditional put in this SDK usage) | 1 — governed evidence |
| 4a | `AuditMetadataRepository.put_audit_metadata_once` — live in **both** `packages/storage/audit_metadata_client.py` (Lambda handlers) and `src/release_confidence_platform/storage/audit_metadata_client.py` (CLI) — confirmed genuinely dual-tree, both live | AuditMetadata, `PK=CLIENT#{client_id}` `SK=AUDIT#{audit_id}` | DynamoDB | CREATE | `attribute_not_exists(PK) AND attribute_not_exists(SK)` | 6 — explicitly excluded / separately governed |
| 4b | `update_for_force_recreate` (`src/` only — no `packages/` caller found) | AuditMetadata, same key | DynamoDB | REGENERATION (`--force`, content replaced in place) | `lifecycle_state IN (:draft, :failed)` | 6 |
| 4c | `append_lifecycle_transition` — dual-tree live: `packages/` via `scheduled_execution_handler.py`/`audit_finalization_handler.py`; `src/` via `audit_scheduling/service.py`/`audit_lifecycle/cancellation.py` (through the CLI's `AwsClientFactory`) | AuditMetadata, same key | DynamoDB | UPDATE | `lifecycle_state = :expected_state` (true optimistic concurrency — the only row in this inventory with this pattern) | 6 |
| 4d | `set_schedules` | AuditMetadata (`schedules` field) | DynamoDB | UPDATE | `attribute_exists(PK) AND attribute_exists(SK)` | 6 |
| 4e | `update_execution_counters` | AuditMetadata (`execution_counters` field) | DynamoDB | UPDATE | `attribute_exists(PK) AND attribute_exists(SK)` | 6 |
| 4f | `record_finalization` | AuditMetadata (`finalization` field) | DynamoDB | UPDATE | `attribute_exists(PK) AND attribute_exists(SK)` | 6 |
| 4g | `record_cleanup_errors` | AuditMetadata (`cleanup_errors` field) | DynamoDB | UPDATE | `attribute_exists(PK) AND attribute_exists(SK)` | 6 |
| 4h | `put_aggregation_job_intent_once` (`packages/` only, called from `audit_finalization_handler.py`) | AggregationJobIntent — **same SK namespace as Phase 4's own AggregationJob**, `SK=AUDIT#{audit_id}#AGGJOB#{job_id}` | DynamoDB | CREATE | `attribute_not_exists(PK) AND attribute_not_exists(SK)` | 3 — operational coordination metadata |
| 4i | `update_aggregation_job_intent` (`packages/` only, same handler; delegates to `update_occurrence`) | AggregationJobIntent, same key | DynamoDB | UPDATE | `attribute_exists(PK) AND attribute_exists(SK)` | 3 |
| 4j | `claim_occurrence` (`packages/` only, `scheduled_execution_handler.py`) | ScheduleOccurrenceClaim, `SK=AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}` | DynamoDB | CREATE — the conditional put itself **is** the duplicate-delivery idempotency guard, not incidental to it | `attribute_not_exists(PK) AND attribute_not_exists(SK)` | 3 |
| 4k | `update_occurrence` (`packages/` only, same handler) | ScheduleOccurrenceClaim, same key | DynamoDB | UPDATE | `attribute_exists(PK) AND attribute_exists(SK)` | 3 |
| 5 | `S3StorageClient.write_json` via `AuditCreationService.create_from_files` (`src/` only, CLI — confirmed: `self.s3.write_json(keys[label], payload, overwrite=force)`) | Config artifacts (`client_config.json`/`audit_config.json`/`endpoints.json`), `configs/{client_id}/...` | S3 | CREATE normally; **REGENERATION/overwrite on `--force`** — the one confirmed same-key-overwrite case in the whole inventory, producing a real noncurrent S3 version | Pre-write existence check unless `overwrite=True` | 5 — configuration/input artifact |

**Phase 4 — aggregation (5 call sites, all `src/release_confidence_platform/aggregation/repository.py`, class `AggregationRepository`)**

| # | Source (file :: method) | Record / Object | Storage | Semantics | Existing Condition | Category (§18.1) |
| --- | --- | --- | --- | --- | --- | --- |
| 6 | `put_job_once` | AggregationJob, same SK as 4h | DynamoDB | CREATE (falls through to #7 as RETRY on conflict) | `attribute_not_exists(PK) AND attribute_not_exists(SK)` | 3 |
| 7 | `update_job` | AggregationJob | DynamoDB | UPDATE — **generic caller-supplied `dict[str, Any]` → dynamic SET builder, no attribute allowlist**; `_complete_job` sets up to 9 fields in one call | `attribute_exists(PK) AND attribute_exists(SK)` | 3 — see §18.7 for the required constraint on this method specifically |
| 8 | `put_records_once` | **5 record kinds in one `TransactWriteItems`**: lineage_manifest×(1+N), aggregate/audit, aggregate/failure_classification×(1+N), aggregate/endpoint×N, aggregate_set_completion — each independently conditional | DynamoDB | CREATE only, never updated after | `attribute_not_exists(PK) AND attribute_not_exists(SK)` per item, within one `TransactWriteItems` | 1 — governed evidence |
| 9 | `put_audit_execution_identity_once` | AuditExecutionIdentity, `SK=AUDIT#{audit_id}#EXECUTION_ID` | DynamoDB | CREATE (write-once identity) | `attribute_not_exists(PK) AND attribute_not_exists(SK)` | 6 |
| 10 | `put_lineage_page_once` | LineageManifestPage | DynamoDB | CREATE / retry-safe (page_hash verified on conflict) | `attribute_not_exists(PK) AND attribute_not_exists(SK)` | 1 |

**Phase 5 — reliability intelligence (6 call sites, `src/release_confidence_platform/reliability_intelligence/`)**

| # | Source (file :: method) | Record / Object | Storage | Semantics | Existing Condition | Category (§18.1) |
| --- | --- | --- | --- | --- | --- | --- |
| 11 | `repository.py::IntelligenceRepository.put_intelligence_job_once` | IntelligenceJob | DynamoDB | CREATE | `attribute_not_exists(PK) AND attribute_not_exists(SK)` | 3 |
| 12 | `update_intelligence_job` | IntelligenceJob | DynamoDB | UPDATE | **No `ConditionExpression` at all** | 3 |
| 13 | `put_intelligence_metadata_once` | IntelligenceMetadata | DynamoDB | CREATE | `attribute_not_exists(PK) AND attribute_not_exists(SK)` | 2 |
| 14 | `update_intelligence_metadata` | IntelligenceMetadata | DynamoDB | REGENERATION — **unconditional full `put_item` (whole-item overwrite)**, preserves original `created_at` by convention of the caller re-supplying it | **No `ConditionExpression` at all** | 2 — see §18.4 |
| 15 | `update_intelligence_metadata_fields` | IntelligenceMetadata | DynamoDB | UPDATE | **No `ConditionExpression` at all** | 2 |
| 16 | `publisher.py::IntelligencePublisher.write_artifact` — confirmed via `identity.py::build_s3_key`, unique key includes `intelligence_job_id` | Intelligence artifact, `intelligence/{client_id}/{audit_id}/{audit_execution_id}/...` | S3 | CREATE — unique key per job id, never overwritten even on force-regen | Pre-write existence semantics inherited from unique-key-per-invocation design | 1 |

**Phase 6 — deterministic reporting (5 call sites, `src/release_confidence_platform/deterministic_reporting/`)**

| # | Source (file :: method) | Record / Object | Storage | Semantics | Existing Condition | Category (§18.1) |
| --- | --- | --- | --- | --- | --- | --- |
| 17 | `repository.py::ReportRepository.put_report_job_once` | ReportJob | DynamoDB | CREATE | `attribute_not_exists(PK) AND attribute_not_exists(SK)` | 3 |
| 18 | `update_report_job` | ReportJob | DynamoDB | UPDATE | **No `ConditionExpression` at all** | 3 |
| 19 | `put_report_metadata_once` | ReportMetadata | DynamoDB | CREATE | `attribute_not_exists(PK) AND attribute_not_exists(SK)` | 2 |
| 20 | `update_report_metadata_fields` | ReportMetadata | DynamoDB | REGENERATION — **no full-overwrite method exists in Phase 6**; this is Phase 6's only regen path, and it is a **partial `SET`** (bumps `report_job_id`/`generation_count`/`status`/`updated_at`), asymmetric versus Phase 5's full-overwrite regen and Phase 7's unconditional full-overwrite regen | **No `ConditionExpression` at all** | 2 — see §18.4 |
| 21 | `publisher.py::ReportPublisher.write_artifact` | Report artifact, `reports/{client_id}/{audit_id}/.../{report_job_id}/artifact.json` | S3 | CREATE — unique key, never overwritten | Unique-key-per-invocation | 1 |

**Phase 7 — audit platform integrity (6 call sites, `src/release_confidence_platform/audit_platform_integrity/repository.py`, class `CertificationRepository` — already read and confirmed in a prior planning pass of this document)**

| # | Source (file :: method) | Record / Object | Storage | Semantics | Existing Condition | Category (§18.1) |
| --- | --- | --- | --- | --- | --- | --- |
| 22 | `write_certjob_pending` | CertificationJob | DynamoDB | CREATE | `attribute_not_exists(PK) AND attribute_not_exists(SK)` | 3 |
| 23 | `update_certjob_in_progress` | CertificationJob | DynamoDB | UPDATE | No `ConditionExpression` | 3 |
| 24 | `update_certjob_complete` | CertificationJob | DynamoDB | FINALIZATION | No `ConditionExpression` | 3 |
| 25 | `update_certjob_failed` | CertificationJob | DynamoDB | FINALIZATION | No `ConditionExpression` | 3 |
| 26 | `write_cert_metadata_complete` | CertificationMetadata | DynamoDB | REGENERATION on every `--force` re-cert — **fully unconditional `put_item`, no `ConditionExpression` at all**; `created_at` always reset to "now" per the method's own docstring ("MVP scope") — **the least-guarded write in the entire inventory** | **None whatsoever** | 2 — see §18.4, this is the highest-priority row for the regeneration rule |
| 27 | `publisher.py::CertificationPublisher.write_artifact` — key built via `identity.py::build_cert_s3_key`, includes `certjob_id` | Certificate artifact, `integrity/{client_id}/{audit_id}/.../{certjob_id}/artifact.json` | S3 | CREATE — unique key, never overwritten | Unique-key-per-invocation | 1 |

**Evidence Retention module — A1.1/A1.2, already implemented, not wired to any live entrypoint yet (5 call sites, confirmed by direct re-read of the merged code during this amendment)**

| # | Source (file :: method) | Record / Object | Storage | Semantics | Existing Condition | Category (§18.1) |
| --- | --- | --- | --- | --- | --- | --- |
| 28 | `hold_repository.py::HoldRepository.write_hold_event` | LegalHoldEvent | DynamoDB | CREATE, append-only | `attribute_not_exists(PK) AND attribute_not_exists(SK)`, guarded by `_assert_retention_sk` | 4 — governance metadata |
| 29 | `hold_repository.py::upsert_hold` | LegalHold | DynamoDB | CREATE + UPDATE via the same unconditional `put_item` — **same blind-overwrite pattern as #26**, by design (mirrors `write_cert_metadata_complete`'s "latest state wins" convention per its own docstring) | **None** (unconditional `put_item`), guarded by `_assert_retention_sk` | 4 |
| 30 | `disposal_repository.py::DisposalRepository.put_disposal_record` | DisposalRecord | DynamoDB | CREATE, append-only | `attribute_not_exists(PK) AND attribute_not_exists(SK)`, guarded by `_assert_disposal_sk`. **Confirmed by direct re-read: the method never accepts or sets a `ttl_disposal_at` parameter or field — ADR Non-Negotiable Invariant 1 is enforced by the method's own signature, not merely documented.** | 4 |
| 31 | `custody_sweep_client.py::CustodySweepClient.remove_ttl_disposal_at` / `restore_ttl_disposal_at` | Cross-phase `ttl_disposal_at` attribute on whatever the `Query` under an audit identity's partition returns | DynamoDB | UPDATE, one attribute (`ttl_disposal_at`) only | `_assert_custody_field_only_update` (operation-shape guard: rejects any SK containing `#LEGALHOLD#`/`#DISPOSAL#`, and rejects any `UpdateExpression` touching an attribute other than `ttl_disposal_at`) | N/A — this method is a cross-cutting sweep over *other* categories' records, not itself a record type; see §18.3 for why its "no record-type allowlist" design is correct only if §18.1's write-time classification is honored everywhere else |
| 32 | `custody_sweep_client.py::retag_s3_versions` | S3 object tags (`rcp-legal-hold`) across all four `S3_EVIDENCE_CLASS_PREFIXES` | S3 | Tag mutation only — confirmed the class has no `put_object`/`delete_object` method, enforced by both omission and an internal method allowlist (`_ALLOWED_S3_METHODS`) | N/A (tagging API, not conditional writes) | Applies to Category 1 (governed evidence) content only, by construction of `S3_EVIDENCE_CLASS_PREFIXES` (confirmed: excludes `configs/`) |

No existing method signature, return type, or write condition changes for any of the above — the two DynamoDB fields and two S3 tags remain additive-only wherever this amendment concludes they should be added (Categories 1 and 2 only; see §18.1). Categories 3, 4, 5, and 6 receive no A1.3 write-path change at all.

---

## 12. Security

- **No new external attack surface.** All new CLI commands are operator-only, at the same trust boundary as every existing `rcp` command. No customer-facing or network-exposed interface is introduced.
- **IAM scope for the new Lambda:** `evidenceDisposalRecorder` requires `dynamodb:GetRecords`/`GetShardIterator`/`DescribeStream`/`ListStreams` on `MetadataTable`'s stream ARN, `dynamodb:PutItem` scoped to `MetadataTable` (for `DisposalRecord` writes only — the Lambda has no need for `UpdateItem`/`DeleteItem`, so those actions are deliberately excluded from its role), `sqs:SendMessage` scoped to `evidenceDisposalRecorderDLQ` (for the failure-destination path — see Finding 4 fix below), and no S3 permissions beyond receiving EventBridge notifications (it never calls S3 APIs itself; all data comes from the event payload).
- **`#DISPOSAL#`/`#LEGALHOLD#` write-exclusivity — code-level guard, not an IAM boundary.** IAM's `dynamodb:PutItem`/`UpdateItem` grants below are scoped to the table as a whole; DynamoDB IAM fine-grained access control conditions on the partition key (`dynamodb:LeadingKeys`) but cannot restrict a call to items whose sort key contains a given substring, and cannot restrict an `UpdateItem` call to touching only one named attribute. The actual write-exclusivity guarantees — that only `evidenceDisposalRecorder` (via `DisposalRepository`) writes `#DISPOSAL#` items, only `RetentionService` (via `HoldRepository`) writes `#LEGALHOLD#` items, and `CustodySweepClient` may touch neither namespace while touching everything else only via `ttl_disposal_at`-only updates — are therefore enforced at the code level by `_assert_retention_sk()`, `_assert_disposal_sk()`, and `_assert_custody_field_only_update()` respectively (Section 5.2/6), mirroring `_assert_phase7_sk` in `audit_platform_integrity/repository.py:49`. This is stated explicitly rather than implied by the IAM grants, which alone would not prevent a code change to any of the three classes from accidentally writing outside its intended scope.
- **IAM scope for `HoldRepository`:** requires `dynamodb:GetItem`/`PutItem`/`UpdateItem` scoped to `MetadataTable`, used only for `LegalHold`/`LegalHoldEvent` items. No S3 permissions — `HoldRepository` has no S3-calling method.
- **IAM scope for `CustodySweepClient`:** requires `dynamodb:Query`/`UpdateItem` on `MetadataTable` (cross-phase, since it must reach other phases' SKs under an audit identity's partition) and `s3:ListBucketVersions`/`s3:GetObjectTagging`/`s3:PutObjectTagging` scoped to `RawResultsBucket`. Deliberately excludes `s3:DeleteObject`/`s3:PutObject` and `dynamodb:PutItem`/`DeleteItem` — this class only tags and updates one named attribute; it never writes or deletes evidence content or full records, preserving the Evidence Principle that raw evidence is the source of truth while within its authorized custody period.
- **No sensitive data introduced.** `DisposalRecord`/`LegalHold`/`LegalHoldEvent` fields are identifiers, timestamps, and free-text operator justification — no raw request/response bodies, headers, tokens, or PII, consistent with `phase_6_report_schema.md` §8.3's sensitive-data exclusion pattern, which this design follows by extension.
- **Sanitization boundary compliance (`adr_sanitization_boundary.md`).** `client_id`, `audit_id`, and all fields used to construct `PK`/`SK` or S3 key paths in `LegalHold`, `LegalHoldEvent`, and `DisposalRecord` are canonical identifier fields. Per that ADR, `sanitize()` must never be applied to these fields before persistence — the same incident class (UUID-substring false-positive PII redaction corrupting a persisted key) that ADR documents for Phase 3/4 applies identically here if `evidence_retention/hold_repository.py` or `evidence_retention/disposal_repository.py` were to call `sanitize()` on an item dict before `PutItem`. Both repository classes must follow the same convention already established in `audit_platform_integrity/repository.py` and `deterministic_reporting/repository.py`: `sanitize()` is reserved for structured log output and human-readable CLI rendering only, never for persistence-bound dicts.
- **Misuse risk — hold sweep as a resource-exhaustion vector.** A hold placed on an audit with an extremely large evidence footprint triggers a potentially large number of `PutObjectTagging`/`UpdateItem` calls. This is bounded by the same operator-only trust boundary as all other CLI commands; no additional rate limiting is designed here, but Reliability (Section 13) flags the operational latency characteristic this creates.

---

## 13. Reliability

- **DynamoDB TTL deletion is best-effort, typically within 48 hours of `ttl_disposal_at`, not synchronous.** `DisposalRecord.recorded_at` will lag `DisposalRecord.disposed_at` (and both may lag the true deletion instant) by this window. Any consumer of `DisposalRecord` data must treat timestamps as approximate.
- **S3 Lifecycle evaluates once per day**, not continuously. An object crossing its expiration threshold may wait up to ~24 hours before the next lifecycle evaluation cycle picks it up.
- **Legal hold placement/release on large evidence sets is not instantaneous.** The S3 re-tagging sweep is O(number of object versions under the audit identity); very large audits may take non-trivial wall-clock time. The `LegalHold`/`LegalHoldEvent` write (the authoritative "hold is active" signal) completes immediately and atomically — the sweep is best-effort follow-up work that `place`/`release` can be safely re-invoked to complete if interrupted.
- **At-least-once event delivery.** Both DynamoDB Streams and EventBridge deliver at-least-once; `evidenceDisposalRecorder` uses a conditional put (`attribute_not_exists(PK) AND attribute_not_exists(SK)`) on `DisposalRecord`, matching the existing `_put_once` pattern in `audit_platform_integrity/repository.py`, to make redelivery idempotent.
- **Failure isolation.** A failure in `evidenceDisposalRecorder` never blocks or delays the underlying disposal (TTL/Lifecycle deletion already happened by the time the event fires) — only the disposal *record* is at risk of delay/retry, never the disposal *action* itself. This bounds the blast radius of any bug in the recorder to observability, not to evidence-retention correctness.
- **Dead-letter queue and failure destination on both event sources (Finding 4 fix).** Neither event source mapping relies on default retry-then-drop behavior:
  - The DynamoDB Streams event source mapping sets a bounded `MaximumRetryAttempts`, `BisectBatchOnFunctionError: true` (so one malformed record cannot block or silently discard the rest of a batch), and `DestinationConfig.OnFailure` pointing at `evidenceDisposalRecorderDLQ` (SQS). A batch that exhausts its retry budget lands on the DLQ instead of being silently dropped.
  - The EventBridge rule delivering S3 `LifecycleExpiration` notifications configures a `DeadLetterConfig` on its Lambda target, pointing at the same `evidenceDisposalRecorderDLQ`.
  - `evidenceDisposalRecorderDLQAlarm` (CloudWatch) alarms on `ApproximateNumberOfMessagesVisible > 0` for the DLQ, so a dropped disposal-recording attempt is an alerted, operator-visible condition — closing the gap where FR-A1-5's durable-record guarantee could otherwise silently fail for a specific item while structured logs alone go unreviewed.
  - The DLQ itself is not further processed by an automated redrive in this design (out of scope for A1); an operator inspects and manually redrives or investigates DLQ contents. This is noted as a manual-intervention step, not a fully automated recovery path.
- **Monitoring:** structured log events (per `docs/architecture/structured_logging.md`) for every `evidenceDisposalRecorder` invocation, every `RetentionService.place_legal_hold`/`release_legal_hold` call, and every write failure, consistent with the platform's existing structured-logging convention.

---

## 14. Dependencies

- **Custody-period duration value(s)** — a Product Strategy decision, tracked separately (SDLC Verification Gate §9 item 6); one value per evidence class (`raw_evidence`/`intelligence`/`report`/`certificate`), which may end up identical or different across classes. The mechanism is fully designable and implementable without them; the S3 `LifecycleConfiguration` deployment step specifically cannot proceed to any stage until all four values are supplied (each of the four per-evidence-class rules requires its own concrete `Days` value — confirmed fail-closed by A1.2 QA via `sls print` variable-resolution failure, not a self-reported claim).
- **Legal hold authorization policy** (who may place/release a hold) — explicitly out of scope; flagged as Workstream B/C.
- **Custody scope decisions from Workstream B/C** (e.g., whether custody periods differ by customer contract, not just evidence class) — not resolved here; the per-evidence-class parameterization (Section 5, Decision 5 of the companion ADR) is designed to accommodate a future per-contract dimension without a code change, but that dimension itself is not designed here.
- **Every existing phase's write-path code** must be touched to add the two new fields/tags. This is a real, nontrivial cross-cutting implementation dependency spanning `packages/storage/{s3_client,dynamodb_client}.py` (Phase 1/2/3, confirmed — see Section 11), and the Phase 4/5/6/7 repository modules (Section 11). Implementation planning should sequence this explicitly (see Implementation Notes).

---

## 15. Assumptions

**Assumption requiring confirmation (backlog handling — AC-A1-8, Open Question #2):** This design recommends the enforcement mechanism apply **prospectively at minimum**, with pre-existing (pre-Workstream-A) evidence brought under enforcement via a **separate, explicit, one-time backfill migration** (a new `rcp retention backfill-custody --stage <stage>` operator-invoked command, not an automatic on-deploy action), rather than either (a) silently grandfathering the backlog indefinitely, or (b) retroactively applying the full custody period clocked from each record's *original* `created_at` (rejected — see companion ADR Alternative 5, since this could trigger a mass simultaneous disposal event the moment the mechanism activates). The recommended backfill approach clocks the backlog's custody period from **backfill-execution time**, not original creation time, so existing evidence gets the full custody-period duration from the point enforcement actually begins, giving operators a predictable, bounded window rather than an immediate mass-deletion event. **This is a recommendation only. Per the Product Spec's own Section 12 assumption, backlog handling is a distinct migration decision requiring confirmation from Architect / Product Strategy before implementation proceeds.**

**Assumption requiring confirmation (evidence_class → S3 prefix mapping completeness for Phase 4/5):** This design assumes the full set of S3 key prefixes requiring lifecycle/tagging coverage is `raw-results/`, `configs/`, `data-pools/` (Phase 1/2/3, confirmed via `packages/storage/s3_client.py` — the config/data-pool prefixes are written by `S3StorageClient.write_json`, whose `overwrite=True` path is also the one identified source of noncurrent S3 versions in this design, per the companion ADR's Decision 2 rationale), `intelligence/` (Phase 5), `reports/` (Phase 6, confirmed via `phase_6_report_schema.md` §7), and `integrity/` (Phase 7, confirmed via `audit_platform_integrity/identity.py::build_cert_s3_key`). The Phase 1/2/3 and Phase 6/7 prefixes are now confirmed by direct code inspection (Section 11); **the Phase 4 and Phase 5 S3 footprint — specifically, whether Phase 4A lineage-manifest pagination writes S3 pages outside the DynamoDB-only aggregate records this design assumed, and the exact Phase 5 intelligence artifact write path — was not independently verified during this revision** (`aggregation/` and `reliability_intelligence/` source was not read). Confirmation against actual Phase 4/5 write-path code is required before implementation.

**Resolved (previously an open assumption, now confirmed by direct code inspection):** the Phase 1/2/3 raw-evidence write path is `packages/storage/s3_client.py::S3StorageClient.write_raw_results_once` (S3) and `packages/storage/dynamodb_client.py::DynamoDBMetadataClient.put_started_once`/`update_terminal` (DynamoDB), invoked from `apps/backend/orchestrator/service.py`. This replaces the "location TBD" placeholder in the prior revision of this document and directly addresses the architecture review finding that this was the largest evidence class originally missing from scope.

---

## 16. Risks / Open Questions

- **Risk:** Cross-cutting change touching every phase's write path is the largest-blast-radius part of A1. Even though each change is additive (new optional fields/tags, no existing behavior altered), the sheer number of touched call sites raises regression risk. Mitigation: implementation should be sequenced phase-by-phase with the existing regression suite re-run after each phase's write-path change, not as one large cross-cutting commit.
- **Risk:** S3 per-version tagging at legal-hold time (`CustodySweepClient`) is not atomic across all versions of all objects under an audit identity; a hold could theoretically be "active" (per the `LegalHold` record, written by `HoldRepository`) while the S3 re-tagging sweep is still in progress, leaving a narrow window where an already-elapsed-custody object version has not yet been re-tagged and could be swept by the next daily Lifecycle evaluation before re-tagging completes. Given S3 Lifecycle only evaluates once per day, and the re-tagging sweep is expected to complete in well under 24 hours for realistic evidence volumes, this window is small but not zero; it should be explicitly covered in QA/Test Strategy for A1.
- **Risk (symmetric to the above, DynamoDB side):** the same class of race exists on the DynamoDB leg of hold placement. `LegalHold.status` is written `ACTIVE` atomically and immediately by `HoldRepository`, but `CustodySweepClient`'s subsequent `Query` (`PK=CLIENT#{client_id}`, `SK begins_with AUDIT#{audit_id}`) + per-item `UpdateItem REMOVE ttl_disposal_at` loop is not atomic across the full item set. An item whose `ttl_disposal_at` has already elapsed, and which DynamoDB's background TTL sweep reaches before this loop reaches that same item, could still be deleted despite the hold being logically "active" at the `LegalHold`-record level. Given DynamoDB TTL deletion is itself best-effort within ~48 hours (not instantaneous), and the removal loop is expected to complete in well under that window for realistic item counts, this window is small but not zero — documented here symmetrically with the S3-side race rather than omitted, and should be covered by the same QA/Test Strategy item as the S3 case.
- **Open dependency:** the exact custody-period value(s) (tracked separately, out of scope here).
- **Open dependency:** legal hold authorization policy (Workstream B/C).
- **Open question:** whether `DisposalRecord` retention itself should be time-bounded by an independent, longer-lived compliance-record retention policy, or retained permanently. Not resolved by this design; flagged for Product Strategy alongside the custody-period decision.
- **Resolved (this amendment):** the §5.2/§6 internal contradiction QA surfaced during A1.1 validation — `HoldRepository` described as performing S3 tagging and cross-phase DynamoDB updates while simultaneously being SK-guarded to reject exactly those writes. Closed by introducing `CustodySweepClient` as the named, differently-scoped component for those two operations (see Section 5.2/6/11/12). No ADR change was required — the ADR's Non-Negotiable Invariant 6 is what the strict `_assert_retention_sk()` guard was correctly upholding; only the TD's component boundaries needed naming.

---

## 17. Implementation Notes

- **A1.1 status: implemented and QA-validated (PASS WITH OBSERVATIONS)** on branch `feature/a1-1-retention-data-models-repository` — `models.py`, `hold_repository.py`, `disposal_repository.py`, and both SK guards, scoped exactly to §7.1–7.3 and correctly deferring the S3 sweep and cross-phase DynamoDB update per ADR Non-Negotiable Invariant 6. QA confirmed: model fields match §7.1–7.3 exactly, both guards are genuinely tested with real negative cases, full suite passes with no regressions (1459 passed), and no custody-period value is hardcoded. This section is amended (below) to unblock A1.2/A1.3 by naming the component A1.1 correctly deferred.
- **A1.2/A1.3 scope:** implement `custody_sweep_client.py` (`CustodySweepClient`) and `service.py` (`RetentionService`), per the amended Section 5.2/6/11/12 above. `RetentionService` must be constructed with **both** a `HoldRepository` instance and a `CustodySweepClient` instance — do not assume `HoldRepository` alone covers the sweep operations described in the original (pre-amendment) revision of this document.
- **A1.2 status: implemented and QA-validated (PASS WITH OBSERVATIONS)** on branch `feature/a1-2-retention-infrastructure` — `infra/resources/s3.yml` (four per-evidence-class `LifecycleConfiguration` rules), `infra/resources/dynamodb.yml` (TTL + Streams), the DLQ, and `custody_sweep_client.py`. QA confirmed no custody-period default exists anywhere (`sls print --stage dev` fails at variable-resolution time with eight "Value not found" errors — genuine fail-closed behavior), `CustodySweepClient`'s guards and method-allowlists are real and tested (36 tests), full suite 1505 passed/2 skipped with no regressions, and no file outside authorized A1.2 scope was touched. This section is amended (above, §3/§4; and the companion ADR's Decision 1) to correct a "single rule" wording gap QA surfaced — the four-rule, per-evidence-class design was always what Decision 5's parameterization structurally required; only the prose describing Decision 1 read ambiguously.
- Infrastructure changes (`s3.yml`, `dynamodb.yml`, `evidence-retention-dlq.yml`, `serverless.yml`) remain gated behind all four custody-period values remaining unset (i.e., code-complete and unit-tested with test-only custody-period values; none of the four per-evidence-class CFN lifecycle rules can deploy without a real value each — this must be sequenced as a separate, explicitly authorized deployment step per stage).
- **Superseded by §18.9 below.** The sequencing this bullet originally proposed treated every phase's write path as uniformly needing the tag/TTL-field change. §18 (this amendment) establishes that only Category 1 (governed evidence) and Category 2 (evidence-derived artifact) rows receive it — Categories 3, 4, 5, and 6 explicitly do not. §18.9 replaces this bullet's sequencing with the corrected, category-aware plan and proposed subphasing. This bullet is left in place, struck through in spirit rather than in markdown, purely so the document's revision history stays legible; treat §18.9 as authoritative.
- Unit-test all three guards directly — `_assert_retention_sk()`, `_assert_disposal_sk()`, and (new, for A1.2/A1.3) `_assert_custody_field_only_update()` — including negative tests asserting: `HoldRepository` cannot write a `#DISPOSAL#`-shaped item; `DisposalRepository` cannot write a `#LEGALHOLD#`-shaped item; `CustodySweepClient` cannot write to `#LEGALHOLD#` or `#DISPOSAL#`; and `CustodySweepClient`'s `UpdateItem` calls cannot touch any attribute other than `ttl_disposal_at`. Do this before any integration testing, mirroring the existing test coverage pattern for `_assert_phase7_sk` in the Phase 7 test suite and the pattern A1.1 already established for the first two guards.
- The `rcp retention backfill-custody` migration command (if the backlog assumption above is confirmed) should be implemented and tested independently of the prospective mechanism, and must require explicit operator confirmation before running (consistent with "Governance Before Implementation" — the backfill is an intentional, observable act, not a silent side effect of deployment).
- The DLQ and its alarm should be provisioned and validated (a deliberately malformed stream event / EventBridge payload routed through to confirm it lands on the DLQ and the alarm fires) before this mechanism is considered implementation-complete — a DLQ that has never been exercised is not a verified failure destination.
- QA/Test Strategy (next SDLC stage) should explicitly cover: legal hold placed/released before and after custody elapses (AC-A1-3, AC-A1-4), including both the S3-side and DynamoDB-side TOCTOU races documented in Section 16; noncurrent version expiration (AC-A1-7); disposal record creation for both S3 and DynamoDB paths, including simulated TTL-Streams events and a deliberately-failing event routed to the DLQ; idempotent re-invocation of `place`/`release`; the partial-sweep interruption/resume scenario; and the four guard negative tests listed above.

---

## 18. Governed-Record Boundary and Write-Path Governance (Amendment — A1.3 Execution Authorization Withheld Pending This Section)

**Status of this amendment:** Product Strategy withheld A1.3 execution authorization after an independent, ground-truth investigation of the actual repository found §11's write-path table — which called itself "confirmed, exhaustive" — materially incomplete (7 rows / 2 fully-specified methods versus 32 actual write call sites). §11 above has been replaced with the corrected inventory. This section is the governed revision Product Strategy required before A1.3 can be re-proposed: it defines which of the 32 call sites are actually in scope for custody-field treatment, resolves three concrete correctness gaps the fuller inventory exposed (regeneration semantics, an unconstrained update method, a dual-tree write path), and revises the implementation estimate accordingly. This is architecture work, not implementation — no code, infrastructure, or already-merged A1.1/A1.2 file is touched by this amendment.

### 18.1 Governed-Record Boundary — Six Categories

The Product Spec's original scope language ("all objects in `RawResultsBucket` and all records in `MetadataTable`, regardless of which phase wrote them") reads, taken literally, as if every DynamoDB record sharing an audit partition should receive `custody_expires_at`/`ttl_disposal_at`. §11's fuller inventory makes clear this cannot be the intended meaning: it would mean disposing of `AuditMetadata` — the canonical record that anchors an audit's existence and that every other record's SK partially depends on for interpretation — on the same clock as a single `RunMetadata` record, or disposing `ScheduleOccurrenceClaim` (a pure duplicate-delivery guard with no evidentiary content) on an "evidence" clock it was never designed to have. This is the ambiguity Product Strategy flagged. It is resolved here by classifying every record/object type found in §11 into exactly one of six categories:

**Category 1 — Governed evidence.** The four S3 evidence-class prefixes' raw content (`raw-results/`, `intelligence/`, `reports/`, `integrity/` — items 3, 16, 21, 27) plus the DynamoDB records that ARE the evidentiary payload itself, not a pointer to it: the five record kinds inside `put_records_once` (item 8 — lineage manifests, audit/endpoint/failure-classification aggregates, aggregate-set-completion marker) and `LineageManifestPage` (item 10). These are write-once, never updated after creation, and their content is the thing an audit reviewer or compliance reviewer would actually need to inspect. **Receives:** `custody_expires_at`, `ttl_disposal_at` (DynamoDB rows) or `rcp-legal-hold`/`rcp-evidence-class` tags + S3 Lifecycle rule coverage (S3 objects), `evidence_class = aggregate_metadata` for the Phase 4 DynamoDB rows, matching the already-built `EVIDENCE_CLASSES` bounded set in `evidence_retention/constants.py`.

**Category 2 — Evidence-derived artifact.** DynamoDB "pointer/summary" records whose entire content exists to reference and summarize one specific Category-1 S3 artifact, and nothing else: `RunMetadata` (items 1–2, points at the raw result envelope), `IntelligenceMetadata` (item 13–15, points at the intelligence artifact), `ReportMetadata` (item 19–20, points at the report artifact), `CertificationMetadata` (item 26, points at the certificate artifact). **Receives:** `custody_expires_at`/`ttl_disposal_at`. **Clarified per Product Strategy observation (post-§18 approval):** each Category 2 record computes `custody_expires_at` **independently, at its own write time**, from `custody_period_days.<evidence_class>.${stage}` — the same governing custody-period policy that governs the Category 1 artifact it points to — rather than reading, copying, or otherwise inheriting the sibling S3 artifact's already-computed value. This preserves deterministic behavior: each write derives its custody fields solely from its own timestamp and the shared, externally-supplied policy, with no dependency on write ordering or on a cross-write read of the other record. In ordinary operation the two independently-computed values will be effectively identical (both writes happen within the same generation event, against the same `evidence_class`), but the DynamoDB record's value is never sourced *from* the S3 object — the two are computed in parallel from the same policy, not chained. §18.4 specifies exactly how this applies on regeneration, since that is where the correctness gap this workstream exists to close actually lives. `evidence_class` matches the pointed-to artifact's class.

**Category 3 — Operational coordination metadata.** Job-log / pipeline-state / idempotency records whose purpose is entirely operational and whose content has no standalone evidentiary value once their pipeline stage completes: `AggregationJob`/`AggregationJobIntent` (items 4h–4i, 6–7), `IntelligenceJob` (11–12), `ReportJob` (17–18), `CertificationJob` (22–25), `ScheduleOccurrenceClaim` (4j–4k). **Receives:** nothing from this mechanism — no `custody_expires_at`, no `ttl_disposal_at`, no `rcp-legal-hold`, no `rcp-evidence-class`. This is a governed exclusion, not an oversight (§18.3).

**Category 4 — Governance metadata.** Records about the retention/disclosure governance mechanism itself: `LegalHold`, `LegalHoldEvent`, `DisposalRecord` (items 28–30), and any future A2 disclosure-governance records. **Receives:** nothing from this mechanism, permanently and structurally, per ADR Non-Negotiable Invariant 1 and the SK/operation guards already built in A1.1/A1.2 (§18.3).

**Category 5 — Configuration/input artifact.** `configs/*` S3 objects (item 5 — `client_config.json`, `audit_config.json`, `endpoints.json`). **Receives:** nothing from A1.3 — see §18.6 for why this must not be silently folded into scope.

**Category 6 — Explicitly excluded / separately governed.** `AuditMetadata` (items 4a–4g) and `AuditExecutionIdentity` (item 9) — the canonical audit anchor and the durable execution-identity record. Both are structurally load-bearing for every other record's referential integrity (every Category 1/2 record's SK embeds `audit_id` and/or `audit_execution_id`), and disposing either while descendant evidence survives would orphan that evidence's context. **Receives:** nothing from A1.3. Whether either should ever be disposed — and if so, under what cascading rule (e.g., "only after all descendant Category 1/2 records under this audit identity have themselves already been disposed") — is a distinct, higher-stakes decision than ordinary evidence custody and is **not decided here**.

**Assumption requiring confirmation:** Category 6's exclusion is this document's recommendation, not a settled Product Strategy decision. `AuditMetadata`/`AuditExecutionIdentity` could plausibly be argued into Category 3 (purely operational, same treatment, same non-disposal) instead of a standalone category — the practical outcome (no A1.3 custody fields) is identical either way, so this ambiguity does not block A1.3, but the *future* question of whether these records should ever be disposed under a cascading rule is explicitly unresolved and requires Product Strategy confirmation before any later workstream attempts it.

### 18.2 Why This Classification, Not a Simpler One

An earlier framing (Product Strategy's own phrasing of the ambiguity) posed the question as binary — "does X count as evidence, or is it operational?" A binary split does not survive contact with the inventory: `RunMetadata`/`IntelligenceMetadata`/`ReportMetadata`/`CertificationMetadata` are neither pure evidence (they contain no raw content) nor pure operational metadata (their entire existence is to summarize evidence for retrieval, and their custody genuinely should track the evidence they summarize) — they need their own category (2), distinct from both the raw content (1) and the job logs that produced them (3). Collapsing Category 2 into Category 1 would mean computing `custody_expires_at` independently at each of the four record types' own write time, which is exactly the design the fuller inventory shows is unsafe on regeneration (§18.4) — the pointer and the artifact it points to would drift out of lockstep. Collapsing Category 2 into Category 3 would mean these four record types never get disposed at all, silently reintroducing indefinite retention for `RunMetadata`/`IntelligenceMetadata`/`ReportMetadata`/`CertificationMetadata` — the exact defect Workstream A exists to close, and one that would be easy to miss precisely because it would look like "conservative, minimal scope" rather than a gap.

### 18.3 Structural Exclusion — Enforceable in Code, Not Convention

Category 4 (`LegalHold`/`LegalHoldEvent`/`DisposalRecord`) is **already** structurally excluded, confirmed by direct re-read during this amendment: `DisposalRepository.put_disposal_record`'s method signature has no `ttl_disposal_at` parameter at all — the exclusion is enforced by the method not accepting the field, not merely by a docstring. `HoldRepository`'s `upsert_hold`/`write_hold_event` likewise never construct an item containing `ttl_disposal_at`. No further work is needed for Category 4.

Categories 3 and 6 (job logs, `AuditMetadata`, `AuditExecutionIdentity`) have **no equivalent structural guard today**, because their write methods (items 4a–4k, 6–7, 11–12, 17–18, 22–25) are existing, locked Phase 1–7 code that this workstream does not modify (per this document's own out-of-scope statement) — retrofitting a runtime assertion into every one of those existing methods would mean touching Phase 4/5/6/7 internals for a governance concern that Category 3/6's own semantics already prevent by simple omission (these methods have never set, and under A1.3 will continue to never set, `custody_expires_at`/`ttl_disposal_at`). Adding a runtime guard to code that structurally cannot violate the invariant (because A1.3 is defined to never touch those write paths) would be exactly the kind of premature, speculative hardening this project's stated bias warns against.

**The chosen enforcement is therefore test-level, not runtime-level, for Categories 3/5/6:** a negative unit test per Category-3/5/6 write method, asserting the item constructed by that method never contains a `custody_expires_at` or `ttl_disposal_at` key. This is real, checkable enforcement (a regression in any of those methods that started setting the field would fail the test immediately) without adding a runtime assertion to code this workstream has no other reason to touch. §18.9 scopes this test list explicitly.

**One additional structural point confirmed during this amendment's re-verification:** `CustodySweepClient.remove_ttl_disposal_at`/`restore_ttl_disposal_at` (items 31) query *every* item under an audit identity's partition with no record-type allowlist at all — confirmed directly in the already-merged code (`_query_audit_items`'s own docstring states this explicitly) — and act on whatever it finds carrying (or not carrying) `ttl_disposal_at`/`custody_expires_at`. This design is **correct, not a gap**, but only on the precondition that §18.1's write-time classification is honored everywhere: `CustodySweepClient` never needs to know a record's category because Category 3/5/6 records will structurally never carry the field it looks for, by construction of their write paths never setting it. This is stated explicitly here because it is the load-bearing assumption underneath `CustodySweepClient`'s existing "no allowlist" design — if a future change ever caused a Category 3/5/6 write path to start setting `ttl_disposal_at` for an unrelated reason, `CustodySweepClient` would silently start sweeping it, with no guard to catch the mistake. The negative-test coverage in §18.9 is this precondition's actual enforcement mechanism.

### 18.4 Regeneration Semantics — One Governed Rule Across Phase 5, 6, and 7

This is a real correctness gap in the mechanism as previously scoped, not a hypothetical. §11's inventory shows three different regeneration mechanics for Category 2 records — Phase 5's `update_intelligence_metadata` (unconditional full `put_item`, item 14), Phase 6's `update_report_metadata_fields` (unconditional partial `SET`, item 20), and Phase 7's `write_cert_metadata_complete` (unconditional full `put_item`, no condition at all, item 26) — and none of them currently has any awareness of `custody_expires_at`/`ttl_disposal_at` at all, because those fields do not exist in the codebase yet. Without a single governed rule, three independent implementations of "what happens to custody fields on regen" would very likely diverge, and the specific failure mode Product Strategy called out — a full-overwrite regen silently reintroducing `ttl_disposal_at` on a record whose evidence is currently under legal hold — is exactly the kind of defect that would not surface until an actual regen-under-hold scenario occurred in production.

**The governed rule, applying identically to items 14, 20, and 26 regardless of each phase's own write mechanics (full-overwrite vs. partial-update, which this amendment does not change):**

1. **`custody_expires_at` is always freshly computed on regeneration**, from the regeneration event's own timestamp — not preserved from the prior generation. This is the correct default, not an accidental extension, because every regeneration produces a genuinely new S3 artifact at a new key with its own genuine creation time (confirmed: no Category 1/2 S3 write path ever overwrites an existing key outside the one `configs/*` exception in Category 5). A fresh `custody_expires_at` keeps the DynamoDB pointer's clock in lockstep with the new artifact it now points to, consistent with Category 2's own definition (§18.1).
2. **`ttl_disposal_at` is set conditionally on the audit identity's *current* legal-hold status, read fresh at regeneration time** (`HoldRepository.get_legal_hold(client_id, audit_id).status`), not carried forward from whatever the prior generation's value happened to be:
   - If a hold is currently `ACTIVE`: the regenerated item must **omit** `ttl_disposal_at` entirely — this is the direct fix for "a regen must never silently reintroduce the field while held."
   - If no hold is active: `ttl_disposal_at = custody_expires_at` (the freshly computed value from rule 1), identical to a first-time write.
3. **Partial-update paths (Phase 6, item 20) must explicitly include both fields in their `SET`/updates dict on every regen call** — today, Phase 6's regen path touches only `report_job_id`/`generation_count`/`status`/`updated_at`; per this rule it must be extended (in A1.3 implementation) to also explicitly set `custody_expires_at` and (conditionally) `ttl_disposal_at` on every regeneration, exactly as rules 1–2 specify. This removes the asymmetry Product Strategy flagged versus Phase 5/7's full-overwrite regen — not by making Phase 6's write mechanics match Phase 5/7's (that would mean changing Phase 6's own locked design, out of scope), but by making the *retention-field outcome* of all three phases' regen paths identical regardless of how each phase's own write mechanics get there. A partial-update path that simply never mentions `ttl_disposal_at` at all (as Phase 6's does today) is a safe default *only* for the "don't accidentally restore a removed TTL" half of the problem (DynamoDB `UpdateItem` never touches unlisted attributes) — it is not a safe default for the "the record needs a fresh custody clock reflecting its new content" half, which is why explicit inclusion is required, not merely reliance on partial-update's own not-touching-unlisted-fields behavior.
4. **Full-overwrite paths (Phase 5 item 14, Phase 7 item 26) must construct their replacement item using rules 1–2 above, every time** — since a full `put_item` replaces the entire item, omitting `ttl_disposal_at` from the new item dict when a hold is active is both necessary and sufficient (there is no "unlisted attribute" safety net the way partial-update has; a full-overwrite that forgets to omit the field will set it).
5. **Prior/superseded S3 artifacts require no special handling.** Because every S3 write is to a unique, never-reused key (confirmed across items 3, 16, 21, 27, and the one Category 5 exception), a superseded artifact continues aging off on its own original `custody_expires_at` clock, computed at its own original write time, entirely unaffected by any later regeneration of the DynamoDB pointer that now points elsewhere. No cross-referencing between the current and prior artifact is needed or proposed — this is a clean emergent property of the existing "new key per regen" design, not something this amendment has to build.
6. **Retries stay idempotent under the existing conditional-write semantics, unchanged by this rule.** For Category 1/2 CREATE paths guarded by `attribute_not_exists` (items 1, 3, 8, 9, 10, 13, 19), a retry before the first write succeeded is a fresh write with fresh custody fields — correct. A retry after a genuinely completed first write is rejected by the existing condition (`ConditionalWriteError`), leaving the original, successful write's custody fields authoritative — also correct, and this rule introduces no new retry-handling requirement beyond what items 1/3/8/9/10/13/19 already do today.

This rule is proposed as a Non-Negotiable Invariant candidate for the companion ADR — see §18.10.

### 18.5 The Dual-Tree Hazard — Resolved for A1.3, Flagged for the Future

§11's re-verification (the correction noted at the top of that section) narrows this from how it was originally framed. The genuinely dual-tree, both-live write path is `AuditMetadataRepository` (items 4a–4g, 4c specifically confirmed dual-tree-live) — but every record type that class governs is Category 3 or Category 6 (§18.1), and Categories 3/6 receive **no** custody-field treatment in A1.3 at all. `RunMetadata` — the one Category-2 record type anywhere near this hazard — was independently traced to a single live write path (`packages/storage/dynamodb_client.py`/`s3_client.py`, via `apps/backend/orchestrator/service.py`, wired exclusively by `apps/backend/handlers/orchestrator_handler.py`); the `src/release_confidence_platform/storage/` copies of `DynamoDBMetadataClient`/`S3StorageClient` were not found wired into any live caller for this record type.

**Conclusion: neither tree requires direct modification for A1.3, and no shared custody-calculation helper is justified now.** The dual-tree hazard does not block or require rework of A1.3 as scoped by §18.1, because the one class it genuinely, currently threatens (`AuditMetadataRepository`) governs only Category 3/6 records, which A1.3 does not touch. Proposing a shared component to solve a problem that does not arise for any in-scope record type would be exactly the premature abstraction this project has a stated bias against — there is no correctness requirement pulling one into existence today.

This conclusion is conditional, not permanent: if a future workstream ever decides `AuditMetadata` (or another `AuditMetadataRepository`-governed record) should move from Category 6 into a custody-bearing category, the dual-tree hazard becomes immediately load-bearing, and at that point a shared custody-calculation helper (or consolidating the two trees into one) would need to be justified on correctness grounds — both trees would need to compute identical `custody_expires_at`/`ttl_disposal_at` values from identical inputs, and two independently-maintained near-duplicate implementations are a documented risk for silent divergence. **This is flagged here as a tracked risk (§18.11), not resolved, and not acted on now.**

Separately, and outside this amendment's scope but worth recording since it surfaced during verification: `packages/storage/audit_metadata_client.py` and `src/release_confidence_platform/storage/audit_metadata_client.py` are near-byte-identical duplicate implementations of the same class today, for reasons unrelated to retention — this is a pre-existing structural characteristic of the codebase (confirmed the `rcp` CLI entrypoint is `release_confidence_platform.operator_cli.main:main`, the `src/` tree; Lambda handlers use `packages/`), not something Workstream A introduced or is positioned to fix.

### 18.6 Classifying `configs/` — Audit Input, Not Evidence, Not A1.3 Scope

`configs/*` (Category 5: `client_config.json`, `audit_config.json`, `endpoints.json`, item 5, CLI-only via `AuditCreationService.create_from_files` → `S3StorageClient.write_json`) is an **audit input artifact**, not evidence of an audit's execution outcome — it is the configuration an audit was run *against*, not a record of what happened when it ran. Confirmed by direct inspection: `evidence_retention/constants.py::S3_EVIDENCE_CLASS_PREFIXES` (the already-built, already-merged bounded list `CustodySweepClient` sweeps) does not include `configs`, and no `LifecycleConfiguration` rule in `infra/resources/s3.yml` references it. `configs/*` is also the **one confirmed same-key-overwrite case** in the entire inventory (`write_json(..., overwrite=force)`), meaning it genuinely produces noncurrent S3 versions under `--force` — a materially different lifecycle-management problem than any of the four write-once-per-key evidence classes A1.2 already built rules for.

**This document does not fold `configs/` into A1.3 scope**, per Product Strategy's explicit instruction. If `configs/*` is later judged to need its own retention/lifecycle treatment, it requires its own Lifecycle rule (a fifth rule, or a decision that configuration artifacts follow a different retention model entirely — e.g., "retained for the life of the audit, disposed only when `AuditMetadata` itself is," which would tie its disposal to the Category 6 question in §18.1 rather than to any evidence-class custody period), and its own explicit Product Strategy authorization. Not deciding this now is itself the correct scope boundary, not an oversight.

### 18.7 Constraining `AggregationRepository.update_job`

Item 7 (`update_job`) accepts a caller-supplied `dict[str, Any]` and builds a dynamic `UpdateExpression` from its keys with **no field allowlist whatsoever** — confirmed by direct re-read of `aggregation/repository.py` during this amendment: every key in the caller's dict becomes a `SET` target, unconditionally. This is Phase 4's own existing, locked update path (`AggregationJob`, Category 3 — an operational coordination record, per §18.1, that must never carry `custody_expires_at`/`ttl_disposal_at` at all), and its current design means nothing today stops a future caller — accidentally or otherwise — from passing `{"ttl_disposal_at": ...}` through this method and having it silently accepted and written.

**The required fix does not move Phase 4 update logic into the retention module** (per Product Strategy's explicit instruction to preserve Phase 4's ownership of its own update path) and does not change `update_job`'s existing signature, callers, or behavior for any field Phase 4 itself uses. It adds one thing: a **field-name rejection guard**, local to `aggregation/repository.py`, checked before the existing `UpdateExpression` is built:

```
_RETENTION_GOVERNED_FIELD_NAMES = frozenset({"ttl_disposal_at", "custody_expires_at"})

def update_job(self, key, updates):
    if _RETENTION_GOVERNED_FIELD_NAMES & updates.keys():
        raise AssertionError(
            "AggregationJob.update_job must never set retention-governed "
            f"fields {sorted(_RETENTION_GOVERNED_FIELD_NAMES & updates.keys())!r}; "
            "AggregationJob is Category 3 (operational coordination metadata) "
            "and is permanently excluded from custody-field treatment."
        )
    # ... existing UpdateExpression construction, unchanged ...
```

This is a rejection guard, not an allowlist of every legitimate field `_complete_job` and other Phase 4 callers already use — it does not need to enumerate Phase 4's own field vocabulary (which this module already owns and controls) to close the specific gap raised (retention-field smuggling through an unrestricted `dict[str, Any]`). It mirrors the existing SK-shape/operation-shape guard pattern (`_assert_phase7_sk`, `_assert_retention_sk`, `_assert_disposal_sk`, `_assert_custody_field_only_update`) already established across this codebase and this workstream, applied here as a two-item denylist rather than an allowlist, since a denylist is the minimal change that closes the gap without taking on ownership of Phase 4's full field vocabulary.

This is the only proposed code change to any existing Phase 1–7 repository method anywhere in this amendment — every other Category 1/2 write path (items 1, 3, 8, 9, 10, 13, 14, 15, 19, 20, 26) is proposed to gain fields additively (new fields, no behavior change to existing fields), which is a materially smaller-risk change than `update_job`'s unrestricted `dict[str, Any]` pattern warrants a denylist for.

**Clarified per Product Strategy observation (post-§18 approval):** this denylist is a **tactical, local protection scoped to the specific gap `update_job`'s unrestricted `dict[str, Any]` pattern creates for A1.3** — it is not intended to become a general governance-field enforcement mechanism, is not a precedent for retrofitting similar guards onto other update methods absent a comparable structural gap, and does not establish a reusable "governance field denylist" abstraction elsewhere in the codebase. If a future write path is found with the same class of defect (an unrestricted attribute dict with no allowlist, touching a Category 3/4/5/6 record type), that is a new, separately evaluated finding, not an automatic application of this pattern.

### 18.8 Backlog Migration Remains Explicitly Out of Scope

Restated, again, as Product Strategy requested: A1.3 scope excludes bulk backfill, retroactive TTL assignment, migration commands, and historical-record mutation. Nothing in this amendment changes that. §15's existing "Assumption requiring confirmation" on backlog handling (prospective-only enforcement, backfill clocked from backfill-execution time, a separate `rcp retention backfill-custody` command) stands as previously documented and is not re-litigated here — it remains a distinct, separately authorized Product Strategy decision, not something this governed revision folds into A1.3's write-path work.

### 18.9 Revised Implementation Estimate and Sequencing

**Scope correction from the file list this document previously proposed:** the prior revision implied all of Phase 1–7's write paths needed the tag/TTL-field change (7 rows). The corrected scope is **Category 1 and Category 2 rows only: items 1, 2, 3, 8, 10, 13, 14, 15, 16, 19, 20, 21, 26, 27 — 14 of the 32 call sites** — plus the one denylist guard on item 7 (§18.7), plus negative-test coverage for the remaining Category 3/5/6 items (§18.3). Item 9 (`AuditExecutionIdentity`) is Category 6 and is excluded, not Category 1/2 — it is Phase 4's other conditional-put write path but carries no evidentiary content of its own (§18.1).

This is materially smaller than either the original 7-row estimate (which was wrong in the other direction — it undercounted real call sites while also, by implication, overcounting scope by assuming uniform treatment across all 7 phases) or the raw 32-call-site inventory (most of which is now explicitly excluded by category). **The corrected scope is bounded and the smaller of the two directions of error the original estimate could have had.**

**Recommended subphasing.** Product Strategy suggested, as an example only, a four-way split (governed-record classification + shared custody calculation / Phase 1–4 / Phase 5–7 generation-regeneration / S3 tagging + cross-path validation). This document does not adopt that split automatically, per Product Strategy's own instruction. The recommended sequence, justified below:

- **A1.3a — Governed-record classification and the regeneration rule (this document).** Already complete as of this amendment; no further subphase needed to "land" §18.1/§18.4 — they are architecture, not code. The next subphase begins implementation against them.
- **A1.3b — Category 1/2 write-path integration, Phase 1/2/3 first.** Items 1, 2, 3 (`RunMetadata` + raw evidence). Single live tree (§18.5), highest evidentiary volume, and the class that originally motivated Workstream A — same priority ordering as the pre-amendment plan, still correct. Includes the `AggregationRepository.update_job` denylist guard (§18.7) as a small, independent addition within the same subphase since it touches a different module but is comparably small in scope and has no sequencing dependency on anything else.
- **A1.3c — Category 1 write-path integration, Phase 4.** Items 8, 10 (the `TransactWriteItems` aggregate/lineage records). No regeneration-semantics work needed here (Category 1 records are write-once, never updated — §18.1) — this subphase is purely additive-field work, structurally simpler than 18.3d.
- **A1.3d — Category 2 write-path integration and the regeneration rule, Phase 5/6/7.** Items 13, 14, 15, 16 (Phase 5); 19, 20, 21 (Phase 6); 26, 27 (Phase 7). Grouped together, after 18.3b/c, because this is where §18.4's governed regeneration rule actually gets implemented and is the highest-correctness-risk subphase in the corrected plan (three different regen mechanics needing an identical field-handling outcome, plus the legal-hold-status read dependency §18.4 introduces into three existing write paths). Sequencing this last, after the simpler Category 1 work in 18.3b/c has already validated the basic field-addition pattern against real regression suites, reduces the chance of conflating "does the basic additive change work" bugs with "does the regeneration rule work" bugs.
- **A1.3e — Negative-test coverage for Category 3/5/6 exclusions (§18.3) and cross-path validation.** Can run in parallel with 18.3b–d once each subphase's write paths are touched, rather than as a strictly final step — each subphase's own PR should include the negative test for the write paths it touches, closing §18.3's enforcement requirement incrementally rather than as one large trailing subphase.

This is a five-way split rather than Product Strategy's illustrative four-way one, because the corrected, category-aware scope naturally separates at the Category-1-vs-Category-2 boundary (§18.1) in a way the original phase-by-phase framing did not — Category 1 (Phase 4's `put_records_once`/`put_lineage_page_once`) genuinely has no regeneration-semantics risk and no reason to be sequenced alongside Phase 5–7's regeneration-heavy Category 2 work. Recommending the smallest sequence that preserves this real structural boundary, rather than forcing the corrected scope back into Product Strategy's four-way example, is this document's judgment call — flagged here as a recommendation, not an assumption requiring confirmation, since it is an architecture/sequencing decision within this document's own authority, not a product/business judgment call.

### 18.10 ADR Amendment Recommendation

**Recommendation: the companion ADR (`docs/architecture/adr_evidence_retention_disposal_enforcement.md`) requires amendment, but narrowly** — new Non-Negotiable Invariants only, not new Decisions or Alternatives. The governed-record-boundary classification (§18.1) and the regeneration rule (§18.4) are durable, cross-cutting correctness rules that any future implementer of A1.3 (or a later workstream touching these write paths) must not silently violate — exactly the purpose the existing Non-Negotiable Invariants section already serves (e.g., Invariant 1: "A `DisposalRecord` must never itself carry a `ttl_disposal_at` attribute"). The full 32-row inventory, the phase-by-phase table, and the implementation sequencing (§18.9) are implementation-level detail tied to today's code shape and belong in the Technical Design only, where they can be revised again without an ADR amendment if the codebase's write paths change. See the companion ADR for the three new invariants proposed as a direct result of this section (added there, not duplicated here).

### 18.11 Risks Carried Forward From This Amendment

- **Tracked, not resolved:** the `AuditMetadataRepository` dual-tree duplication (§18.5) is a real correctness risk independent of retention — two independently-maintained near-duplicate implementations of the same repository class can silently diverge in behavior over time. It does not block A1.3 (no Category 1/2 record type depends on it), but it should be tracked as separate technical debt, not closed as "resolved" by this amendment.
- **Open dependency:** the Phase 4/5 S3 footprint caveat already flagged in §15 (whether Phase 4A lineage-manifest pagination writes S3 pages, exact Phase 5 write-path module confirmation) — partially resolved by this amendment (Phase 5's `IntelligencePublisher.write_artifact` and `identity.py::build_s3_key` are now directly confirmed, item 16), but Phase 4A lineage-manifest S3 paging remains unconfirmed and should be checked before A1.3c begins.
- **Open question, deliberately not resolved here:** whether Category 6 (`AuditMetadata`, `AuditExecutionIdentity`) should ever receive a disposal mechanism of its own, and if so under what cascading rule. Flagged for a future, separately authorized workstream, not A1.3.
