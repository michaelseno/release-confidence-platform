# Technical Design

## Evidence Governance Workstream A1 — Evidence Retention Enforcement

**Status:** Planning only. No implementation, code change, or PR is authorized by this document.
**Companion ADR:** `docs/architecture/adr_evidence_retention_disposal_enforcement.md`
**Companion Product Spec:** `docs/product/evidence_governance_workstream_a_product_spec.md`

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
| FR-A1-1, AC-A1-7 | `RawResultsBucket` `LifecycleConfiguration` rule: tag-filtered `Expiration` + `NoncurrentVersionExpiration`, both scoped to `rcp-legal-hold=false` |
| FR-A1-2 | `MetadataTable` TTL attribute `ttl_disposal_at`; removed (not mutated to a sentinel) while a hold is active |
| FR-A1-3 | Custody-period value sourced from `infra/serverless.yml` `custom` per-evidence-class, per-stage config; consumed by CFN lifecycle rule and by Lambda environment variables at write time |
| FR-A1-4 | New `LegalHold` / `LegalHoldEvent` DynamoDB records; new `evidence_retention/` service re-tags S3 object versions and removes/restores `ttl_disposal_at` |
| FR-A1-5 | New `DisposalRecord` DynamoDB type, written by a new `evidenceDisposalRecorder` Lambda consuming DynamoDB Streams (TTL path) and S3 Event Notifications (Lifecycle path) |
| FR-A1-6 | Single bucket-wide lifecycle rule and single table-wide TTL attribute; no per-phase filter or opt-in required |
| AC-A1-8 | Explicit backlog recommendation below, flagged as Assumption Requiring Confirmation |

---

## 4. Technical Scope

### Current Technical Scope

- `infra/resources/s3.yml`: add `LifecycleConfiguration` to `RawResultsBucket` (tag-filtered `Expiration` + `NoncurrentVersionExpiration`); add S3 Event Notification configuration for `s3:LifecycleExpiration:*` routed to EventBridge.
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

**Confirmed, exhaustive enumeration of existing phase write paths requiring the additive tag/TTL-field change** (this replaces the prior "location TBD" placeholder — every path below was directly inspected during this revision):

| Phase | Evidence class | DynamoDB write call site | S3 write call site |
| --- | --- | --- | --- |
| 1/2/3 (raw execution evidence) | `raw_evidence` | `packages/storage/dynamodb_client.py::DynamoDBMetadataClient.put_started_once` — sole `PutItem` for `RUN` records (`custody_expires_at`/`ttl_disposal_at` computed here at record-creation time; `update_terminal`, the terminal-status transition method in the same file, must **not** recompute these fields, consistent with "computed once at write time, never mutated") | `packages/storage/s3_client.py::S3StorageClient.write_raw_results_once` — sole `PutObject` for raw evidence (tag `rcp-evidence-class=raw_evidence` is a hardcoded constant in this method, since every call to it is a raw-evidence write) |
| 1/2/3 (call sites) | — | Both methods above are invoked from `apps/backend/orchestrator/service.py` (confirmed at approximately lines 102 `put_started_once`, 222 `write_raw_results_once`, 238 and 630 `update_terminal`). No change to `orchestrator/service.py`'s item-construction logic is required if the two fields are computed inside `put_started_once`/`write_raw_results_once` themselves (centralizing the computation in the shared wrapper rather than scattering it across every orchestrator call site) — this requires `DynamoDBMetadataClient`/`S3StorageClient` to be constructed with the custody-period-per-evidence-class configuration available, which must be verified against how these clients are instantiated in the Lambda handler / orchestrator initialization path. | — |
| 4 (aggregates) | `aggregate_metadata` | `src/release_confidence_platform/aggregation/repository.py` | N/A (Phase 4 aggregate records are DynamoDB-only in the current schema; any Phase 4A lineage-manifest S3 pages, if present, require separate confirmation — see Assumptions) |
| 5 (intelligence) | `intelligence` | `src/release_confidence_platform/reliability_intelligence/repository.py` | same module or its S3-writing counterpart, to be confirmed against actual file layout at implementation time |
| 6 (reports) | `report` | `src/release_confidence_platform/deterministic_reporting/repository.py` | `src/release_confidence_platform/deterministic_reporting/publisher.py` |
| 7 (certificates) | `certificate` | `src/release_confidence_platform/audit_platform_integrity/repository.py::write_cert_metadata_complete` | same file's `publisher.py` counterpart (`CertificationPublisher`, referenced from `operator_cli/main.py`) |

No existing method signature, return type, or write condition changes for any of the above — the two DynamoDB fields and two S3 tags are additive only.

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

- **Custody-period duration value(s)** — a Product Strategy decision, tracked separately (SDLC Verification Gate §9 item 6). The mechanism is fully designable and implementable without it; the S3 `LifecycleConfiguration` deployment step specifically cannot proceed to any stage until the value is supplied (CloudFormation requires a concrete `Days` value).
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
- Implement infrastructure changes (`s3.yml`, `dynamodb.yml`, `evidence-retention-dlq.yml`, `serverless.yml`) alongside A1.2/A1.3, gated behind the custody-period value remaining unset (i.e., code-complete and unit-tested with a test-only custody-period value; the CFN lifecycle rule itself cannot deploy without a real value — this must be sequenced as a separate, explicitly authorized deployment step per stage).
- Sequence the cross-cutting write-path changes phase-by-phase, in this order, re-running each phase's existing regression suite after its write-path change before moving to the next: (1) **Phase 1/2/3** — `packages/storage/s3_client.py::write_raw_results_once` and `packages/storage/dynamodb_client.py::put_started_once` (confirmed call sites; highest-priority given this is the evidence class that originally motivated Workstream A and was missing from the initial scope); (2) Phase 4 `aggregation/repository.py`; (3) Phase 5 `reliability_intelligence/repository.py`; (4) Phase 6 `deterministic_reporting/repository.py`/`publisher.py`; (5) Phase 7 `audit_platform_integrity/repository.py`. Before this sequencing begins, implementation planning must independently verify the Phase 4/5 S3 footprint per the Assumptions section (Phase 4 lineage-manifest S3 pages, exact Phase 5 write-path module).
- Unit-test all three guards directly — `_assert_retention_sk()`, `_assert_disposal_sk()`, and (new, for A1.2/A1.3) `_assert_custody_field_only_update()` — including negative tests asserting: `HoldRepository` cannot write a `#DISPOSAL#`-shaped item; `DisposalRepository` cannot write a `#LEGALHOLD#`-shaped item; `CustodySweepClient` cannot write to `#LEGALHOLD#` or `#DISPOSAL#`; and `CustodySweepClient`'s `UpdateItem` calls cannot touch any attribute other than `ttl_disposal_at`. Do this before any integration testing, mirroring the existing test coverage pattern for `_assert_phase7_sk` in the Phase 7 test suite and the pattern A1.1 already established for the first two guards.
- The `rcp retention backfill-custody` migration command (if the backlog assumption above is confirmed) should be implemented and tested independently of the prospective mechanism, and must require explicit operator confirmation before running (consistent with "Governance Before Implementation" — the backfill is an intentional, observable act, not a silent side effect of deployment).
- The DLQ and its alarm should be provisioned and validated (a deliberately malformed stream event / EventBridge payload routed through to confirm it lands on the DLQ and the alarm fires) before this mechanism is considered implementation-complete — a DLQ that has never been exercised is not a verified failure destination.
- QA/Test Strategy (next SDLC stage) should explicitly cover: legal hold placed/released before and after custody elapses (AC-A1-3, AC-A1-4), including both the S3-side and DynamoDB-side TOCTOU races documented in Section 16; noncurrent version expiration (AC-A1-7); disposal record creation for both S3 and DynamoDB paths, including simulated TTL-Streams events and a deliberately-failing event routed to the DLQ; idempotent re-invocation of `place`/`release`; the partial-sweep interruption/resume scenario; and the four guard negative tests listed above.
