# Technical Design

## Phase 5 — Reliability Intelligence

---

## 1. Feature Overview

Phase 5 is the Reliability Intelligence layer of the Release Confidence Platform. It consumes immutable Phase 4 aggregation artifacts and derives structured, evidence-backed reliability intelligence. This intelligence is persisted as Phase 5 artifacts and consumed by Phase 6 to produce Release Confidence Reports.

Phase 5 occupies a specific position in the platform pipeline:

```
Phase 1/2/3 (Execution, Evidence Capture, Finalization)
    → Phase 4 (Aggregation — produces facts)
        → Phase 5 (Reliability Intelligence — produces interpretation)
            → Phase 6 (Deterministic Reporting — produces reports)
```

**Constitutional boundary statement:** "Aggregation owns facts. Phase 5 owns interpretation."

Phase 5 reads Phase 4 aggregation artifacts. Phase 5 writes Phase 5 intelligence artifacts. Phase 5 never mutates any Phase 4 record. Phase 5 never reads raw execution evidence. These boundaries are unconditional and cannot be waived.

This document covers all Phase 5 subphases:

| Subphase | Scope |
| --- | --- |
| 5.1 | Documentation — product spec, this technical design, Phase 5 schema, Phase 6 consumer contract |
| 5.2 | Reliability Metrics Core — per-endpoint success rate, failure classification breakdown, latency profile |
| 5.3 | Stability Analysis — distributional stability characterization of latency and success rate |
| 5.4 | Burst Analysis — distributional burst and latency spike characterization |
| 5.5 | Consistency Analysis — cross-run outcome consistency estimation |
| 5.6 | Release Confidence Scoring — deterministic composite score with evidence trace |
| 5.7 | Engineering Retrieval CLI — operator CLI for Phase 5 intelligence artifacts |
| 5.8 | Validation Campaign — live validation against Phase 4A audit data |

---

## 2. Product Requirements Summary

The following requirements from `docs/product/phase_5_reliability_intelligence_product_spec.md` govern this design:

| Requirement | Description |
| --- | --- |
| FR-P1 | Operator-invoked CLI with `AggregateSetCompletion` prerequisite gate, idempotency, and status lifecycle |
| FR-P2 | Per-endpoint reliability metrics: success rate, failure classification breakdown, latency profile, audit-level summary |
| FR-P3 | Stability analysis: success rate and latency stability labels with full methodology trace |
| FR-P4 | Burst analysis: failure burst and latency spike labels with methodology trace |
| FR-P5 | Consistency analysis: outcome consistency label with methodology trace |
| FR-P6 | Release Confidence Score: deterministic composite score with per-endpoint evidence trace and methodology disclosure |
| FR-P7 | Persistence: immutable S3 JSON artifact and DynamoDB metadata/status record; no Phase 4 mutation |
| FR-P8 | Engineering Retrieval CLI: ten read-only retrieval commands with provenance envelope |
| NFR-1 | Determinism: byte-identical output for identical inputs |
| NFR-5 | Phase 4 non-mutation: unconditional constitutional invariant |
| NFR-6 | No raw evidence access: Phase 5 reads only Phase 4 aggregation artifacts |
| NFR-7 | Methodology stability within `intel_v1` |

---

## 3. Requirement-to-Architecture Mapping

| Requirement | Architecture Decision |
| --- | --- |
| FR-P1a — CLI invocation | `rcp generate intelligence` command in `reliability_intelligence/commands.py` |
| FR-P1b — AggregateSetCompletion gate | Enforced at pipeline entry in `engine.py` via `repository.py` DynamoDB read before any intelligence computation |
| FR-P1c — Idempotency | `IntelligenceMetadata` DynamoDB record checked before computation; `--force` required to re-generate |
| FR-P1d — Status lifecycle | `IntelligenceJob` DynamoDB record with `PENDING`, `IN_PROGRESS`, `COMPLETE`, `FAILED` states |
| FR-P1e — intelligence_version | `intel_v1` carried on all artifacts; defined in `identity.py` |
| FR-P2 — Reliability Metrics | `metrics.py`: direct field reads from Phase 4 `EndpointAggregate` and `AuditAggregate` records |
| FR-P3 — Stability Analysis | `stability.py`: distributional proxy algorithms on full-window aggregate fields; methodology disclosure required |
| FR-P4 — Burst Analysis | `burst.py`: distributional proxy algorithms; explicit limitations documented in methodology trace |
| FR-P5 — Consistency Analysis | `consistency.py`: Bernoulli variance estimation from aggregate success rate |
| FR-P6 — Scoring | `scoring.py`: weighted composite of 4 analysis layers; deterministic formula with documented weights |
| FR-P7a — S3 artifact | `publisher.py`: immutable JSON write; key includes `intelligence_job_id` for per-generation uniqueness |
| FR-P7b — DynamoDB records | `repository.py`: `IntelligenceJob` and `IntelligenceMetadata` record writes |
| FR-P7c — No Phase 4 mutation | `repository.py` write paths target exclusively Phase 5-namespaced sort keys |
| FR-P8 — Retrieval CLI | `commands.py` (retrieve group): reads DynamoDB for summaries; reads S3 artifact for detail/methodology |
| NFR-1 — Determinism | `Decimal` arithmetic with documented precision; canonical sort ordering; methodology trace persisted with input values |
| NFR-5 — Phase 4 non-mutation | `repository.py` contains no write methods targeting Phase 4 sort key prefixes |
| NFR-6 — No raw evidence access | `repository.py` Phase 4 reads are limited to the patterns defined in `phase_4a_phase5_consumer_contract.md` |

---

## 4. Technical Scope

### Current Technical Scope

- New `reliability_intelligence/` module under `src/release_confidence_platform/`.
- CLI `generate intelligence` command and ten `retrieve intelligence-*` commands.
- DynamoDB: two new record types (`IntelligenceJob`, `IntelligenceMetadata`).
- S3: immutable JSON intelligence artifact written to a Phase 5-namespaced key prefix.
- Intelligence generation pipeline: prerequisite gate, metrics derivation, stability/burst/consistency analysis, scoring, persistence.
- Phase 6 consumer contract document (`docs/architecture/phase_5_phase6_consumer_contract.md`).
- Unit and integration tests for all modules.
- Phase 5.8 validation campaign against Phase 4A audit data.

### Out of Scope

- Phase 6 Deterministic Reporting implementation.
- Event-driven Lambda trigger from `AggregateSetCompletion` (deferred until after Phase 5.8 validation).
- Customer-facing intelligence export, dashboards, or visualizations.
- AI-generated or probabilistic scoring.
- Predictive analytics or cross-audit trend comparison.
- Sub-window time-series data collection (this would require a Phase 4 `agg_v2` contract amendment).
- Mutation, deletion, or re-aggregation of Phase 4 artifacts.
- New AWS resources beyond the existing DynamoDB metadata table and S3 raw-results bucket.

### Future Technical Considerations

- Sub-window temporal stability and burst analysis requires time-bucketed aggregate fields that do not exist in `agg_v1`. If temporal characterization is required in a future release, it would require an `agg_v2` contract amendment with HITL approval. This is flagged as a risk but does not block Phase 5.
- Event-driven Lambda trigger from `AggregateSetCompletion` may be introduced after Phase 5.8 confirms determinism and reproducibility.
- Cross-audit trend analysis and scoring weight tuning may be introduced in a future `intel_v2`.

---

## 5. Architecture Overview

### Platform Pipeline Position

```
Phase 4 DynamoDB
(AggregateSetCompletion, AuditAggregate,
 EndpointAggregate, FailureClassificationAggregate,
 LineageManifest)
          |
          | read-only, consumer contract boundary
          |
          v
Phase 5 Intelligence Engine
(prerequisite gate → metrics → stability → burst
 → consistency → scoring → publish)
          |
          |---> DynamoDB (IntelligenceJob, IntelligenceMetadata)
          |---> S3 (immutable intelligence artifact JSON)
          |
          v
Phase 6 (consumes Phase 5 DynamoDB + S3 artifact via Phase 6 consumer contract)
```

### Constitutional Invariants

1. Phase 5 reads Phase 4 aggregation artifacts only. It never reads raw evidence from S3, DynamoDB run metadata, or Phase 1/2/3 records.
2. Phase 5 never writes to or mutates any Phase 4 record, lineage manifest, or `AggregateSetCompletion` marker.
3. Phase 5 requires the `AggregateSetCompletion` marker with `completion_status = COMPLETE` before consuming any Phase 4 child record.
4. Phase 5 never redefines, remaps, or re-classifies Phase 4 failure classification labels.
5. All Phase 5 intelligence conclusions trace to specific Phase 4 aggregate fields via documented methodology steps. Conclusions without traceable evidence are prohibited.

### Trigger Model

Phase 5 is operator-invoked only. No event-driven Lambda trigger is in scope. The operator runs `rcp generate intelligence --client <id> --audit <id> --execution <id> --config-version <v> --aggregation-version <v>` after confirming Phase 4 aggregation is complete.

---

## 6. System Components

### `reliability_intelligence/` Module

| File | Responsibility |
| --- | --- |
| `__init__.py` | Module init |
| `engine.py` | Orchestrates the full intelligence generation pipeline; owns status transitions; catches and classifies failures |
| `metrics.py` | Per-endpoint reliability metric derivations from Phase 4 aggregate fields (5.2) |
| `stability.py` | Distributional stability label algorithms (5.3) |
| `burst.py` | Distributional burst and spike label algorithms (5.4) |
| `consistency.py` | Bernoulli variance consistency label algorithm (5.5) |
| `scoring.py` | Weighted composite score computation with per-endpoint evidence trace assembly (5.6) |
| `models.py` | Dataclass models for intelligence DTOs and DynamoDB record structures |
| `repository.py` | Phase 4 consumer reads (via Phase 5 consumer contract access patterns) and Phase 5 artifact writes to DynamoDB |
| `publisher.py` | Phase 5 S3 immutable artifact write; owns S3 key construction and artifact serialization |
| `identity.py` | Phase 5 artifact identity and versioning; `intelligence_job_id` generation; S3 key construction |
| `constants.py` | All bounded constants: `INTELLIGENCE_VERSION`, algorithm names, label values, scoring weights, thresholds |
| `events.py` | Structured log event definitions for Phase 5 pipeline stages |
| `commands.py` | CLI command definitions: `generate intelligence` and `retrieve intelligence-*` commands; argument parsing and output formatting only |
| `formatter.py` | Phase 5 retrieval output formatting (JSON and human); provenance envelope assembly |
| `filters.py` | Filter validation and application for Phase 5 retrieval commands |
| `dtypes.py` | Immutable retrieval DTO definitions for Phase 5 retrieval layer |

### Bounded Context Layering

The intelligence generation pipeline follows the same bounded context layering as Phase 4 aggregation:

```
CLI commands.py  (argument parsing + output formatting only)
    |
engine.py  (pipeline orchestration + status lifecycle)
    |
metrics.py / stability.py / burst.py / consistency.py / scoring.py
(pure computation — no I/O, no storage access)
    |
repository.py  (all DynamoDB reads and writes)
publisher.py   (S3 write only)
```

The retrieval sub-layer follows the Phase 4A retrieval pattern:

```
CLI commands.py  (argument parsing + output formatting only)
    |
RetrievalService  (read orchestration + DTO construction)
    |
repository.py  (DynamoDB reads) + publisher.py / S3 (artifact reads)
    |
formatter.py  (output serialization + provenance envelope)
```

---

## 7. Data Models

### 7.1 IntelligenceJob DynamoDB Record

**Purpose:** Tracks each intelligence generation invocation — status, timing, outcome, and S3 artifact reference. One record per invocation event. Analogous to `AggregationJob` in Phase 4.

**Sort Key:**
```
AUDIT#{audit_id}#INTJOB#{intelligence_job_id}
```

**Fields:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` | String | Yes | `CLIENT#{client_id}` |
| `SK` | String | Yes | `AUDIT#{audit_id}#INTJOB#{intelligence_job_id}` |
| `record_type` | String | Yes | `intelligence_job` |
| `client_id` | String | Yes | Validated client identifier |
| `audit_id` | String | Yes | Validated audit identifier |
| `audit_execution_id` | String | Yes | Durable execution identity |
| `config_version` | String | Yes | Configuration version |
| `aggregation_version` | String | Yes | Phase 4 aggregation version consumed (e.g., `agg_v1`) |
| `intelligence_version` | String | Yes | Phase 5 intelligence version (e.g., `intel_v1`) |
| `intelligence_job_id` | String | Yes | Opaque generated job identifier (prefix: `intjob_`) |
| `status` | String | Yes | `PENDING` \| `IN_PROGRESS` \| `COMPLETE` \| `FAILED` |
| `composite_score` | Number | No | Audit composite score; present when `status = COMPLETE` |
| `endpoint_count` | Number | No | Endpoints scored; present when `status = COMPLETE` |
| `s3_artifact_ref` | String | No | S3 key of the written intelligence artifact; present when `status = COMPLETE` |
| `aggregate_set_hash` | String | No | Hash from `AggregateSetCompletion` marker; immutable lineage link to Phase 4 |
| `is_force_regeneration` | Boolean | No | `true` if invoked with `--force`; present when applicable |
| `created_at` | String | Yes | UTC ISO-8601 creation timestamp |
| `updated_at` | String | Yes | UTC ISO-8601 last status update timestamp |
| `completed_at` | String | No | UTC ISO-8601 completion timestamp |
| `failure_stage` | String | No | Pipeline stage where failure occurred (when `status = FAILED`) |
| `failure_reason_code` | String | No | Controlled failure reason code (when `status = FAILED`) |

**Ownership:** Scoped to `client_id`. Written on each invocation. Never mutated after `COMPLETE` or `FAILED` (only the transition to the terminal state mutates the record).

**Lifecycle:** Written with `status = PENDING` at invocation start. Updated to `IN_PROGRESS` when computation begins. Terminal update to `COMPLETE` or `FAILED` at pipeline end.

---

### 7.2 IntelligenceMetadata DynamoDB Record

**Purpose:** Current-state intelligence summary for a specific `(client_id, audit_id, audit_execution_id, config_version, aggregation_version, intelligence_version)` combination. Provides the Phase 6 consumer contract anchor and the retrieval CLI with fast-path access to status, score, and S3 artifact reference without reading the full S3 artifact.

**Sort Key:**
```
AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#META
```

**Fields:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` | String | Yes | `CLIENT#{client_id}` |
| `SK` | String | Yes | As above |
| `record_type` | String | Yes | `intelligence_metadata` |
| `client_id` | String | Yes | Validated client identifier |
| `audit_id` | String | Yes | Validated audit identifier |
| `audit_execution_id` | String | Yes | Durable execution identity |
| `config_version` | String | Yes | Configuration version |
| `aggregation_version` | String | Yes | Phase 4 aggregation version consumed |
| `intelligence_version` | String | Yes | Phase 5 intelligence version |
| `intelligence_job_id` | String | Yes | Job ID of the most recent generation event |
| `status` | String | Yes | `PENDING` \| `IN_PROGRESS` \| `COMPLETE` \| `FAILED` |
| `composite_score` | Number | No | Audit composite score; present when `status = COMPLETE` |
| `endpoint_count` | Number | No | Endpoint count scored; present when `status = COMPLETE` |
| `s3_artifact_ref` | String | No | S3 key of the latest complete intelligence artifact |
| `aggregate_set_hash` | String | No | Phase 4 `AggregateSetCompletion.aggregate_set_hash`; immutable lineage link |
| `created_at` | String | Yes | UTC ISO-8601 timestamp of first generation |
| `updated_at` | String | Yes | UTC ISO-8601 timestamp of most recent state update |
| `completed_at` | String | No | UTC ISO-8601 completion timestamp of most recent generation |
| `generation_count` | Number | Yes | Count of generation events (including force re-generations); starts at `1` |
| `failure_reason_code` | String | No | Controlled failure reason code (when `status = FAILED`) |

**Ownership:** One record per `(client_id, audit_id, audit_execution_id, config_version, aggregation_version, intelligence_version)`. Written on first invocation and updated on each re-generation or status transition.

**Lifecycle:** Created when the first generation for the combination is invoked. Updated on each status transition. On force re-generation, `intelligence_job_id`, `composite_score`, `s3_artifact_ref`, `completed_at`, `updated_at`, and `generation_count` are updated to reflect the latest generation.

---

### 7.3 Sort Key Prefix Index (Phase 5 Additions)

| Prefix | Record Type |
| --- | --- |
| `AUDIT#{id}#INTJOB#{id}` | IntelligenceJob |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#INTEL#{v}#META` | IntelligenceMetadata |

Phase 5 sort key prefixes must not overlap with any Phase 4 sort key prefix. The `#INTEL#` segment is reserved for Phase 5+ records. Phase 4 consumer contract access patterns query under `#AGG#` without `#INTEL#` and therefore do not return Phase 5 records.

---

## 8. S3 Artifact Structure

### 8.1 S3 Key Pattern

Phase 5 intelligence artifacts are written to the existing S3 raw-results bucket using a Phase 5-exclusive key prefix:

```
intelligence/{client_id}/{audit_id}/{audit_execution_id}/{aggregation_version}/{intelligence_version}/{intelligence_job_id}/artifact.json
```

Example:
```
intelligence/client_abc/audit_xyz/audexec_0b1c2d3e/agg_v1/intel_v1/intjob_4f5a6b7c/artifact.json
```

The `intelligence_job_id` segment ensures each generation produces a unique, addressable S3 key. Re-generation with `--force` writes to a new key (new `intelligence_job_id`). The previous artifact is preserved at its original key. The `IntelligenceMetadata` DynamoDB record is updated to reference the latest artifact.

Phase 4 raw evidence keys use the prefix `raw-results/`. Phase 5 uses `intelligence/`. These prefixes do not overlap.

---

### 8.2 S3 Artifact JSON Schema

The S3 artifact is a single immutable JSON document written once per generation. It is the authoritative detailed record of the intelligence output. All methodology traces, evidence traces, per-endpoint details, and methodology disclosure live in this artifact.

```json
{
  "intelligence_version": "intel_v1",
  "aggregation_version": "agg_v1",
  "client_id": "<client_id>",
  "audit_id": "<audit_id>",
  "audit_execution_id": "<audit_execution_id>",
  "config_version": "<config_version>",
  "intelligence_job_id": "<intelligence_job_id>",
  "generated_at": "<UTC ISO-8601>",
  "generator_version": "<platform version string>",

  "input_lineage": {
    "aggregate_set_hash": "<hash from AggregateSetCompletion>",
    "aggregation_job_id": "<aggregation_job_id from AggregateSetCompletion>",
    "aggregation_version": "agg_v1",
    "aggregate_set_completion_created_at": "<UTC ISO-8601>",
    "endpoint_aggregate_count": "<number>",
    "source_raw_result_count": "<number>",
    "audit_lineage_manifest_ref": {
      "manifest_scope": "audit",
      "source_ref_count": "<number>",
      "manifest_hash": "<hash>"
    }
  },

  "audit_reliability_summary": {
    "total_executions": "<number>",
    "total_pass": "<number>",
    "total_fail": "<number>",
    "total_timeout": "<number>",
    "total_network_failure": "<number>",
    "audit_success_rate": "<decimal, 3 places>",
    "endpoint_count": "<number>",
    "audit_latency_mean_ms": "<number or null>",
    "audit_latency_p95_ms": "<number or null>",
    "audit_latency_p99_ms": "<number or null>",
    "source_field_refs": {
      "total_executions": "AuditAggregate.request_counts.total",
      "total_pass": "AuditAggregate.request_counts.successful",
      "total_fail": "AuditAggregate.request_counts.failed",
      "total_timeout": "AuditAggregate.request_counts.timeout",
      "total_network_failure": "AuditAggregate.request_counts.network_failure",
      "audit_latency_mean_ms": "AuditAggregate.latency_summary_ms.mean",
      "audit_latency_p95_ms": "AuditAggregate.latency_summary_ms.p95",
      "audit_latency_p99_ms": "AuditAggregate.latency_summary_ms.p99",
      "endpoint_count": "AuditAggregate.endpoint_execution_counts (distinct key count)"
    }
  },

  "composite_score": {
    "value": "<decimal, 3 places, in [0.0, 1.0]>",
    "intelligence_version": "intel_v1",
    "aggregation_version": "agg_v1",
    "aggregate_set_hash": "<hash>",
    "endpoint_count": "<number>",
    "component_breakdown": {
      "reliability": {
        "weight": 0.50,
        "value": "<decimal, 3 places>",
        "description": "Unweighted arithmetic mean of per-endpoint success rates"
      },
      "stability": {
        "weight": 0.20,
        "value": "<decimal, 3 places>",
        "description": "Mean of per-endpoint stability scores derived from stability label mappings"
      },
      "burst": {
        "weight": 0.15,
        "value": "<decimal, 3 places>",
        "description": "Mean of per-endpoint burst scores derived from burst and spike label mappings"
      },
      "consistency": {
        "weight": 0.15,
        "value": "<decimal, 3 places>",
        "description": "Mean of per-endpoint consistency scores derived from consistency label mappings"
      }
    }
  },

  "endpoints": [
    {
      "endpoint_id": "<sanitized endpoint identifier>",
      "reliability_metrics": {
        "execution_count": "<number>",
        "pass_count": "<number>",
        "fail_count": "<number>",
        "timeout_count": "<number>",
        "success_rate": "<decimal, 3 places>",
        "success_rate_numerator": "<number>",
        "success_rate_denominator": "<number>",
        "latency_min_ms": "<number or null>",
        "latency_max_ms": "<number or null>",
        "latency_mean_ms": "<number or null>",
        "latency_median_ms": "<number or null>",
        "latency_p95_ms": "<number or null>",
        "latency_p99_ms": "<number or null>",
        "latency_count": "<number>",
        "failure_classification_breakdown": {
          "<classification_label>": "<count>",
          "..."
        },
        "http_response_distribution": {
          "<status_code_or_NO_STATUS>": "<count>",
          "..."
        },
        "source_field_refs": {
          "success_rate_numerator": "EndpointAggregate.success_inputs.numerator",
          "success_rate_denominator": "EndpointAggregate.success_inputs.denominator",
          "execution_count": "EndpointAggregate.execution_count",
          "timeout_count": "EndpointAggregate.timeout_count",
          "latency_*": "EndpointAggregate.latency_distribution_ms.*",
          "failure_classification_breakdown": "FailureClassificationAggregate.classification_counts (scope=endpoint)"
        }
      },
      "stability_analysis": {
        "success_rate_stability_label": "<STABLE|DEGRADED|INSUFFICIENT_DATA>",
        "latency_stability_label": "<STABLE|DEGRADED|INSUFFICIENT_DATA>",
        "methodology_trace": {
          "algorithm": "success_rate_stability_v1",
          "algorithm_version": "intel_v1",
          "inputs": {
            "execution_count": "<number>",
            "success_rate": "<decimal>",
            "latency_count": "<number>",
            "latency_p99_ms": "<number or null>",
            "latency_mean_ms": "<number or null>",
            "latency_max_ms": "<number or null>",
            "latency_p95_ms": "<number or null>"
          },
          "thresholds": {
            "MIN_EXECUTION_COUNT": 10,
            "STABLE_THRESHOLD": 0.95,
            "MIN_LATENCY_COUNT": 5,
            "P99_MEAN_RATIO_THRESHOLD": 3.0,
            "MAX_P95_RATIO_THRESHOLD": 2.0
          },
          "intermediate_values": {
            "p99_mean_ratio": "<number or null>",
            "max_p95_ratio": "<number or null>"
          },
          "label_determination": "<human-readable explanation of which rule applied>"
        }
      },
      "burst_analysis": {
        "failure_burst_label": "<NO_BURST_DETECTED|BURST_SUSPECTED|INSUFFICIENT_DATA>",
        "latency_spike_label": "<NO_SPIKE_DETECTED|SPIKE_SUSPECTED|INSUFFICIENT_DATA>",
        "methodology_trace": {
          "algorithm": "failure_burst_v1",
          "algorithm_version": "intel_v1",
          "inputs": {
            "execution_count": "<number>",
            "timeout_count": "<number>",
            "latency_count": "<number>",
            "latency_p99_ms": "<number or null>",
            "latency_max_ms": "<number or null>"
          },
          "thresholds": {
            "MIN_EXECUTION_COUNT": 10,
            "TIMEOUT_BURST_THRESHOLD": 0.20,
            "MIN_LATENCY_COUNT": 5,
            "MAX_P99_RATIO_THRESHOLD": 3.0
          },
          "intermediate_values": {
            "timeout_proportion": "<decimal or null>",
            "max_p99_ratio": "<decimal or null>"
          },
          "label_determination": "<human-readable explanation of which rule applied>"
        }
      },
      "consistency_analysis": {
        "consistency_label": "<CONSISTENT|INCONSISTENT|INSUFFICIENT_DATA>",
        "methodology_trace": {
          "algorithm": "outcome_consistency_v1",
          "algorithm_version": "intel_v1",
          "inputs": {
            "execution_count": "<number>",
            "success_rate": "<decimal>",
            "success_rate_numerator": "<number>",
            "success_rate_denominator": "<number>"
          },
          "thresholds": {
            "MIN_EXECUTION_COUNT": 10,
            "VARIANCE_CONSISTENT_THRESHOLD": 0.05
          },
          "intermediate_values": {
            "outcome_variance": "<decimal or null>"
          },
          "label_determination": "<human-readable explanation of which rule applied>"
        }
      },
      "endpoint_score": {
        "composite_score": "<decimal, 3 places>",
        "reliability_score": "<decimal, 3 places>",
        "stability_score": "<decimal, 3 places>",
        "burst_score": "<decimal, 3 places>",
        "consistency_score": "<decimal, 3 places>",
        "score_derivation": {
          "reliability_score_source": "success_rate",
          "stability_score_formula": "(label_to_value(sr_stability) + label_to_value(lat_stability)) / 2.0",
          "burst_score_formula": "(label_to_value(failure_burst) + label_to_value(spike)) / 2.0",
          "consistency_score_formula": "label_to_value(consistency)"
        }
      }
    }
  ],

  "methodology_disclosure": {
    "intelligence_version": "intel_v1",
    "scoring": {
      "composite_score_range": "[0.0, 1.0]",
      "rollup": "Unweighted arithmetic mean of per-endpoint composite scores",
      "precision": "3 decimal places, half-up rounding via Python Decimal",
      "component_weights": {
        "reliability": 0.50,
        "stability": 0.20,
        "burst": 0.15,
        "consistency": 0.15
      },
      "per_endpoint_formula": "0.50 * reliability_score + 0.20 * stability_score + 0.15 * burst_score + 0.15 * consistency_score"
    },
    "stability_label_definitions": {
      "STABLE": "Aggregate distributional indicators are consistent with stable behavior",
      "DEGRADED": "Aggregate distributional indicators are inconsistent with stable behavior",
      "INSUFFICIENT_DATA": "Execution or latency count below minimum threshold for characterization"
    },
    "burst_label_definitions": {
      "NO_BURST_DETECTED": "Distributional proxy signals do not indicate concentrated failure events",
      "BURST_SUSPECTED": "Distributional proxy signals are consistent with concentrated failure events",
      "INSUFFICIENT_DATA": "Execution count below minimum threshold for burst characterization",
      "NO_SPIKE_DETECTED": "Latency distribution does not indicate isolated spike events",
      "SPIKE_SUSPECTED": "Max/p99 latency divergence is consistent with isolated spike events"
    },
    "consistency_label_definitions": {
      "CONSISTENT": "Bernoulli outcome variance p*(1-p) is at or below 0.05, indicating predominantly uniform outcomes",
      "INCONSISTENT": "Bernoulli outcome variance p*(1-p) exceeds 0.05, indicating mixed pass/fail outcomes",
      "INSUFFICIENT_DATA": "Execution count below minimum threshold for consistency estimation"
    },
    "label_to_score_mapping": {
      "STABLE": 1.0,
      "DEGRADED": 0.0,
      "INSUFFICIENT_DATA": 0.5,
      "CONSISTENT": 1.0,
      "INCONSISTENT": 0.0,
      "NO_BURST_DETECTED": 1.0,
      "BURST_SUSPECTED": 0.0,
      "NO_SPIKE_DETECTED": 1.0,
      "SPIKE_SUSPECTED": 0.0
    },
    "limitations": [
      "agg_v1 provides full-window aggregates without time-bucketed sub-totals. Stability and burst labels characterize distributional properties of the full observation window. Temporal sub-window trends, degradation onset times, and burst timing attribution cannot be determined from agg_v1 inputs.",
      "Consistency is estimated using the Bernoulli variance formula p*(1-p). This reflects outcome variance at the aggregate level only. Per-run or per-scenario consistency is not assessable from agg_v1.",
      "Burst detection uses timeout proportion as the primary proxy signal. High timeout rates are consistent with concentrated outage events but do not confirm temporal clustering.",
      "Latency spike detection uses the max/p99 ratio. A high ratio indicates extreme outlier presence but does not characterize spike frequency, duration, or timing.",
      "Component scoring weights (0.50/0.20/0.15/0.15) reflect the relative importance of reliability over temporal characterization given agg_v1 data fidelity. Weights are fixed within intel_v1.",
      "Composite score is an unweighted arithmetic mean across endpoints. High-volume endpoints are not weighted more heavily than low-volume endpoints in intel_v1.",
      "The composite score is an evidence-backed assessment, not a pass/fail gate. Release decisions require human review."
    ]
  }
}
```

---

## 9. Reliability Metrics Methodology (Phase 5.2)

Phase 5.2 derives per-endpoint and audit-level reliability metrics by reading Phase 4 aggregate fields directly. No re-computation, re-aggregation, or re-classification of raw evidence is performed.

### 9.1 Per-Endpoint Success Rate

| Output Field | Derivation | Source |
| --- | --- | --- |
| `success_rate` | `success_inputs.numerator / success_inputs.denominator` (3 decimal places) | `EndpointAggregate` |
| `execution_count` | `EndpointAggregate.execution_count` | `EndpointAggregate` |
| `pass_count` | `success_inputs.numerator` | `EndpointAggregate` |
| `fail_count` | `execution_count - pass_count` | Derived |
| `timeout_count` | `EndpointAggregate.timeout_count` | `EndpointAggregate` |
| `success_rate_numerator` | `success_inputs.numerator` (retained for traceability) | `EndpointAggregate` |
| `success_rate_denominator` | `success_inputs.denominator` (retained for traceability) | `EndpointAggregate` |

**Edge cases:**
- `success_inputs.denominator = 0`: success rate is labeled `INSUFFICIENT_DATA`; no numeric value is computed; no divide-by-zero error is raised. The condition is recorded in the artifact.
- `execution_count = 0`: all per-endpoint fields set to zero or null; stability/burst/consistency labels set to `INSUFFICIENT_DATA`.

### 9.2 Per-Endpoint Failure Classification Breakdown

The complete `classification_counts` map from the endpoint-scoped `FailureClassificationAggregate` record is carried through without renaming, remapping, or augmentation. Source record coordinates (`aggregate_type`, `scope`, `endpoint_id`) are included in the artifact for traceability.

If no `FailureClassificationAggregate` record exists for an endpoint with non-zero `EndpointAggregate.execution_count`, this condition is flagged as a data inconsistency in the artifact. The failure classification breakdown is omitted and the anomaly is recorded in the methodology trace.

### 9.3 Per-Endpoint Latency Profile

| Output Field | Source Field |
| --- | --- |
| `latency_min_ms` | `EndpointAggregate.latency_distribution_ms.min` |
| `latency_max_ms` | `EndpointAggregate.latency_distribution_ms.max` |
| `latency_mean_ms` | `EndpointAggregate.latency_distribution_ms.mean` |
| `latency_median_ms` | `EndpointAggregate.latency_distribution_ms.median` |
| `latency_p95_ms` | `EndpointAggregate.latency_distribution_ms.p95` |
| `latency_p99_ms` | `EndpointAggregate.latency_distribution_ms.p99` |
| `latency_count` | `EndpointAggregate.latency_distribution_ms.count` |

All latency values are carried at Phase 4 precision (3 decimal places). Phase 5 does not re-compute, adjust, or round latency values. Values are `null` when `latency_count = 0`, per `agg_v1` semantic guarantee.

### 9.4 Audit-Level Reliability Summary

| Output Field | Source Field |
| --- | --- |
| `total_executions` | `AuditAggregate.request_counts.total` |
| `total_pass` | `AuditAggregate.request_counts.successful` |
| `total_fail` | `AuditAggregate.request_counts.failed` |
| `total_timeout` | `AuditAggregate.request_counts.timeout` |
| `total_network_failure` | `AuditAggregate.request_counts.network_failure` |
| `audit_success_rate` | `request_counts.successful / request_counts.total` (3 decimal places) |
| `endpoint_count` | Distinct key count in `AuditAggregate.endpoint_execution_counts` |
| `audit_latency_mean_ms` | `AuditAggregate.latency_summary_ms.mean` |
| `audit_latency_p95_ms` | `AuditAggregate.latency_summary_ms.p95` |
| `audit_latency_p99_ms` | `AuditAggregate.latency_summary_ms.p99` |

---

## 10. Stability Analysis Methodology (Phase 5.3)

### Data Availability Design Decision

`agg_v1` `EndpointAggregate` records contain full-window summary statistics. No time-bucketed sub-totals, per-run breakdowns, or ordered sequence data is available in the Phase 5 consumer contract.

**Design decision:** Phase 5.3 implements distributional stability proxies rather than temporal sub-window analysis. All stability labels characterize the distributional properties of the full-window aggregate. Temporal claims ("the endpoint degraded in the second half of the window") are NOT made and are NOT possible from `agg_v1` inputs.

This decision is documented in the methodology disclosure and is not a deficiency to be hidden — it is an explicit documented boundary of `intel_v1`. If temporal stability characterization is required in a future release, it requires a Phase 4 `agg_v2` contract amendment introducing time-bucketed aggregate fields.

No Phase 4 contract amendment is required for Phase 5 to proceed.

### 10.1 Success Rate Stability Algorithm (`success_rate_stability_v1`)

**Algorithm name:** `success_rate_stability_v1`
**Version:** `intel_v1`

**Inputs:**
- `execution_count` from `EndpointAggregate`
- `success_rate` computed in Phase 5.2
- `success_inputs.denominator` from `EndpointAggregate`

**Thresholds:**

| Threshold | Value | Meaning |
| --- | --- | --- |
| `MIN_EXECUTION_COUNT` | `10` | Below this, `INSUFFICIENT_DATA` |
| `STABLE_THRESHOLD` | `0.95` | Success rate at or above this → `STABLE` |

**Logic:**
```
1. If execution_count < MIN_EXECUTION_COUNT: return INSUFFICIENT_DATA
2. If success_inputs.denominator = 0: return INSUFFICIENT_DATA
3. If success_rate >= STABLE_THRESHOLD: return STABLE
4. Else: return DEGRADED
```

**Methodology disclosure note:** "STABLE indicates the aggregate success rate meets or exceeds 0.95 across the full observation window. DEGRADED indicates the aggregate success rate is below 0.95, reflecting meaningful failure volume. Temporal sub-window degradation — whether success rate declined from the first half to the second half of the window — cannot be determined from `agg_v1` full-window aggregates."

### 10.2 Latency Stability Algorithm (`latency_stability_v1`)

**Algorithm name:** `latency_stability_v1`
**Version:** `intel_v1`

**Inputs:**
- `latency_count` from `EndpointAggregate.latency_distribution_ms.count`
- `latency_p99_ms`, `latency_mean_ms`, `latency_max_ms`, `latency_p95_ms` from `EndpointAggregate.latency_distribution_ms`

**Thresholds:**

| Threshold | Value | Meaning |
| --- | --- | --- |
| `MIN_LATENCY_COUNT` | `5` | Below this, `INSUFFICIENT_DATA` |
| `P99_MEAN_RATIO_THRESHOLD` | `3.0` | p99/mean above this → high distributional spread |
| `MAX_P95_RATIO_THRESHOLD` | `2.0` | max/p95 above this → outlier tail presence |

**Logic:**
```
1. If latency_count < MIN_LATENCY_COUNT OR latency_mean_ms is null: return INSUFFICIENT_DATA
2. Compute p99_mean_ratio = latency_p99_ms / latency_mean_ms (if mean > 0, else skip to step 4)
3. If p99_mean_ratio > P99_MEAN_RATIO_THRESHOLD: return DEGRADED
4. Compute max_p95_ratio = latency_max_ms / latency_p95_ms (if p95 > 0, else skip to step 6)
5. If max_p95_ratio > MAX_P95_RATIO_THRESHOLD: return DEGRADED
6. Return STABLE
```

**Methodology disclosure note:** "Latency stability is assessed using distributional spread ratios as proxies. A high p99/mean ratio indicates that the 99th percentile is substantially higher than average, consistent with variable latency. A high max/p95 ratio indicates extreme tail presence. These are distributional characterizations. Temporal attribution — whether latency increased over time — is not possible from `agg_v1`."

---

## 11. Burst Analysis Methodology (Phase 5.4)

### Data Availability Design Decision

Same constraint as Section 10: no time-bucketed data is available. Burst detection uses distributional proxy signals, as explicitly specified in FR-P4b. The methodology must document what signals are used and what claims can and cannot be made.

### 11.1 Failure Burst Algorithm (`failure_burst_v1`)

**Algorithm name:** `failure_burst_v1`
**Version:** `intel_v1`

**Inputs:**
- `execution_count` from `EndpointAggregate`
- `timeout_count` from `EndpointAggregate`

**Thresholds:**

| Threshold | Value | Meaning |
| --- | --- | --- |
| `MIN_EXECUTION_COUNT` | `10` | Below this, `INSUFFICIENT_DATA` |
| `TIMEOUT_BURST_THRESHOLD` | `0.20` | Timeout proportion above this → `BURST_SUSPECTED` |

**Logic:**
```
1. If execution_count < MIN_EXECUTION_COUNT: return INSUFFICIENT_DATA
2. Compute timeout_proportion = timeout_count / execution_count
3. If timeout_proportion > TIMEOUT_BURST_THRESHOLD: return BURST_SUSPECTED
4. Return NO_BURST_DETECTED
```

**Rationale for signal choice:** Timeouts in API reliability audits tend to cluster temporally. When a service becomes unavailable or severely degraded for a period, requests during that window all timeout while requests outside that window respond normally. A high aggregate timeout proportion (>20%) is therefore a meaningful proxy signal for concentrated outage events, even without per-window data.

**What this signal can claim:** The endpoint had a timeout rate exceeding 20%, which is consistent with concentrated service unavailability events.

**What this signal cannot claim:** When within the observation window the burst occurred, how many distinct burst events occurred, or whether failures were genuinely clustered vs uniformly distributed.

### 11.2 Latency Spike Algorithm (`latency_spike_v1`)

**Algorithm name:** `latency_spike_v1`
**Version:** `intel_v1`

**Inputs:**
- `latency_count` from `EndpointAggregate.latency_distribution_ms.count`
- `latency_p99_ms`, `latency_max_ms` from `EndpointAggregate.latency_distribution_ms`

**Thresholds:**

| Threshold | Value | Meaning |
| --- | --- | --- |
| `MIN_LATENCY_COUNT` | `5` | Below this, `INSUFFICIENT_DATA` |
| `MAX_P99_RATIO_THRESHOLD` | `3.0` | max/p99 above this → `SPIKE_SUSPECTED` |

**Logic:**
```
1. If latency_count < MIN_LATENCY_COUNT OR latency_p99_ms is null: return INSUFFICIENT_DATA
2. If latency_p99_ms = 0: return INSUFFICIENT_DATA
3. Compute max_p99_ratio = latency_max_ms / latency_p99_ms
4. If max_p99_ratio > MAX_P99_RATIO_THRESHOLD: return SPIKE_SUSPECTED
5. Return NO_SPIKE_DETECTED
```

**Rationale:** If the maximum observed latency is 3x or more above the 99th percentile, it indicates that the top 1% of requests experienced substantially higher latency than the already-high p99 boundary — consistent with isolated spike events affecting a small number of requests.

---

## 12. Consistency Analysis Methodology (Phase 5.5)

### Data Availability Design Decision

`agg_v1` provides no per-run breakdown. Individual run-level consistency (whether the same endpoint consistently passes or fails across independent runs) cannot be directly assessed. Phase 5.5 implements outcome variance estimation using the Bernoulli model as a proxy for aggregate-level consistency.

### 12.1 Outcome Consistency Algorithm (`outcome_consistency_v1`)

**Algorithm name:** `outcome_consistency_v1`
**Version:** `intel_v1`

**Inputs:**
- `execution_count` from `EndpointAggregate`
- `success_rate` computed in Phase 5.2
- `success_inputs.numerator`, `success_inputs.denominator` from `EndpointAggregate`

**Thresholds:**

| Threshold | Value | Meaning |
| --- | --- | --- |
| `MIN_EXECUTION_COUNT` | `10` | Below this, `INSUFFICIENT_DATA` |
| `VARIANCE_CONSISTENT_THRESHOLD` | `0.05` | Bernoulli variance at or below this → `CONSISTENT` |

**Logic:**
```
1. If execution_count < MIN_EXECUTION_COUNT OR success_inputs.denominator = 0: return INSUFFICIENT_DATA
2. Let p = success_rate
3. Compute outcome_variance = p * (1 - p)
4. If outcome_variance <= VARIANCE_CONSISTENT_THRESHOLD: return CONSISTENT
5. Return INCONSISTENT
```

**Threshold semantics:** `p * (1-p) <= 0.05` is satisfied when `p >= 0.947` or `p <= 0.053`. An endpoint that passes in at least 94.7% of executions or fails in at least 94.7% of executions produces consistent outcomes. An endpoint in the middle range (e.g., 50% success rate) is flagged as `INCONSISTENT`.

**Note on CONSISTENT-but-low-success-rate:** An endpoint with `p = 0.02` (2% success rate) returns `CONSISTENT` by this algorithm. This is correct: the endpoint consistently fails. The methodology trace records the `success_rate` value, so a reviewer can distinguish a consistently high-performing endpoint from a consistently low-performing one.

**Methodology disclosure note:** "Consistency is estimated using the Bernoulli variance formula `p*(1-p)` where `p` is the aggregate success rate from `agg_v1`. A `CONSISTENT` label means the endpoint produced predominantly uniform outcomes (either predominantly passing or predominantly failing). Per-run consistency — whether the same endpoints pass in the same runs — cannot be assessed from `agg_v1` full-window aggregates."

---

## 13. Release Confidence Scoring Methodology (Phase 5.6)

### 13.1 Score Range and Representation

The composite score is a decimal value in `[0.0, 1.0]` with 3 decimal places using half-up rounding via Python `Decimal`. A higher score indicates greater evidence-backed confidence in releasing the API. The score is NOT a pass/fail gate. Phase 5 does not make release recommendations.

### 13.2 Label-to-Score Mapping Table

All label values are mapped to numeric scores via the following deterministic table:

| Label | Score Value |
| --- | --- |
| `STABLE` | `1.0` |
| `DEGRADED` | `0.0` |
| `INSUFFICIENT_DATA` (stability) | `0.5` |
| `CONSISTENT` | `1.0` |
| `INCONSISTENT` | `0.0` |
| `INSUFFICIENT_DATA` (consistency) | `0.5` |
| `NO_BURST_DETECTED` | `1.0` |
| `BURST_SUSPECTED` | `0.0` |
| `INSUFFICIENT_DATA` (burst) | `0.5` |
| `NO_SPIKE_DETECTED` | `1.0` |
| `SPIKE_SUSPECTED` | `0.0` |
| `INSUFFICIENT_DATA` (spike) | `0.5` |

`INSUFFICIENT_DATA` maps to `0.5` (neutral) in all cases: the absence of evidence does not penalize or reward the endpoint.

### 13.3 Per-Endpoint Scoring Formula

**Step 1 — Reliability score:**
```
reliability_score = success_rate
```
If `success_inputs.denominator = 0` or `execution_count = 0`: `reliability_score = 0.0`.

**Step 2 — Stability score:**
```
sr_val = label_to_score[success_rate_stability_label]
lat_val = label_to_score[latency_stability_label]
stability_score = round((sr_val + lat_val) / 2.0, 3)
```

**Step 3 — Burst score:**
```
burst_val = label_to_score[failure_burst_label]
spike_val = label_to_score[latency_spike_label]
burst_score = round((burst_val + spike_val) / 2.0, 3)
```

**Step 4 — Consistency score:**
```
consistency_score = label_to_score[consistency_label]
```

**Step 5 — Endpoint composite score:**
```
endpoint_score = round(
    0.50 * reliability_score +
    0.20 * stability_score +
    0.15 * burst_score +
    0.15 * consistency_score,
    3
)
```

Component weights:

| Component | Weight | Rationale |
| --- | --- | --- |
| Reliability (success rate) | `0.50` | Primary direct signal of API correctness |
| Stability | `0.20` | Distributional consistency proxy; secondary signal |
| Burst | `0.15` | Concentrated event proxy; tertiary signal |
| Consistency | `0.15` | Outcome variance; complements reliability |
| **Total** | **1.00** | |

### 13.4 Audit Composite Score Rollup

```
audit_score = round(sum(endpoint_scores) / len(endpoint_scores), 3)
```

Rollup method: unweighted arithmetic mean across all scored endpoints. All endpoints contribute equally regardless of execution count. This is explicitly documented in methodology disclosure.

**Edge case:** If no endpoints exist (audit with zero endpoint aggregates): `audit_score = 0.0`; this condition is flagged in the artifact.

### 13.5 Scoring Constraints

- All arithmetic uses Python `Decimal` with `ROUND_HALF_UP` to ensure reproducibility.
- No AI-generated conclusions, probabilistic models trained on historical data, or threshold values without explicit documentation are permitted.
- Weights, thresholds, and formulas defined in Section 13 constitute the complete `intel_v1` scoring specification. These must not change within `intel_v1` after validation.

### 13.6 Score Label Assignment

`score_label` is assigned from the fully-computed, rounded `audit_score`. The assignment order is invariant:

1. Compute `audit_score` via the rollup formula (Section 13.4).
2. Round `audit_score` to 3 decimal places using `Decimal` `ROUND_HALF_UP`.
3. Assign `score_label` from the **rounded** value using the thresholds below.

**Score label thresholds:**

| Label | Condition | Threshold Constants |
| --- | --- | --- |
| `HIGH_CONFIDENCE` | `rounded_audit_score >= HIGH_CONFIDENCE_THRESHOLD` | `HIGH_CONFIDENCE_THRESHOLD = 0.80` |
| `MODERATE_CONFIDENCE` | `rounded_audit_score >= MODERATE_CONFIDENCE_THRESHOLD` | `MODERATE_CONFIDENCE_THRESHOLD = 0.50` |
| `LOW_CONFIDENCE` | `rounded_audit_score < MODERATE_CONFIDENCE_THRESHOLD` | — |

**Example:** `audit_score = 0.7995` → rounded to `0.800` → `0.800 >= 0.80` → `HIGH_CONFIDENCE`.

`HIGH_CONFIDENCE_THRESHOLD` and `MODERATE_CONFIDENCE_THRESHOLD` must be defined in `constants.py`. No inline magic numbers are permitted in `scoring.py`.

### 13.7 intel_v1 Constants Reference

All `intel_v1` constants must be defined in `constants.py`. The following is the authoritative reference:

| Constant | Value | Used In |
| --- | --- | --- |
| `MIN_EXECUTION_COUNT` | `10` | All algorithms — INSUFFICIENT_DATA gate |
| `MIN_LATENCY_COUNT` | `5` | `latency_stability_v1`, `latency_spike_v1` — INSUFFICIENT_DATA gate |
| `STABLE_THRESHOLD` | `0.95` | `success_rate_stability_v1` — STABLE/DEGRADED boundary |
| `P99_MEAN_RATIO_THRESHOLD` | `3.0` | `latency_stability_v1` — p99/mean spread proxy |
| `MAX_P95_RATIO_THRESHOLD` | `2.0` | `latency_stability_v1` — max/p95 outlier proxy |
| `TIMEOUT_BURST_THRESHOLD` | `0.20` | `failure_burst_v1` — BURST_SUSPECTED boundary |
| `MAX_P99_RATIO_THRESHOLD` | `3.0` | `latency_spike_v1` — SPIKE_SUSPECTED boundary |
| `VARIANCE_CONSISTENT_THRESHOLD` | `0.05` | `outcome_consistency_v1` — INCONSISTENT boundary |
| `HIGH_CONFIDENCE_THRESHOLD` | `0.80` | `scoring.py` — HIGH_CONFIDENCE label boundary |
| `MODERATE_CONFIDENCE_THRESHOLD` | `0.50` | `scoring.py` — MODERATE_CONFIDENCE label boundary |

No algorithm module may define threshold constants inline. All constants must be imported from `constants.py`.

---

## 14. Phase 6 Consumer Contract

Phase 5.1 must publish a formal Phase 6 consumer contract document at `docs/architecture/phase_5_phase6_consumer_contract.md`. This document governs what Phase 6 may consume from Phase 5. The following section defines the boundary this technical design establishes.

### 14.1 Phase 6 Constitutional Statement

**Reliability Intelligence owns interpretation. Phase 6 owns reporting.**

Phase 6 may consume Phase 5 intelligence artifacts to produce Release Confidence Reports. Phase 6 must not re-derive, re-score, or re-interpret any Phase 5 intelligence conclusion. Phase 6 must not read Phase 4 aggregation artifacts directly for reporting purposes.

### 14.2 What Phase 6 May Consume

**From DynamoDB:**
- `IntelligenceMetadata` record: status, composite_score, endpoint_count, s3_artifact_ref, aggregate_set_hash, intelligence_version, aggregation_version, completed_at
- Phase 6 must require `IntelligenceMetadata.status = COMPLETE` before consuming any Phase 5 intelligence. This is the Phase 6 prerequisite gate, analogous to Phase 5's `AggregateSetCompletion` gate.

**From S3 (via s3_artifact_ref):**
All sections of the S3 intelligence artifact defined in Section 8.2:
- `intelligence_version`, `aggregation_version`, `input_lineage`
- `audit_reliability_summary`
- `composite_score` (and component breakdown)
- `endpoints[*]` — all per-endpoint sections: reliability_metrics, stability_analysis, burst_analysis, consistency_analysis, endpoint_score
- `methodology_disclosure`

### 14.3 What Phase 6 Must Not Do

- Re-derive success rates, stability labels, burst labels, consistency labels, or composite scores from Phase 4 aggregate inputs.
- Access Phase 4 aggregation artifacts directly (DynamoDB or S3 raw evidence).
- Modify or extend Phase 5 intelligence artifacts.
- Read `IntelligenceJob` records (internal Phase 5 implementation detail).
- Bypass the `IntelligenceMetadata.status = COMPLETE` prerequisite gate.
- Interpret structured logs as authoritative intelligence evidence.

### 14.4 Stable Fields for Phase 6 Consumption

All fields defined in the S3 artifact schema (Section 8.2) and the `IntelligenceMetadata` DynamoDB record (Section 7.2) are stable for Phase 6 consumption within `intel_v1`. Breaking changes require a new `intelligence_version` and a formal Phase 6 consumer contract amendment with HITL approval.

### 14.5 Compatibility Gate

A `tests/unit/test_phase6_consumer_contract.py` compatibility gate test must be created in Phase 5.1. It validates that all stable fields defined above are present and correctly typed in a fixture intelligence artifact. This test blocks Phase 5 implementation changes that would break Phase 6 compatibility.

---

## 15. Intelligence Generation Pipeline

### 15.1 Step-by-Step Pipeline

The following describes the complete intelligence generation pipeline executed by `engine.py` on operator invocation.

**Step 1 — CLI invocation and input validation**

Operator invokes:
```
rcp generate intelligence \
    --client <client_id> \
    --audit <audit_id> \
    --execution <audit_execution_id> \
    --config-version <config_version> \
    --aggregation-version <aggregation_version> \
    [--dry-run] [--force] [--output json|human]
```

`commands.py` validates argument presence and format. Passes validated parameters to `engine.py`.

**Step 2 — Idempotency check**

`engine.py` calls `repository.py` to query for an existing `IntelligenceMetadata` record for the scoped combination.

- If no record exists: proceed to Step 3.
- If record exists with `status = COMPLETE` and `--force` not provided: return existing metadata to operator; terminate without generation. Emit `intelligence_already_exists` structured log event.
- If record exists with `status = IN_PROGRESS`: return error `INTELLIGENCE_GENERATION_IN_PROGRESS`; terminate without generation.
- If record exists with `status = FAILED` (or `PENDING`): treat as a retryable situation; proceed to Step 3 with the same `intelligence_job_id` if available, or generate a new one.
- If `--force` provided and record exists with `status = COMPLETE`: generate new `intelligence_job_id`; proceed to Step 3; update records on completion.

If `--dry-run`: proceed to Step 3 (prerequisite gate check) and Step 4 (Phase 4 record query) only; do not compute, do not write; report prerequisite gate result to operator.

**Step 3 — AggregateSetCompletion prerequisite gate**

`engine.py` calls `repository.py` to query the `AggregateSetCompletion` marker for the specified `(client_id, audit_id, audit_execution_id, config_version, aggregation_version)`.

- If marker is absent: emit `intelligence_prerequisite_gate_failed` structured log event; return structured error `AGGREGATE_SET_COMPLETION_ABSENT`; terminate without writing any Phase 5 artifact.
- If marker is present but `completion_status != COMPLETE`: return structured error `AGGREGATE_SET_COMPLETION_NOT_COMPLETE`; terminate.
- If marker is present with `completion_status = COMPLETE`: proceed.

**Step 4 — Write PENDING status record**

`engine.py` directs `repository.py` to write the `IntelligenceJob` record with `status = PENDING` and the `IntelligenceMetadata` record with `status = PENDING`. Emit `intelligence_generation_pending` structured log event.

**Step 5 — Load Phase 4 aggregate records**

`repository.py` queries DynamoDB for all Phase 4 aggregate records in the set using the query pattern from the Phase 5 consumer contract:

```
PK = CLIENT#{client_id}
SK begins_with AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#
```

Records loaded: `AuditAggregate`, all `EndpointAggregate` records, all `FailureClassificationAggregate` records (audit and endpoint scope).

**Step 6 — Update status to IN_PROGRESS**

`engine.py` directs `repository.py` to update both records to `status = IN_PROGRESS`. Emit `intelligence_generation_in_progress` structured log event.

**Step 7 — Compute reliability metrics (5.2)**

`metrics.py` derives per-endpoint success rates, failure classification breakdowns, and latency profiles. Computes audit-level reliability summary. Returns `EndpointMetricsDTO` list and `AuditMetricsDTO`. All computations use `Decimal` arithmetic.

**Step 8 — Compute stability analysis (5.3)**

`stability.py` runs `success_rate_stability_v1` and `latency_stability_v1` for each endpoint. Returns per-endpoint stability labels and methodology traces.

**Step 9 — Compute burst analysis (5.4)**

`burst.py` runs `failure_burst_v1` and `latency_spike_v1` for each endpoint. Returns per-endpoint burst labels and methodology traces.

**Step 10 — Compute consistency analysis (5.5)**

`consistency.py` runs `outcome_consistency_v1` for each endpoint. Returns per-endpoint consistency labels and methodology traces.

**Step 11 — Compute release confidence score (5.6)**

`scoring.py` computes per-endpoint scores using the label-to-score mapping table and the weighted formula. Computes audit composite score. Assembles per-endpoint evidence traces and audit-level score summary. Returns `IntelligenceScoreDTO`.

**Step 12 — Assemble full intelligence artifact**

`engine.py` assembles the complete S3 artifact JSON document from all analysis outputs, lineage references from the `AggregateSetCompletion` marker, and the `methodology_disclosure` section.

**Step 13 — Write S3 artifact**

`publisher.py` writes the serialized artifact JSON to the S3 key:
```
intelligence/{client_id}/{audit_id}/{audit_execution_id}/{aggregation_version}/{intelligence_version}/{intelligence_job_id}/artifact.json
```

S3 write uses server-side encryption and the existing bucket configuration. If S3 write fails, `engine.py` catches the exception and proceeds to Step 14 failure handling.

**Step 14 — Write COMPLETE DynamoDB records**

`repository.py` updates both `IntelligenceJob` and `IntelligenceMetadata` records with:
- `status = COMPLETE`
- `composite_score`, `endpoint_count`, `s3_artifact_ref`, `aggregate_set_hash`, `completed_at`
- `generation_count` incremented on `IntelligenceMetadata`

Emit `intelligence_generation_complete` structured log event.

**Step 15 — Return result to operator**

`engine.py` returns summary to `commands.py`, which formats and outputs according to `--output json|human`.

### 15.2 Failure Handling

If any step from 7–13 raises an exception:
- `engine.py` classifies the failure stage.
- `repository.py` updates both DynamoDB records to `status = FAILED` with `failure_stage` and `failure_reason_code`.
- Emit `intelligence_generation_failed` structured log event with `failure_stage` and `failure_reason_code`.
- Return structured error to operator.

If Step 13 (S3 write) fails after Step 12 (artifact assembly): DynamoDB records are updated to `FAILED`. No partial S3 artifact is left. The next invocation can retry.

If Step 14 (DynamoDB COMPLETE write) fails after Step 13 (S3 write succeeds): The S3 artifact exists but DynamoDB shows no `COMPLETE` record. The operator may re-invoke (no `--force` needed since the previous invocation's DynamoDB status is `FAILED`). Re-invocation will re-compute and re-write — the previous S3 artifact key is orphaned but not overwritten (new `intelligence_job_id` on re-invocation).

---

## 16. Operator CLI Contract

All Phase 5 CLI commands are registered under the existing `rcp` operator CLI infrastructure. `commands.py` in the `reliability_intelligence/` module registers both the generation command and all retrieval commands.

### 16.1 Generation Command

**Command:** `rcp generate intelligence`

**Arguments:**

| Argument | Required | Description |
| --- | --- | --- |
| `--client <client_id>` | Yes | Scoped client identifier |
| `--audit <audit_id>` | Yes | Scoped audit identifier |
| `--execution <audit_execution_id>` | Yes | Durable execution identity |
| `--config-version <config_version>` | Yes | Configuration version |
| `--aggregation-version <aggregation_version>` | Yes | Phase 4 aggregation version to consume (e.g., `agg_v1`) |
| `--stage <dev|staging|prod>` | Yes | Deployment stage |
| `--dry-run` | No | Validate prerequisites without writing artifacts |
| `--force` | No | Re-generate and overwrite existing complete artifacts |
| `--output <json|human>` | No | Output format (default: `human`) |

**Success output includes:** `intelligence_job_id`, `status`, `composite_score`, `endpoint_count`, `s3_artifact_ref`, `aggregate_set_hash`, `completed_at`.

### 16.2 Retrieval Commands

All retrieval commands follow the pattern:
```
rcp retrieve <intelligence-command> \
    --client <client_id> \
    --audit <audit_id> \
    --execution <audit_execution_id> \
    --stage <dev|staging|prod> \
    [--output json|human] \
    [--endpoint <endpoint_id>] \
    [--intelligence-version <version>]
```

| Command | Data Source | Returns |
| --- | --- | --- |
| `retrieve intelligence-status` | DynamoDB | Status, `intelligence_job_id`, `composite_score`, `endpoint_count`, `s3_artifact_ref`, `completed_at` |
| `retrieve intelligence-summary` | DynamoDB | Audit-level score summary, component breakdown, `aggregate_set_hash`, `intelligence_version` |
| `retrieve intelligence-score` | DynamoDB | Composite score, component breakdown, weights, methodology version |
| `retrieve intelligence-endpoints` | S3 artifact | Per-endpoint reliability metrics for all or `--endpoint`-filtered endpoint |
| `retrieve intelligence-stability` | S3 artifact | Per-endpoint stability labels and methodology traces |
| `retrieve intelligence-burst` | S3 artifact | Per-endpoint burst and spike labels and methodology traces |
| `retrieve intelligence-consistency` | S3 artifact | Per-endpoint consistency labels and methodology traces |
| `retrieve intelligence-evidence-trace` | S3 artifact | Per-endpoint evidence traces with Phase 4 source field references |
| `retrieve intelligence-methodology` | S3 artifact | Full `methodology_disclosure` section |
| `retrieve intelligence-lineage` | DynamoDB + S3 | `aggregate_set_hash`, `aggregation_job_id`, `audit_lineage_manifest_ref`, lineage chain back to Phase 4 |

**Provenance envelope** (required on all retrieval output):
```json
{
  "_notice": "This output is for engineering diagnostics only. Authoritative intelligence resides in the immutable Phase 5 S3 artifact.",
  "retrieved_at": "<UTC ISO-8601>",
  "retrieval_version": "<retrieval layer version>",
  "intelligence_version": "<intel_v1>",
  "aggregation_version": "<agg_v1>",
  "aggregate_set_hash": "<hash>",
  "audit_id": "<audit_id>",
  "client_id": "<client_id>",
  "data": { ... }
}
```

**Read-only invariant:** Phase 5 retrieval commands must not modify any Phase 5 or Phase 4 persisted artifact. Unconditional.

**Retrieval data source routing:** Commands that return only summary/status data read from DynamoDB (`IntelligenceMetadata`). Commands that return per-endpoint analysis details or methodology traces read the S3 artifact via `publisher.py`. This allows DynamoDB-only fast-path for summary queries while keeping per-endpoint methodology detail in the authoritative S3 artifact.

---

## 17. Idempotency and Re-generation

### 17.1 Default Behavior (No `--force`)

If an `IntelligenceMetadata` record exists with `status = COMPLETE` for the specified combination:
- Generation is skipped entirely.
- Operator is notified with existing metadata: `intelligence_job_id`, `created_at`, `completed_at`, `intelligence_version`, `composite_score`.
- No Phase 5 artifacts are written or modified.
- This is not an error; it is the expected idempotent behavior.

### 17.2 Force Re-generation (`--force`)

When `--force` is provided and a `COMPLETE` record exists:
1. A new `intelligence_job_id` is generated.
2. All pipeline steps execute against the same Phase 4 inputs.
3. A new S3 artifact is written to a new key (new `intelligence_job_id` in path).
4. The previous S3 artifact is NOT deleted. It remains at its original key.
5. `IntelligenceMetadata` is updated to reference the new `intelligence_job_id`, `s3_artifact_ref`, `completed_at`, and incremented `generation_count`.
6. A new `IntelligenceJob` record is written for the re-generation event.

The operator can retrieve previous artifacts directly via S3 if the old key is known.

### 17.3 Concurrent Generation Protection

If `IntelligenceMetadata` has `status = IN_PROGRESS`:
- New invocation (with or without `--force`) returns error `INTELLIGENCE_GENERATION_IN_PROGRESS`.
- No action is taken.
- This is a soft protection for the operator-invoked CLI. Full distributed lock protection is not required for Phase 5 given the CLI trigger model.

### 17.4 Retry After FAILED Status

If `IntelligenceMetadata` has `status = FAILED`:
- New invocation without `--force` is allowed; a new `intelligence_job_id` is generated and the pipeline runs.
- `--force` is not required for retry after failure. `--force` is only required to overwrite a successful `COMPLETE` artifact.

---

## 18. File Structure

```text
src/release_confidence_platform/
  reliability_intelligence/
    __init__.py
    commands.py         (CLI: generate intelligence + retrieve intelligence-* commands)
    engine.py           (Pipeline orchestration; status lifecycle; exception handling)
    metrics.py          (5.2 — per-endpoint reliability metric derivation)
    stability.py        (5.3 — stability label algorithms)
    burst.py            (5.4 — burst and spike label algorithms)
    consistency.py      (5.5 — consistency label algorithm)
    scoring.py          (5.6 — composite score computation; evidence trace assembly)
    models.py           (DTOs: EndpointMetricsDTO, StabilityResultDTO, BurstResultDTO,
                          ConsistencyResultDTO, ScoreDTO, IntelligenceArtifactDTO,
                          IntelligenceJobRecord, IntelligenceMetadataRecord)
    repository.py       (Phase 4 consumer reads; Phase 5 DynamoDB writes)
    publisher.py        (S3 artifact write and read; key construction)
    identity.py         (intelligence_job_id generation; S3 key construction; intel_v1 version constant)
    constants.py        (INTELLIGENCE_VERSION, algorithm names, label values,
                          scoring weights, all thresholds)
    events.py           (structured log event definitions for Phase 5)
    formatter.py        (Phase 5 retrieval output formatting; provenance envelope assembly)
    filters.py          (filter validation for Phase 5 retrieval commands)
    dtypes.py           (immutable retrieval DTOs for Phase 5 retrieval layer)

tests/unit/
  reliability_intelligence/
    test_metrics.py                 (5.2 derivation correctness; edge cases; denominator=0)
    test_stability.py               (5.3 label determinism; threshold boundary conditions)
    test_burst.py                   (5.4 label determinism; threshold boundary conditions)
    test_consistency.py             (5.5 label determinism; variance boundary conditions)
    test_scoring.py                 (5.6 component scores; composite formula; rollup)
    test_engine.py                  (pipeline orchestration; gate enforcement; status transitions)
    test_engine_gate.py             (AggregateSetCompletion gate enforcement; negative cases)
    test_engine_no_phase4_mutation.py  (Phase 4 non-mutation assertion against fixtures)
    test_repository.py              (DynamoDB read/write DTOs; Phase 4 access patterns)
    test_publisher.py               (S3 key construction; artifact serialization)
    test_identity.py                (intelligence_job_id format; version constants)
    test_determinism.py             (byte-identical artifact for identical inputs; two invocations)
    test_evidence_trace.py          (per-endpoint trace completeness)
    test_methodology_disclosure.py  (disclosure section completeness; all required fields)
    test_commands.py                (CLI argument parsing; output format)
    test_formatter.py               (provenance envelope; canonical ordering; JSON and human)
    test_retrieval_read_only.py     (retrieval commands make no writes)
    test_phase6_consumer_contract.py  (compatibility gate for Phase 6 consumer contract)

tests/integration/
  test_phase5_generation_integration.py   (full pipeline against fixture Phase 4 records)
  test_phase5_retrieval_integration.py    (retrieval commands against known intelligence state)

docs/architecture/
  phase_5_reliability_intelligence_technical_design.md  ← this document
  phase_5_phase6_consumer_contract.md                   ← Phase 5.1 deliverable

docs/product/
  phase_5_reliability_intelligence_product_spec.md
```

---

## 19. Security

### Data Boundaries

Phase 5 operates within the same sanitization boundary defined in `docs/architecture/adr_sanitization_boundary.md`:

- S3 intelligence artifact must not contain raw request/response bodies, headers, cookies, tokens, credentials, PII, raw URLs, query strings, or payload content.
- `endpoint_id` values in Phase 5 artifacts are inherited from Phase 4 sanitized identifiers. Phase 5 must not un-sanitize or expand them.
- `failure_classification_counts` keys are inherited from Phase 4 classification labels — these are controlled bounded labels, not user-supplied strings.
- Composite score and analysis labels carry no sensitive data.

### Access Control

- Phase 5 generation and retrieval CLI commands require IAM-authorized internal operator access. No public API surface is introduced.
- Phase 5 S3 artifact writes use the existing S3 bucket IAM configuration for the `intelligence/` prefix. No new IAM roles or policies are required for Phase 5 CLI-invoked generation.
- Phase 5 retrieval commands are read-only. No write permissions are required beyond those already held for Phase 5 generation.

### Input Validation

- All CLI arguments are validated against existing `validate_identifier` utilities before use in DynamoDB key construction.
- `aggregation_version` is validated against the bounded set of known versions (`agg_v1`) before Phase 4 record query.
- `intelligence_version` is fixed to `intel_v1` from `constants.py`. No user-supplied version override is accepted.

### Misuse Risks

- The `--force` flag could be used to re-generate intelligence unnecessarily. Mitigation: structured log event records every force re-generation with the operator identity (if available), and the previous artifact is preserved.
- Phase 4 non-mutation invariant: `repository.py` write methods target only Phase 5-namespaced sort keys. Any attempt to write to a Phase 4-namespaced sort key would be a programming error caught in code review and unit tests.

---

## 20. Reliability

### Determinism Requirements

- All numeric computations use Python `Decimal` with `ROUND_HALF_UP` (matching Phase 4's `latency_summary` rounding standard in `engine.py`).
- Per-endpoint ordering in the S3 artifact `endpoints` array is canonically sorted by `endpoint_id` (lexicographic ascending).
- `failure_classification_breakdown` maps are sorted by key (lexicographic ascending) for canonical serialization.
- Field ordering in the JSON artifact follows a defined canonical order; `json.dumps(..., sort_keys=True)` is used for artifact serialization.
- For identical Phase 4 aggregate inputs, Phase 5 must produce byte-identical S3 artifact JSON. `test_determinism.py` validates this invariant.

### Failure Modes

| Failure Mode | Behavior |
| --- | --- |
| `AggregateSetCompletion` absent | Terminate; return structured error; no Phase 5 writes; emit log event |
| Phase 4 records partially absent (EndpointAggregate count mismatch) | Detected in metrics step; failure_reason_code `PHASE4_RECORD_INCONSISTENCY`; status FAILED |
| `FailureClassificationAggregate` absent for endpoint with failures | Anomaly recorded in artifact; generation continues; per-endpoint failure breakdown omitted |
| S3 write failure | `engine.py` catches; DynamoDB updated to FAILED; no partial artifact |
| DynamoDB COMPLETE write failure after S3 success | DynamoDB shows FAILED; S3 artifact persisted at its key; re-invocation will produce new artifact at new key |
| Concurrent generation attempt | Return `INTELLIGENCE_GENERATION_IN_PROGRESS`; no action |
| `success_inputs.denominator = 0` | success_rate labeled `INSUFFICIENT_DATA`; no divide-by-zero; generation continues |
| `execution_count = 0` for endpoint | All labels `INSUFFICIENT_DATA`; endpoint_score uses all neutral values; generation continues |

### Operational Logging

All Phase 5 structured log events follow the platform logging standard (`docs/architecture/structured_logging.md`):

| Event Type | Stage | Level | When Emitted |
| --- | --- | --- | --- |
| `intelligence_generation_invoked` | `intelligence` | INFO | CLI command received |
| `intelligence_already_exists` | `intelligence` | INFO | Existing COMPLETE artifact found, `--force` not provided |
| `intelligence_prerequisite_gate_failed` | `intelligence` | ERROR | `AggregateSetCompletion` absent or incomplete |
| `intelligence_generation_pending` | `intelligence` | INFO | PENDING status written |
| `intelligence_generation_in_progress` | `intelligence` | INFO | IN_PROGRESS status written |
| `intelligence_metrics_complete` | `intelligence` | INFO | Phase 5.2 computation complete; endpoint_count logged |
| `intelligence_analysis_complete` | `intelligence` | INFO | Stability/burst/consistency analysis complete |
| `intelligence_scoring_complete` | `intelligence` | INFO | Composite score computed; composite_score logged |
| `intelligence_s3_artifact_written` | `intelligence` | INFO | S3 artifact successfully written; s3_artifact_ref logged |
| `intelligence_generation_complete` | `intelligence` | INFO | COMPLETE status written; intelligence_job_id and composite_score logged |
| `intelligence_generation_failed` | `intelligence` | ERROR | FAILED status written; failure_stage and failure_reason_code logged |

Log events must include: `timestamp`, `level`, `service`, `stage`, `event_type`, `client_id`, `audit_id`, `intelligence_job_id`.

### Performance Considerations

Phase 5 is a CLI-invoked synchronous process. No Lambda cold-start or timeout constraints apply. Expected completion time for a standard 10-endpoint 48-hour audit campaign: under 5 seconds (DynamoDB reads + local computation + S3 write).

DynamoDB access pattern: single query on the Phase 4 aggregate prefix returns all required records in one call. No per-endpoint queries required.

---

## 21. Dependencies

- Phase 4 aggregation layer: `AggregateSetCompletion` marker, `AuditAggregate`, `EndpointAggregate`, `FailureClassificationAggregate`, and `LineageManifest` records must be persisted and retrievable.
- `docs/architecture/phase_4a_phase5_consumer_contract.md`: stable field set, DynamoDB query patterns, `agg_v1` semantic guarantees.
- `docs/architecture/phase_4a_aggregation_schema.md`: Phase 4 record types and field schemas.
- Existing operator CLI infrastructure (`src/release_confidence_platform/operator_cli/`).
- Phase 4A retrieval infrastructure (`src/release_confidence_platform/retrieval/`): patterns followed; shared utilities reused where applicable.
- Existing platform DynamoDB metadata table: Phase 5 records use the same table with Phase 5-namespaced sort keys.
- Existing S3 raw-results bucket: Phase 5 artifact key prefix `intelligence/` does not overlap with `raw-results/`.
- `docs/architecture/naming_and_schema_versioning.md`: naming conventions.
- `docs/architecture/structured_logging.md`: log event field standard.
- `docs/architecture/adr_sanitization_boundary.md`: sanitization requirements apply to Phase 5 output.
- `src/release_confidence_platform/core/`: existing validators, exceptions, time utilities, StructuredLogger.
- Phase 4A validation campaign audit data: required for Phase 5.8 validation campaign (575 executions, 3 independent 48-hour audits).

---

## 22. Assumptions

The following assumptions require confirmation before or during Phase 5.1:

**Assumption requiring confirmation:** The Phase 4A validation campaign data (575 executions across 3 independent 48-hour audits) is available and lineage-complete in the development environment for Phase 5.8 validation use.

**Assumption requiring confirmation:** The existing DynamoDB metadata table can accommodate Phase 5 `IntelligenceJob` and `IntelligenceMetadata` records under the existing capacity configuration. Phase 5 adds a bounded and small number of records per audit (one `IntelligenceJob` per generation, one `IntelligenceMetadata` per audit execution).

**Assumption requiring confirmation:** The existing S3 raw-results bucket accepts Phase 5 artifact writes under the `intelligence/` key prefix without additional bucket policy changes. If a new bucket is required, this must be escalated before Phase 5.2 implementation.

**Assumption (confirmed by product spec):** `intel_v1` is implemented in Python within the `reliability_intelligence/` module under `src/release_confidence_platform/`, following the same structural patterns as `aggregation/` and `retrieval/`.

**Assumption (confirmed by product spec):** Phase 5 will not require new AWS Lambda functions. Intelligence generation runs as a CLI process for Phase 5.

**Confirmed design decision — stability/burst/consistency from agg_v1 full-window data:** The distributional proxy approach defined in Sections 10, 11, and 12 is sufficient for `intel_v1`. Temporal sub-window analysis is deferred. If full-window proxies are found insufficient during Phase 5.8 validation, the path forward is a Phase 4 `agg_v2` contract amendment introducing time-bucketed aggregate fields. This would require a separate ADR and HITL approval and would not block Phase 5.2–5.7 implementation.

---

## 23. Risks and Open Questions

### Risk 1: Stability and Burst Proxy Signal Credibility

**Risk:** The distributional proxy signals for stability and burst detection — success rate threshold, p99/mean ratio, timeout proportion — may not produce credibly meaningful labels when reviewed against real Phase 4A audit data in Phase 5.8. A 20% timeout threshold or 3.0 p99/mean ratio may be too aggressive or too permissive for the known audit profiles.

**Mitigation:** Phase 5.8 validation campaign includes human review of generated labels against known Phase 4A audit behavior. If threshold values produce unintuitive results, they can be adjusted before `intel_v1` is finalized. Thresholds are centralized in `constants.py` and carry no implementation coupling.

**Escalation path:** If labels are not credible from `agg_v1` inputs, the `stability` and `burst` components may be reduced to `INSUFFICIENT_DATA`-only for `intel_v1` and deferred to `intel_v2` pending Phase 4 `agg_v2` sub-window data.

### Risk 2: Composite Score Weight Calibration

**Risk:** The weights (0.50/0.20/0.15/0.15) are architecture-defined, not validated against real operator intuition. Phase 5.8 review may identify that reliability should carry even more weight (e.g., 0.70) or that stability should be excluded until temporal data is available.

**Mitigation:** Weights are defined in `constants.py` with no coupling to artifact schemas. Adjustment before Phase 5.8 sign-off is low-cost. After `intel_v1` is validated, weight changes require a new `intelligence_version`.

### Risk 3: Phase 4 Consumer Contract Stability

**Risk:** During Phase 5.2 implementation, the engineering team may discover that a Phase 4 aggregate field is missing, incorrectly typed, or semantically different from the consumer contract definition for a subset of real audit records.

**Mitigation:** Phase 5.8 validation explicitly tests against live Phase 4A data. Any contract inconsistency discovered must be escalated as a Phase 4 contract defect before proceeding.

### Risk 4: DynamoDB Record on Force Re-generation

**Risk:** The `IntelligenceMetadata` record is UPDATABLE (unlike Phase 4's immutable `AggregateSetCompletion`). This means a previous complete record can be overwritten. If the force re-generation fails midway, the DynamoDB record may be left in an inconsistent state.

**Mitigation:** The two-record design (immutable `IntelligenceJob` audit log + updatable `IntelligenceMetadata`) preserves generation history. Each generation event has its own `IntelligenceJob` record. The `IntelligenceMetadata` record reflects current state only; history is reconstructable from `IntelligenceJob` records.

### Risk 5: S3 Artifact Orphaning on Re-generation

**Risk:** Force re-generation leaves the previous S3 artifact at its original key without any record pointing to it (since `IntelligenceMetadata` is updated to the new artifact). Over time, orphaned artifacts could accumulate.

**Mitigation:** For Phase 5, orphaned artifacts are a known and accepted artifact of the immutability-plus-force-overwrite model. The previous `IntelligenceJob` record retains the old `s3_artifact_ref`, allowing recovery if needed. S3 lifecycle policies for cleaning old `intelligence/` artifacts belong to a future operational phase.

### Open Question 1: Per-Endpoint DynamoDB Records

This design routes per-endpoint analysis detail to the S3 artifact. Some retrieval commands (`retrieve intelligence-endpoints`, `retrieve intelligence-stability`, etc.) therefore require an S3 read. If operators require DynamoDB-only retrieval for all commands (e.g., for cost or latency reasons), per-endpoint summary records could be added to DynamoDB. This would increase DynamoDB record count by up to 10 records per generation (for a 10-endpoint audit). This is a Phase 5.1 confirmation item.

Current decision: per-endpoint detail in S3 artifact only. DynamoDB holds summary/status only. This can be changed in Phase 5.1 before implementation begins without affecting the S3 artifact schema.

### Open Question 2: S3 Bucket for Intelligence Artifacts

The design assumes the existing `release-confidence-platform-${stage}-raw-results` S3 bucket is used with the `intelligence/` key prefix. If operational or compliance concerns require a separate bucket for intelligence artifacts vs raw evidence, a new bucket `release-confidence-platform-${stage}-intelligence` would be added. This requires IAM policy changes. Confirmation required before Phase 5.2 implementation.

---

## 24. Implementation Notes

### For Phase 5.2 (Reliability Metrics Core)

- Start with `metrics.py` as a pure function module with no I/O. All inputs are dictionaries matching the Phase 4 consumer contract field names. This makes the module independently testable with fixture data.
- Use `Decimal(str(value))` for all numeric conversions from DynamoDB-sourced floats, matching the Phase 4 engine pattern in `aggregation/engine.py`.
- The `fail_count` derivation (`execution_count - pass_count`) must be verified against `agg_v1` semantics: `fail_count = execution_count - success_inputs.numerator`. This holds because `agg_v1` has `skipped = 0` always.
- The `audit_success_rate` computation (`request_counts.successful / request_counts.total`) requires a guard for `total = 0`.

### For Phase 5.3–5.5 (Analysis Modules)

- Each analysis module (`stability.py`, `burst.py`, `consistency.py`) returns a named dataclass (`StabilityResult`, `BurstResult`, `ConsistencyResult`) containing the label, intermediate values, and inputs consumed. These intermediate values are the methodology trace inputs persisted in the S3 artifact.
- All thresholds come from `constants.py` only. No magic numbers in analysis modules.
- Each module has a corresponding `test_*.py` unit test file that exercises all label outcomes, all `INSUFFICIENT_DATA` paths, and all threshold boundary conditions (at threshold, just above, just below).

### For Phase 5.6 (Scoring)

- `scoring.py` depends only on analysis result DTOs; it does not read from Phase 4 or storage.
- The label-to-score mapping table in Section 13.2 must be defined as a constant dictionary in `constants.py` and referenced by both `scoring.py` and the S3 artifact `methodology_disclosure.label_to_score_mapping` field.
- Endpoint ordering in composite score rollup follows canonical endpoint_id sort to ensure determinism.

### For Phase 5.7 (Retrieval CLI)

- Follow the `retrieval/` layering pattern exactly: commands own argument parsing and output only; service owns query logic; repository owns storage access; formatter owns serialization.
- Retrieval commands that read the S3 artifact must use `publisher.py`'s artifact-read method (not a direct S3 client call from the command or service layer).
- All `intelligence-*` retrieval commands share the same provenance envelope builder from `formatter.py`.

### For `engine.py`

- Follow the `AggregationOrchestrator` pattern from `aggregation/orchestrator.py`: status updates before and after each major stage; structured log events at each transition; `try/except` with failure classification.
- `engine.py` must not contain any business logic or computation. It is the orchestrator only. All computation lives in the analysis modules.

### For `repository.py`

- Phase 4 consumer reads must use only the two query patterns defined in `phase_4a_phase5_consumer_contract.md` Section 5.
- Phase 5 DynamoDB writes use conditional writes for `IntelligenceJob` creation (analogous to `put_job_once` in `aggregation/repository.py`).
- `IntelligenceMetadata` write uses an upsert pattern (write if not exists; update on re-generation).

### For Naming

- `intelligence_job_id` format: `intjob_{uuid4().hex}` (analogous to `aggjob_` in Phase 4).
- `INTELLIGENCE_VERSION` constant: `"intel_v1"` (analogous to `AGGREGATION_VERSION = "agg_v1"`).

### For Phase 5.8 (Validation Campaign)

- Run Phase 5 generation against each of the 3 Phase 4A campaign audits.
- For each audit: verify composite score, all per-endpoint labels, and all methodology traces against human review expectations.
- Run the same audit through Phase 5 generation twice and confirm byte-identical S3 artifact JSON (determinism test).
- Confirm `test_phase6_consumer_contract.py` passes against generated artifacts before Phase 5 HITL sign-off.

---

## 25. Traceability

This technical design traces to the following documents:

- `docs/product/phase_5_reliability_intelligence_product_spec.md` — primary input; all requirements and acceptance criteria
- `docs/architecture/phase_4a_phase5_consumer_contract.md` — Phase 4 consumer contract boundary; stable field definitions
- `docs/architecture/phase_4a_aggregation_schema.md` — Phase 4 DynamoDB record types and field schemas
- `docs/architecture/phase_4a_aggregation_foundation_technical_design.md` — format reference; Phase 4A architectural patterns
- `docs/architecture/naming_and_schema_versioning.md` — naming conventions for identifiers and schema versions
- `docs/architecture/structured_logging.md` — log event field standard
- `docs/architecture/adr_sanitization_boundary.md` — sanitization requirements applicable to Phase 5 output
- `RCP_Product_Strategy.md` — product constitution; phase governance; core product principles
- `src/release_confidence_platform/aggregation/` — implementation patterns followed
- `src/release_confidence_platform/retrieval/` — retrieval layer patterns extended
