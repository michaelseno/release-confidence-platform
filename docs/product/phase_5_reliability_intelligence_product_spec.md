# Product Specification

## 1. Feature Overview

Phase 5 is the Reliability Intelligence layer of the Release Confidence Platform.

Its purpose is to interpret the deterministic, immutable aggregation artifacts produced by Phase 4 and derive structured, evidence-backed reliability intelligence. This intelligence forms the authoritative analytical foundation that Phase 6 will consume to produce Release Confidence Reports.

Phase 5 delivers:

- Per-endpoint reliability metrics (success rate, failure classification breakdown, latency profile)
- Distributional stability characterization of latency and success rate using full-window agg_v1 aggregate signals (temporal sub-window analysis is not available from agg_v1)
- Distributional burst characterization using proxy signals from full-window agg_v1 aggregates (temporal burst timing is not determinable from agg_v1)
- Outcome consistency estimation using aggregate success rate variance (per-run consistency data is not available from agg_v1)
- A deterministic, explainable Release Confidence Score with per-endpoint evidence trace and full methodology disclosure

Phase 5 is not an autonomous system. For initial implementation, it is operator-invoked via CLI after Phase 4 aggregation is confirmed complete. All intelligence derives from Phase 4 aggregation artifacts. No raw evidence is accessed directly.

Phase 5 is NOT any of the following:

- A reporting or document generation layer (Phase 6)
- A dashboard or visualization layer
- A monitoring or observability platform
- A CI/CD integration or gating mechanism
- A predictive or AI-driven analytics system
- A real-time or streaming system
- An automated trigger for any downstream action
- A customer-facing product surface

### Backend / System Impact

- A new `reliability_intelligence/` module is introduced under `src/release_confidence_platform/`.
- Phase 5 writes its own artifact layer to S3 (immutable JSON intelligence artifacts) and DynamoDB (metadata, status, score summaries, lineage references back to Phase 4).
- Phase 5 does not mutate any Phase 4 aggregation artifacts.
- Phase 5 requires the `AggregateSetCompletion` marker before consuming any Phase 4 artifacts.
- Phase 5 extends the operator CLI with a set of intelligence retrieval commands.
- Phase 5 publishes the Phase 6 consumer contract, defining what Phase 6 may consume from Phase 5 intelligence artifacts.

---

## 2. Problem Statement

Phase 4 and Phase 4A delivered a complete, validated, and production-ready aggregation layer. The platform can now reliably produce immutable aggregate facts from 48-hour audit campaigns: request counts, latency distributions, status code distributions, failure classification breakdowns, and evidence lineage manifests.

These aggregated facts answer the question "What happened?" but do not answer the question the platform exists to answer:

> "Based on objective operational evidence, how confident should we be in releasing this API?"

The gap between aggregated fact and release confidence interpretation is the problem Phase 5 solves.

Specifically:

1. **No reliability interpretation exists.** Per-endpoint success rates, latency profiles, and failure classification breakdowns are not derived from aggregate inputs. There is no structured reliability metric layer.

2. **No stability analysis exists.** Phase 4 aggregates over the full 48-hour window. There is no mechanism to characterize whether aggregate evidence for latency or success rate is consistent with stable behavior across the observation window. Temporal sub-window data is not available from agg_v1.

3. **No burst analysis exists.** Distributional signals consistent with burst behavior — such as elevated timeout proportions or extreme latency outliers — are not characterized from full-window aggregate summaries. Temporal burst timing is not determinable from agg_v1.

4. **No consistency analysis exists.** Whether aggregate success rate variance is consistent with stable outcomes is not assessed. Per-run consistency data is not available from agg_v1.

5. **No Release Confidence Score exists.** There is no deterministic, explainable composite score that synthesizes reliability evidence into a single assessment with per-endpoint evidence trace.

6. **Phase 6 has no input.** Phase 6 (Deterministic Reporting) requires structured, pre-computed intelligence artifacts as input. Without Phase 5, Phase 6 cannot begin.

Phase 5 closes all of these gaps while maintaining the platform's core principles: determinism, explainability, evidence traceability, and no hallucinated conclusions.

---

## 3. User Persona / Target User

### Platform Engineer / Operator

Invokes Phase 5 intelligence generation via CLI after confirming Phase 4 aggregation is complete. Inspects intelligence artifacts to verify correctness, review methodology traces, and confirm evidence lineage. Uses the Phase 5 Engineering Retrieval CLI for operational debugging and pre-release validation.

### QA Engineer

Validates Phase 5 intelligence output against known fixture inputs. Confirms determinism (same inputs produce identical output), methodology correctness, evidence traceability, and absence of conclusions without evidence. Executes acceptance criteria against Phase 5 artifacts.

### Phase 6 Reporting Consumer (Internal)

Consumes the Phase 6 consumer contract published by Phase 5. Reads pre-computed intelligence artifacts from S3 and DynamoDB to produce Release Confidence Reports. Does not re-derive or re-interpret Phase 5 conclusions.

No operator-facing or customer-facing persona interacts directly with Phase 5 artifacts. Phase 5 output is internal platform infrastructure consumed downstream by Phase 6.

---

## 4. User Stories

- As a platform engineer, I want to invoke Phase 5 intelligence generation via CLI for a completed audit so that I can produce a structured reliability intelligence artifact without writing custom analysis scripts or querying DynamoDB directly.
- As a platform engineer, I want Phase 5 to require the `AggregateSetCompletion` marker before running so that intelligence is never generated from an incomplete or partially-aggregated audit.
- As a platform engineer, I want per-endpoint reliability metrics (success rate, failure classification breakdown, latency profile) derived from Phase 4 aggregates so that I can see endpoint-level reliability without accessing raw evidence.
- As a platform engineer, I want distributional stability characterization of latency and success rate from full-window agg_v1 aggregates, with methodology disclosure that temporal sub-window analysis is not available from agg_v1, so that stability conclusions do not overstate what the evidence supports.
- As a platform engineer, I want distributional burst characterization using proxy signals from full-window agg_v1 aggregates, with methodology disclosure that temporal burst timing is not determinable from agg_v1, so that burst conclusions accurately reflect what the aggregate evidence can and cannot show.
- As a platform engineer, I want outcome consistency estimation using aggregate success rate variance, with methodology disclosure that per-run consistency data is not available from agg_v1, so that consistency conclusions are grounded in what agg_v1 supports.
- As a platform engineer, I want a deterministic Release Confidence Score with per-endpoint evidence trace and methodology disclosure so that every score component is explainable and reproducible.
- As a platform engineer, I want Phase 5 intelligence artifacts persisted immutably to S3 and indexed in DynamoDB so that I can retrieve them later without re-running intelligence generation.
- As a platform engineer, I want a Phase 5 retrieval CLI so that I can inspect intelligence artifacts, review score components, and trace evidence lineage without querying storage directly.
- As a future Phase 6 implementer, I want a formally published Phase 6 consumer contract so that I can implement reporting against stable Phase 5 intelligence outputs.

---

## 5. Goals / Success Criteria

Phase 5 is successful when:

- Intelligence generation completes for a known-good Phase 4 audit campaign and produces correct, complete intelligence artifacts.
- Every intelligence conclusion (success rate, stability label, burst flag, consistency label, confidence score) traces to a specific Phase 4 aggregate field with an explicit methodology step.
- For the same Phase 4 aggregate inputs, Phase 5 produces byte-identical intelligence artifacts across independent invocations (determinism).
- Phase 5 never generates intelligence from an audit with no `AggregateSetCompletion` marker present (completeness gate enforced).
- Phase 5 never reads raw execution evidence from S3 or Phase 1/2/3 DynamoDB records.
- Phase 5 never mutates any Phase 4 aggregation artifact.
- Intelligence artifacts are persisted to S3 (immutable JSON) and DynamoDB (metadata + score summary + lineage references) and are retrievable via the Phase 5 retrieval CLI.
- A Phase 6 consumer contract is formally published and HITL-approved as part of Phase 5.1.
- Validation campaign confirms Phase 5 intelligence is correct and reproducible against live 48-hour Phase 4 audit data.
- All GitHub Issues closed, all HITL gates passed, all implementation PRs merged.

---

## 6. Feature Scope

### In Scope

- Phase 5.1: Documentation subphase — product spec, technical design, Phase 5 schema, Phase 6 consumer contract.
- Phase 5.2: Reliability Metrics Core — per-endpoint success rate, failure classification breakdown, latency profile derivation from Phase 4 aggregates.
- Phase 5.3: Stability Analysis — distributional stability characterization of latency and success rate using full-window agg_v1 proxy signals.
- Phase 5.4: Burst Analysis — distributional burst characterization using full-window agg_v1 proxy signals (temporal burst timing not determinable from agg_v1).
- Phase 5.5: Consistency Analysis — outcome consistency estimation using aggregate success rate variance (per-run data not available from agg_v1).
- Phase 5.6: Release Confidence Scoring — deterministic composite score with per-endpoint evidence trace, component weights disclosure, and methodology explainability.
- Phase 5.7: Engineering Retrieval CLI — operator CLI for Phase 5 intelligence artifacts.
- Phase 5.8: Validation Campaign — live validation against Phase 4 audit data from the Phase 4A validation campaign.
- Operator-invoked (CLI/manual) trigger mechanism for Phase 5 generation.
- `AggregateSetCompletion` prerequisite gate enforced before any intelligence generation.
- S3 immutable JSON artifact persistence for full intelligence output with methodology trace.
- DynamoDB metadata, status, score summary, and lineage reference records.
- Phase 6 consumer contract as a platform constitution document.
- GitHub Issues for each subphase with predecessor and successor references.

### Out of Scope

The following are explicitly excluded from Phase 5:

- Phase 6 Deterministic Reporting implementation.
- Phase 7 Audit Platform Integrity implementation.
- Any customer-facing or operator-facing reporting, dashboarding, or visualization.
- Automated event-driven Lambda trigger from `AggregateSetCompletion` (deferred; may follow after manual generation is validated and reproducible, but is not in scope for Phase 5).
- AI-driven or probabilistic scoring; all conclusions must be deterministic and evidence-derived.
- Predictive analytics, trend interpretation across multiple audits, or cross-audit comparison.
- Anomaly detection using machine learning, statistical models trained on historical data, or unsupervised clustering.
- Real-time or streaming intelligence generation.
- External API surface, webhook, or notification system.
- CI/CD integration or release gating.
- Subscription, billing, authentication, RBAC, or account management.
- Mutation, deletion, or compaction of Phase 4 aggregation artifacts.
- Re-aggregation, re-counting, or re-classification of raw execution evidence.
- New monitoring, alerting, or observability infrastructure.
- Customer-facing or public intelligence export.

### Future Considerations

- Event-driven Lambda trigger from `AggregateSetCompletion` may be introduced after Phase 5 manual generation is validated as reproducible. This is intentionally deferred to avoid prematurely automating an unvalidated intelligence pipeline.
- Cross-audit trend analysis comparing reliability trajectories across multiple audit campaigns belongs to a future roadmap phase.
- Customer-facing intelligence export or summary belongs to a later commercial phase.
- Phase 5 retrieval architecture must be designed to allow future expansion without breaking the Phase 6 consumer contract.

---

## 7. Functional Requirements

### FR-P1: Operator-Invoked Intelligence Generation

#### FR-P1a: CLI Invocation Interface

Phase 5 intelligence generation must be invocable via the operator CLI using an explicit command. The command must accept:

- `--client <client_id>` — required; scoped client identifier.
- `--audit <audit_id>` — required; scoped audit identifier.
- `--execution <audit_execution_id>` — required; durable execution identity.
- `--config-version <config_version>` — required; configuration version scoping.
- `--aggregation-version <aggregation_version>` — required; identifies which Phase 4 artifact set to consume (e.g., `agg_v1`).
- `--dry-run` — optional; validates inputs and confirms Phase 4 prerequisites without writing Phase 5 artifacts.
- `--output json | human` — optional; controls output format for invocation confirmation.

#### FR-P1b: AggregateSetCompletion Prerequisite Gate

Phase 5 intelligence generation must not proceed unless an `AggregateSetCompletion` marker exists for the specified `(client_id, audit_id, audit_execution_id, config_version, aggregation_version)` combination with `completion_status = COMPLETE`.

If the marker is absent or `completion_status` is not `COMPLETE`, Phase 5 must:

- Terminate without writing any Phase 5 artifact.
- Return a structured error identifying the missing prerequisite.
- Emit a structured log event recording the gate failure with the scoped identifiers.

The `AggregateSetCompletion` marker is the only authoritative completeness proof. Phase 5 must not infer aggregate set completeness from child record counts, structured logs, or any other mechanism.

#### FR-P1c: Idempotent Invocation

Phase 5 intelligence generation must be idempotent. If intelligence artifacts for the specified combination already exist:

- The operator must be notified with artifact metadata (existing artifact timestamp, version).
- Phase 5 must not overwrite existing immutable artifacts by default.
- A `--force` flag must be required to explicitly re-generate and overwrite existing artifacts.

#### FR-P1d: Intelligence Generation Status

Phase 5 must write a status record to DynamoDB before and after intelligence generation:

- `PENDING` — generation has been invoked and the prerequisite gate has passed.
- `IN_PROGRESS` — intelligence derivation is actively running.
- `COMPLETE` — all Phase 5 artifacts have been successfully written.
- `FAILED` — intelligence generation failed; reason code and failure stage recorded.

Status records must include `created_at`, `updated_at`, and the scoped identifiers.

#### FR-P1e: Intelligence Version

All Phase 5 artifacts must carry a `intelligence_version` field (e.g., `intel_v1`). This version identifies the methodology, scoring weights, and stability/burst/consistency algorithm version used to produce the artifact. Phase 5.1 defines `intel_v1` as the initial version.

---

### FR-P2: Reliability Metrics Core

Reliability Metrics Core derives per-endpoint reliability metrics from Phase 4 `EndpointAggregate` and `FailureClassificationAggregate` records. These metrics form the evidentiary foundation for all subsequent analysis.

#### FR-P2a: Per-Endpoint Success Rate

For each endpoint, Phase 5 must derive:

| Field | Derivation |
| --- | --- |
| `success_rate` | `success_inputs.numerator / success_inputs.denominator` |
| `execution_count` | `EndpointAggregate.execution_count` |
| `pass_count` | `success_inputs.numerator` |
| `fail_count` | `execution_count - pass_count` |
| `timeout_count` | `EndpointAggregate.timeout_count` |
| `success_rate_numerator` | `success_inputs.numerator` (retained for traceability) |
| `success_rate_denominator` | `success_inputs.denominator` (retained for traceability) |

Success rate must be expressed as a decimal in `[0.0, 1.0]` with precision consistent with Phase 4 latency precision (3 decimal places).

The `success_inputs.numerator` and `success_inputs.denominator` source fields from the Phase 4 `EndpointAggregate` must be retained in the Phase 5 artifact for evidence traceability. Phase 5 must not re-define what constitutes a pass or fail.

#### FR-P2b: Per-Endpoint Failure Classification Breakdown

For each endpoint, Phase 5 must include the complete `failure_classification_counts` map from the corresponding endpoint-scoped `FailureClassificationAggregate` record. Phase 5 must not rename, remap, or re-classify any classification label.

The artifact must record the source `aggregate_type`, `scope`, and `endpoint_id` from which each classification count was read.

#### FR-P2c: Per-Endpoint Latency Profile

For each endpoint, Phase 5 must derive a latency profile from `EndpointAggregate.latency_distribution_ms`:

| Field | Derivation |
| --- | --- |
| `latency_min_ms` | `latency_distribution_ms.min` |
| `latency_max_ms` | `latency_distribution_ms.max` |
| `latency_mean_ms` | `latency_distribution_ms.mean` |
| `latency_median_ms` | `latency_distribution_ms.median` |
| `latency_p95_ms` | `latency_distribution_ms.p95` |
| `latency_p99_ms` | `latency_distribution_ms.p99` |
| `latency_count` | `latency_distribution_ms.count` |

All latency values must be carried through at Phase 4 precision (3 decimal places). Phase 5 must not re-compute or adjust latency values.

#### FR-P2d: Audit-Level Reliability Summary

Phase 5 must derive an audit-level reliability summary from the `AuditAggregate` record:

| Field | Derivation |
| --- | --- |
| `total_executions` | `request_counts.total` |
| `total_pass` | `request_counts.successful` |
| `total_fail` | `request_counts.failed` |
| `total_timeout` | `request_counts.timeout` |
| `total_network_failure` | `request_counts.network_failure` |
| `audit_latency_mean_ms` | `latency_summary_ms.mean` |
| `audit_latency_p95_ms` | `latency_summary_ms.p95` |
| `audit_latency_p99_ms` | `latency_summary_ms.p99` |
| `audit_success_rate` | `request_counts.successful / request_counts.total` |
| `endpoint_count` | Count of distinct endpoints in `endpoint_execution_counts` |

---

### FR-P3: Stability Analysis

Stability Analysis characterizes whether distributional evidence from full-window agg_v1 aggregates is consistent with stable latency and success rate across the observation window. It operates on per-endpoint aggregates from the `EndpointAggregate` record.

#### FR-P3a: agg_v1 Data Constraint

Phase 4 `EndpointAggregate` records contain full-window summaries only. Sub-window time-series data is not available from agg_v1. Stability analysis for intel_v1 uses distributional proxy signals from full-window aggregate fields. Temporal sub-window stability analysis requires agg_v2 fields and is deferred.

The methodology trace must explicitly state that stability labels are distributional characterizations of the full observation window, not temporal assessments of when or whether degradation occurred.

#### FR-P3b: Success Rate Stability Label

For each endpoint, Phase 5 must assign a success rate stability label. Labels must be:

- Determined by a documented, deterministic algorithm operating on Phase 4 aggregate inputs.
- Selected from a bounded, pre-defined label set.
- Traceable to the specific input fields and threshold values used in the determination.

Initial label set (subject to refinement in Phase 5.1 technical design):

| Label | Meaning |
| --- | --- |
| `STABLE` | Aggregate evidence is consistent with stable success rate across the observation window |
| `DEGRADED` | Aggregate evidence is consistent with degraded success rate; temporal timing of degradation is not determinable from agg_v1 |
| `INSUFFICIENT_DATA` | Execution count is too low to characterize stability |

Thresholds and algorithm details must be specified in the Phase 5.1 technical design and persisted in the Phase 5 artifact methodology trace.

#### FR-P3c: Latency Stability Label

For each endpoint, Phase 5 must assign a latency stability label using the same label set and methodology traceability requirements as success rate stability. The latency stability determination must use `latency_distribution_ms.p95` and `latency_distribution_ms.mean` from the `EndpointAggregate` as inputs.

#### FR-P3d: Stability Methodology Trace

Every stability label assignment must include a methodology trace in the Phase 5 artifact recording:

- The algorithm name and version.
- The specific input fields consumed.
- The threshold values applied.
- The computed intermediate values that led to the label.

The methodology trace must be sufficient for an independent reviewer to reproduce the label assignment from the Phase 4 aggregate inputs.

---

### FR-P4: Burst Analysis

Burst Analysis characterizes whether distributional evidence from full-window agg_v1 aggregates is consistent with burst behavior or latency spike events. agg_v1 does not provide time-bucketed sub-totals; burst characterization uses distributional proxy signals from full-window summaries. Temporal burst timing is not determinable from agg_v1.

#### FR-P4a: Burst Detection Scope

Burst analysis operates at the endpoint level. Each endpoint in the audit must receive a burst analysis result.

#### FR-P4b: Failure Burst Detection

Phase 5 must evaluate whether the endpoint's failure distribution is consistent with burst behavior, using distributional proxy signals from full-window aggregate fields. The evaluation must:

- Use `EndpointAggregate.failure_classification_counts`, `execution_count`, `timeout_count`, and `http_response_distribution` as inputs.
- Apply a documented, deterministic algorithm.
- Assign a bounded label from the pre-defined burst label set.

Initial burst label set (subject to refinement in Phase 5.1 technical design):

| Label | Meaning |
| --- | --- |
| `NO_BURST_DETECTED` | Aggregate evidence does not indicate burst behavior |
| `BURST_SUSPECTED` | Aggregate evidence is consistent with burst behavior; temporal burst timing is not determinable from agg_v1 |
| `INSUFFICIENT_DATA` | Execution count is too low for burst characterization |

Note: Phase 4 aggregates provide full-window summaries, not time-bucketed sub-totals. Burst detection at this layer must rely on distributional proxy signals (e.g., timeout-to-failure ratios, http error distribution skew). The methodology must explicitly document what signals are used and what claims can and cannot be made.

#### FR-P4c: Latency Spike Detection

Phase 5 must evaluate whether the endpoint's latency distribution is consistent with latency spike events, using the spread between distribution percentiles as a proxy signal. The evaluation must use `latency_distribution_ms.max`, `latency_distribution_ms.p99`, `latency_distribution_ms.p95`, and `latency_distribution_ms.mean` as inputs.

Initial spike label set:

| Label | Meaning |
| --- | --- |
| `NO_SPIKE_DETECTED` | Latency distribution does not indicate spike events |
| `SPIKE_SUSPECTED` | Max and p99 divergence from mean/p95 is consistent with spike events |
| `INSUFFICIENT_DATA` | Latency count is too low for spike characterization |

#### FR-P4d: Burst Methodology Trace

Every burst and spike label assignment must include a methodology trace recording the algorithm, input fields, threshold values, and intermediate values used, following the same requirements as FR-P3d.

---

### FR-P5: Consistency Analysis

Consistency Analysis characterizes whether aggregate success rate variance is consistent with stable endpoint outcomes. agg_v1 provides full-window aggregate counts only; per-run outcome data is not available. Consistency estimation uses the Bernoulli variance formula applied to the aggregate success rate. Per-run consistency analysis requires individual run-level data and is deferred to a future intel_v2 path.

#### FR-P5a: Consistency Scope

Consistency analysis operates at the endpoint level using the endpoint's aggregate inputs.

#### FR-P5b: Outcome Consistency Label

For each endpoint, Phase 5 must assign an outcome consistency label characterizing aggregate success rate variance as a proxy for outcome consistency. The label must be derived from a documented, deterministic algorithm operating on `EndpointAggregate` inputs.

Initial consistency label set (subject to refinement in Phase 5.1 technical design):

| Label | Meaning |
| --- | --- |
| `CONSISTENT` | Aggregate success rate variance is consistent with stable outcomes |
| `INCONSISTENT` | Aggregate success rate variance is consistent with variable outcomes; per-run consistency data is not available from agg_v1 |
| `INSUFFICIENT_DATA` | Execution count is too low to characterize consistency |

#### FR-P5c: Consistency Methodology Trace

Every consistency label assignment must include a methodology trace following the same requirements as FR-P3d, recording the algorithm, input fields, threshold values, and intermediate computation.

---

### FR-P6: Release Confidence Scoring

Release Confidence Scoring produces a deterministic, explainable composite score for the audit that synthesizes reliability, stability, burst, and consistency signals into a single evidence-backed assessment.

#### FR-P6a: Composite Score Structure

The Release Confidence Score must be composed of discrete, named components. Each component must:

- Map to one of the reliability analysis layers (reliability metrics, stability, burst, consistency).
- Have an explicitly documented weight.
- Have a documented derivation algorithm.
- Trace to specific Phase 5 intermediate analysis results and, transitively, to specific Phase 4 aggregate fields.

#### FR-P6b: Score Range and Representation

The composite score must be expressed as a numeric value in a defined, bounded range (e.g., `0.0` to `1.0` or `0` to `100`). The range and its semantic interpretation must be documented in the methodology disclosure section of the Phase 5 artifact and in the Phase 5.1 technical design.

The score must not be presented as a pass/fail gate. Phase 5 produces a scored assessment. Release gating is outside Phase 5 scope.

#### FR-P6c: Per-Endpoint Evidence Trace

For each endpoint, Phase 5 must include an evidence trace in the artifact that records:

- The per-endpoint success rate and its Phase 4 source fields.
- The per-endpoint stability labels (success rate and latency) and their methodology traces.
- The per-endpoint burst labels (failure and latency spike) and their methodology traces.
- The per-endpoint consistency label and its methodology trace.
- The per-endpoint contribution to the composite score (component value and weight applied).

The evidence trace must be sufficient for a reviewer to independently re-derive the endpoint's contribution to the composite score from the Phase 4 aggregate inputs.

#### FR-P6d: Audit-Level Score Summary

The Phase 5 artifact must include an audit-level score summary containing:

- The composite score value.
- The component breakdown with each component's name, value, weight, and description.
- The endpoint count contributing to the score.
- The `intelligence_version` identifying the methodology version.
- The `aggregation_version` of the Phase 4 artifacts consumed.
- The `aggregate_set_hash` from the `AggregateSetCompletion` marker (immutable lineage link to Phase 4).

#### FR-P6e: Methodology Disclosure

Every Phase 5 artifact must include a methodology disclosure section that documents:

- The scoring algorithm version.
- Component names, weights, and derivation descriptions.
- Label definitions for each analysis layer.
- Threshold values used in stability, burst, and consistency determination.
- Explicit limitations: what the methodology can and cannot conclude from Phase 4 aggregate inputs.

The methodology disclosure must be deterministic and self-contained. A reviewer with only the Phase 5 artifact and the Phase 4 aggregate inputs must be able to reproduce the score.

#### FR-P6f: No AI or Probabilistic Scoring

The Release Confidence Score must be derived entirely from deterministic algorithms applied to Phase 4 aggregate fields. AI-generated conclusions, probabilistic models, statistical inference trained on historical data, or heuristics without explicit threshold documentation are prohibited.

Every scoring decision must trace to a documented rule with explicit input fields and threshold values.

---

### FR-P7: Persistence

#### FR-P7a: S3 Immutable Intelligence Artifact

Phase 5 must write the complete intelligence output to S3 as an immutable JSON artifact. The artifact must include:

- Audit-level score summary.
- Per-endpoint reliability metrics.
- Per-endpoint stability analysis results with methodology traces.
- Per-endpoint burst analysis results with methodology traces.
- Per-endpoint consistency analysis results with methodology traces.
- Per-endpoint evidence traces.
- Methodology disclosure section.
- Lineage references back to Phase 4 (`AggregateSetCompletion.aggregate_set_hash`, `AggregateSetCompletion.aggregation_job_id`, consumed artifact identifiers).
- `intelligence_version`, `aggregation_version`, `created_at`, `client_id`, `audit_id`, `audit_execution_id`.

S3 key structure must follow the platform naming conventions and be scoped by `client_id`, `audit_id`, `audit_execution_id`, and `intelligence_version`.

Once written, Phase 5 S3 artifacts must not be modified. Re-generation requires the `--force` flag (FR-P1c) and must write a new artifact with an updated `created_at` timestamp while preserving the previous artifact unless explicitly purged through an authorized operational procedure.

#### FR-P7b: DynamoDB Intelligence Metadata Record

Phase 5 must write a DynamoDB record for each intelligence generation event containing:

| Field | Description |
| --- | --- |
| `client_id` | Scoped client identifier |
| `audit_id` | Scoped audit identifier |
| `audit_execution_id` | Durable execution identity |
| `config_version` | Configuration version |
| `aggregation_version` | Phase 4 aggregation version consumed |
| `intelligence_version` | Phase 5 intelligence version |
| `status` | Generation status: `PENDING`, `IN_PROGRESS`, `COMPLETE`, `FAILED` |
| `composite_score` | Composite score value (when status is `COMPLETE`) |
| `endpoint_count` | Number of endpoints scored |
| `s3_artifact_ref` | S3 key reference to the intelligence artifact |
| `aggregate_set_hash` | Hash from the `AggregateSetCompletion` marker (lineage link) |
| `created_at` | UTC ISO-8601 creation timestamp |
| `completed_at` | UTC ISO-8601 completion timestamp (when applicable) |
| `failure_reason` | Structured failure reason (when status is `FAILED`) |

#### FR-P7c: No Phase 4 Mutation

Phase 5 must not create, update, delete, or extend any Phase 4 aggregation record, lineage manifest, or `AggregateSetCompletion` marker. The Phase 5 persistence layer must target exclusively Phase 5-namespaced DynamoDB records and S3 key paths. This is a constitutional invariant.

---

### FR-P8: Engineering Retrieval CLI for Phase 5

The Phase 5 Engineering Retrieval CLI extends the existing operator CLI with intelligence artifact inspection commands. All Phase 5 retrieval commands are read-only.

#### FR-P8a: Required Phase 5 Retrieval Commands

| Command | Purpose |
| --- | --- |
| `retrieve intelligence-status` | Return Phase 5 generation status and metadata for an audit |
| `retrieve intelligence-summary` | Return audit-level score summary and endpoint count |
| `retrieve intelligence-score` | Return composite score, component breakdown, and methodology version |
| `retrieve intelligence-endpoints` | Return per-endpoint reliability metrics for all endpoints |
| `retrieve intelligence-stability` | Return per-endpoint stability labels and methodology traces |
| `retrieve intelligence-burst` | Return per-endpoint burst and spike labels and methodology traces |
| `retrieve intelligence-consistency` | Return per-endpoint consistency labels and methodology traces |
| `retrieve intelligence-evidence-trace` | Return per-endpoint evidence trace with Phase 4 source field references |
| `retrieve intelligence-methodology` | Return the full methodology disclosure for the intelligence artifact |
| `retrieve intelligence-lineage` | Return Phase 5 lineage references back to Phase 4 aggregation artifacts |

#### FR-P8b: Output Provenance

Every Phase 5 retrieval command output must include provenance metadata:

```
retrieved_at           — UTC ISO-8601 timestamp of this retrieval
retrieval_version      — version of the Phase 5 retrieval layer
intelligence_version   — intelligence_version of the artifact retrieved
aggregation_version    — aggregation_version of the Phase 4 artifacts consumed
aggregate_set_hash     — Phase 4 AggregateSetCompletion hash (immutable lineage link)
audit_id               — scoped audit identifier
client_id              — scoped client identifier
```

Retrieved output must include the following disclaimer in human-readable output and as a top-level `_notice` field in JSON output:

> "This output is for engineering diagnostics only. Authoritative intelligence resides in the immutable Phase 5 S3 artifact."

#### FR-P8c: Output Formats and Filtering

All Phase 5 retrieval commands must support:

- `--output json` — machine-readable JSON for scripting and QA assertions.
- `--output human` (default) — formatted human-readable output.
- `--client <client_id>`, `--audit <audit_id>`, `--execution <audit_execution_id>` — required scoping filters.
- `--endpoint <endpoint_id>` — optional endpoint-level filter (where applicable).
- `--intelligence-version <version>` — optional version filter.

#### FR-P8d: Deterministic Retrieval Output

For the same persisted Phase 5 intelligence state, retrieval commands must return identical output across independent invocations. Canonical ordering, field ordering, and numeric precision must follow the same standards as the Phase 4A Engineering Retrieval CLI.

#### FR-P8e: Read-Only Invariant

The Phase 5 Engineering Retrieval CLI must not modify any Phase 5 or Phase 4 persisted artifact. The read-only invariant is unconditional.

---

## 8. Non-Functional Requirements

### NFR-1: Determinism

For identical Phase 4 aggregate inputs, Phase 5 must produce byte-identical intelligence artifacts. The same `(client_id, audit_id, audit_execution_id, config_version, aggregation_version)` combination must always produce the same composite score, the same per-endpoint labels, and the same methodology traces. Floating-point operations must use consistent precision rules documented in the technical design.

### NFR-2: Explainability

Every intelligence conclusion must be explainable from the artifact alone. An independent reviewer must be able to trace any score component, stability label, burst label, or consistency label to:

1. The specific Phase 5 algorithm and threshold values applied.
2. The specific Phase 4 aggregate input fields consumed.
3. The intermediate computation steps.

Conclusions that cannot be so traced are prohibited.

### NFR-3: Evidence Traceability

Phase 5 intelligence artifacts must carry lineage references back to Phase 4 via the `AggregateSetCompletion.aggregate_set_hash`. This hash provides an immutable link from Phase 5 interpretation to the Phase 4 aggregation artifacts from which it was derived.

### NFR-4: Immutability

Once written, Phase 5 S3 artifacts must not be silently overwritten. Overwrite requires explicit `--force` invocation. DynamoDB status records must record all generation events including re-generations.

### NFR-5: Phase 4 Non-Mutation

Phase 5 must never write to, update, or delete any Phase 4 artifact. This invariant is unconditional and is not subject to operational override. Violation would compromise evidence integrity and the constitutional boundary "Aggregation owns facts. Phase 5 owns interpretation."

### NFR-6: No Raw Evidence Access

Phase 5 must not read Phase 1, Phase 2, or Phase 3 raw evidence from S3 or DynamoDB. All Phase 5 computation must derive from Phase 4 aggregation artifacts only.

### NFR-7: Methodology Stability Within a Version

Once `intel_v1` is deployed and validated, its algorithms, thresholds, and label definitions must not change without incrementing the `intelligence_version`. A score produced by `intel_v1` must be reproducible from the same inputs by any other `intel_v1` implementation.

### NFR-8: Retrieval Correctness

Phase 5 retrieval commands must return data consistent with the persisted Phase 5 intelligence state. Retrieval must not perform interpretation, re-scoring, or re-derivation. It reads and formats persisted artifacts only.

### NFR-9: Operational Safety

Phase 5 must not bypass production authorization requirements, request caps, concurrency caps, or environment restrictions established by the platform safety framework.

---

## 9. Acceptance Criteria

### AC-P1: AggregateSetCompletion Gate Enforcement

Given a Phase 5 generation command is invoked for an audit that has no `AggregateSetCompletion` marker  
When the generation process evaluates the prerequisite gate  
Then generation terminates without writing any Phase 5 artifact, returns a structured error identifying the missing prerequisite, and emits a structured log event recording the gate failure with scoped identifiers.

Given a Phase 5 generation command is invoked for an audit with a valid `AggregateSetCompletion` marker with `completion_status = COMPLETE`  
When the generation process evaluates the prerequisite gate  
Then generation proceeds to the intelligence derivation stage.

### AC-P2: Reliability Metrics Correctness

Given a completed audit with known Phase 4 `EndpointAggregate` and `FailureClassificationAggregate` records  
When Phase 5 intelligence generation completes  
Then the per-endpoint success rate equals `success_inputs.numerator / success_inputs.denominator` to 3 decimal places, and the per-endpoint failure classification breakdown matches the Phase 4 `FailureClassificationAggregate.classification_counts` exactly.

Given a Phase 4 `EndpointAggregate` with a non-zero `execution_count` and `success_inputs.denominator = 0`  
When Phase 5 attempts to derive the success rate  
Then the condition is recorded as an edge case in the artifact with an `INSUFFICIENT_DATA` label rather than a divide-by-zero error.

### AC-P3: Stability Analysis Correctness

Given a completed audit with per-endpoint Phase 4 aggregates  
When Phase 5 stability analysis completes  
Then every endpoint has a success rate stability label and a latency stability label, each from the defined label set, with a methodology trace recording algorithm name, input fields, threshold values, and intermediate values.

Given a Phase 5 artifact is inspected after generation  
When the stability label for an endpoint is reviewed  
Then the label can be independently reproduced by applying the documented algorithm and thresholds to the Phase 4 aggregate inputs referenced in the methodology trace.

### AC-P4: Burst Analysis Correctness

Given a completed audit with per-endpoint Phase 4 aggregates  
When Phase 5 burst analysis completes  
Then every endpoint has a failure burst label and a latency spike label from the defined label sets, with methodology traces documenting the proxy signals, algorithm, thresholds, and the explicit limitations of the approach.

### AC-P5: Consistency Analysis Correctness

Given a completed audit with per-endpoint Phase 4 aggregates  
When Phase 5 consistency analysis completes  
Then every endpoint has an outcome consistency label from the defined label set, with a methodology trace satisfying the traceability requirement.

### AC-P6: Release Confidence Score Determinism

Given the same Phase 4 aggregate inputs invoked twice independently  
When Phase 5 intelligence generation completes for both invocations  
Then the composite score value is identical, all per-endpoint labels are identical, and the methodology trace values are identical across both artifacts.

### AC-P7: Per-Endpoint Evidence Trace Completeness

Given a completed Phase 5 artifact for an audit  
When the evidence trace for any endpoint is inspected  
Then the trace includes the Phase 4 source fields for success rate, the methodology trace for each label assignment, the component contribution to the composite score, and the `aggregate_set_hash` linking back to the Phase 4 `AggregateSetCompletion` marker.

### AC-P8: Methodology Disclosure Completeness

Given a completed Phase 5 artifact  
When the methodology disclosure section is inspected  
Then it includes the scoring algorithm version, component names and weights, label definitions for all analysis layers, threshold values for all deterministic decisions, and explicit limitations of the methodology.

### AC-P9: S3 Artifact Persistence

Given Phase 5 intelligence generation completes successfully  
When the S3 artifact is retrieved  
Then it contains all required sections (score summary, per-endpoint metrics, stability, burst, consistency, evidence traces, methodology disclosure, lineage references) and is valid JSON.

### AC-P10: DynamoDB Status Record

Given Phase 5 intelligence generation is invoked  
When the DynamoDB status record is queried at any point during or after generation  
Then it reflects the correct `status` value (`PENDING`, `IN_PROGRESS`, `COMPLETE`, or `FAILED`) and includes all required metadata fields.

### AC-P11: Phase 4 Non-Mutation

Given Phase 5 intelligence generation runs for any audit  
When all Phase 4 aggregation artifact records are inspected before and after Phase 5 execution  
Then no Phase 4 record has been created, updated, deleted, or extended by Phase 5.

### AC-P12: Phase 5 Retrieval CLI — Status and Summary

Given an audit with a completed Phase 5 intelligence artifact  
When `retrieve intelligence-status` is executed  
Then the command returns the status, composite score, endpoint count, and S3 artifact reference with provenance metadata.

Given any Phase 5 retrieval command is executed  
When the output is inspected  
Then it includes the provenance envelope (`retrieved_at`, `retrieval_version`, `intelligence_version`, `aggregation_version`, `aggregate_set_hash`, `audit_id`, `client_id`) and the engineering diagnostic disclaimer.

### AC-P13: Idempotent Invocation

Given Phase 5 intelligence artifacts already exist for an audit  
When Phase 5 generation is invoked without `--force`  
Then generation does not overwrite the existing artifact and the operator receives a notification including the existing artifact's `created_at` timestamp and `intelligence_version`.

Given Phase 5 generation is invoked with `--force`  
When the force re-generation completes  
Then a new S3 artifact is written and the DynamoDB status record reflects the updated `completed_at` timestamp.

### AC-P14: Validation Campaign

Given Phase 5.2 through 5.7 are merged and deployed  
When Phase 5 intelligence generation is invoked against Phase 4A validation campaign audit data (verified as lineage-complete)  
Then intelligence artifacts are produced successfully, the composite score and all per-endpoint labels are correct by independent review, the methodology is reproducible, and no hallucinated conclusions are present in the output.

---

## 10. Edge Cases

- Phase 5 invoked for an audit where the `AggregateSetCompletion` marker exists but `completion_status` is not `COMPLETE`.
- Phase 5 invoked for an audit that has no endpoint aggregates (audit-level aggregate only).
- Phase 5 invoked for an endpoint with `execution_count = 0`.
- Phase 5 invoked for an endpoint where `success_inputs.denominator = 0`.
- Phase 5 invoked for an endpoint where `latency_distribution_ms.count = 0`.
- Phase 5 invoked for an endpoint where all executions are timeouts (100% timeout rate; `success_rate = 0.0`).
- Phase 5 invoked for an endpoint where all executions pass (100% success rate; no failure classifications).
- Phase 5 invoked for an audit with exactly one endpoint.
- Phase 5 invoked for an audit at the endpoint count maximum defined by the standard commercial offering (10 endpoints).
- Phase 5 invoked for an audit where `AuditAggregate.execution_duration_ms` is zero or very small (extremely short audit window).
- Phase 5 re-invoked with `--force` for an audit that already has a `COMPLETE` intelligence record.
- Phase 5 invoked while a previous intelligence generation for the same audit is `IN_PROGRESS`.
- Phase 5 invoked for a client or audit identifier that does not exist in DynamoDB.
- Phase 5 invoked for an `aggregation_version` that does not match any persisted aggregate records.
- Phase 5 retrieval commands invoked for an audit where intelligence generation has `FAILED` status.
- Phase 5 retrieval commands invoked for an audit where intelligence generation has not yet been run.
- `FailureClassificationAggregate` is absent for an endpoint that has non-zero failures in the `EndpointAggregate`.
- `EndpointAggregate.failure_classification_counts` contains classification labels not in the approved label set defined by the Phase 4 consumer contract.

---

## 11. Constraints

- Phase 5 must require the `AggregateSetCompletion` marker before consuming any Phase 4 artifact. This is a constitutional invariant and cannot be bypassed.
- Phase 5 must consume Phase 4 aggregation artifacts only. Phase 5 must not read raw execution evidence from S3, Phase 1/2/3 DynamoDB records, `AggregationJob` records, `AggregationJobIntent` records, structured logs, or CloudWatch.
- Phase 5 must not mutate any Phase 4 aggregation artifact. The constitutional boundary is absolute: Aggregation owns facts. Phase 5 owns interpretation.
- Phase 5 must not redefine, remap, or re-classify Phase 4 failure classification labels. Classification labels must be consumed as defined by the Phase 4 consumer contract.
- Phase 5 must not implement Phase 6 (reporting), Phase 7 (audit platform integrity), or any CI/CD integration.
- Phase 5 scoring must be deterministic. AI-generated conclusions, probabilistic models trained on historical data, or heuristics without explicit threshold documentation are prohibited.
- All Phase 5 conclusions must trace to specific Phase 4 aggregate fields via documented methodology steps. Conclusions without traceable evidence are prohibited.
- The `intel_v1` methodology, thresholds, and label definitions must not change after validation without incrementing `intelligence_version`.
- Phase 5 S3 artifacts must be immutable after writing. Silent overwrite is prohibited.
- Event-driven Lambda trigger from `AggregateSetCompletion` is not in scope for Phase 5. Phase 5 is operator-invoked for the duration of Phase 5.
- Phase 5 must not implement automated release gating, CI/CD webhook delivery, or customer notification.
- The Phase 5.1 documentation subphase must be completed and HITL-approved before implementation subphases begin.

---

## 12. Dependencies

- Phase 4 aggregation layer: `AggregateSetCompletion` marker, `AuditAggregate`, `EndpointAggregate`, `FailureClassificationAggregate`, and `LineageManifest` records must be persisted and retrievable.
- Phase 4A consumer contract (`docs/architecture/phase_4a_phase5_consumer_contract.md`): defines the stable field set, DynamoDB query patterns, and `agg_v1` semantic guarantees Phase 5 must consume.
- Phase 4A aggregation schema (`docs/architecture/phase_4a_aggregation_schema.md`): defines the record types and field schemas Phase 5 reads.
- Phase 4A Engineering Retrieval CLI infrastructure: Phase 5 CLI commands extend this existing operator CLI layer.
- Existing operator CLI infrastructure (`src/release_confidence_platform/retrieval/`): the Phase 5 retrieval commands follow the same layering patterns (Command → Service → Repository → Storage Provider).
- Platform naming and schema versioning conventions (`docs/architecture/naming_and_schema_versioning.md`).
- Platform structured logging standard (`docs/architecture/structured_logging.md`).
- Platform sanitization boundary (`docs/architecture/adr_sanitization_boundary.md`): applies to all Phase 5 output.
- DynamoDB metadata table: existing platform DynamoDB resource for Phase 5 status records.
- S3 raw-results bucket: Phase 5 artifact S3 key paths must be scoped to avoid collision with Phase 4 artifact key paths.
- Phase 4A validation campaign audit data: required as input for Phase 5.8 validation campaign.

---

## 13. Assumptions

The following assumptions require confirmation before or during Phase 5.1:

- Assumption requiring confirmation: The Phase 4A validation campaign data (575 executions across 3 independent 48-hour audits) is available and lineage-complete in the development environment for Phase 5.8 validation use.
- Assumption requiring confirmation: The existing DynamoDB metadata table has sufficient capacity for Phase 5 status and score summary records under the existing resource configuration.
- Assumption requiring confirmation: The existing S3 resource supports Phase 5 artifact key namespacing without additional bucket provisioning.
- Assumption requiring confirmation: The stability, burst, and consistency analysis algorithms at the Phase 4 aggregate level (without per-run or per-window sub-totals) are sufficient to produce meaningful intelligence. If full-window summaries are insufficient for meaningful stability or burst characterization, Phase 5.1 must either (a) define the limitation explicitly in the methodology disclosure, or (b) identify whether additional Phase 4 aggregate fields are required (which would be a Phase 4 contract change requiring HITL approval).
- Assumption requiring confirmation: `intel_v1` will be implemented in Python within a new `reliability_intelligence/` module under `src/release_confidence_platform/`, following the same structural patterns as `aggregation/` and `retrieval/`.
- Assumption: Phase 5 will not require new AWS Lambda functions for the Phase 5 operator-invoked implementation. Intelligence generation runs as a CLI process, not a Lambda function, for initial implementation.

---

## 14. Open Questions

- **Stability segmentation algorithm:** Phase 4 `EndpointAggregate` records contain full-window summaries, not per-run or time-bucketed sub-totals. The Phase 5.1 technical design must specify what stability proxy signals are derivable from full-window aggregates and what limitations must be disclosed. This question must be resolved before Phase 5.3 implementation begins.
- **Burst detection proxy signals:** Similarly, burst detection without per-window sub-totals relies on distributional proxy signals. The Phase 5.1 technical design must define these signals explicitly and document what claims can and cannot be made at the aggregate level.
- **Composite score component weights:** The initial weights for reliability, stability, burst, and consistency components must be specified in Phase 5.1 and are not pre-defined in this product spec. Weights must be documented and stable within `intel_v1`.
- **Phase 6 consumer contract timing:** The Phase 6 consumer contract is a Phase 5.1 deliverable. Its content depends on the Phase 5 artifact schema defined during Phase 5.1 technical design. The contract must be HITL-approved before Phase 5.2 implementation begins.
- **DynamoDB key schema for Phase 5 records:** The PK/SK pattern for Phase 5 status and metadata records must be defined in the Phase 5.1 technical design, following platform naming conventions and avoiding collision with Phase 4 record key patterns.

---

## 15. QA Expectations

QA validation for Phase 5 must include:

- Unit tests for each Reliability Metrics Core derivation confirming correct success rate, failure classification, and latency profile computation from known fixture Phase 4 aggregate inputs.
- Unit tests confirming divide-by-zero and zero-denominator edge cases are handled without exceptions and produce correct `INSUFFICIENT_DATA` labels.
- Unit tests for stability label assignment confirming each label is deterministically produced from documented threshold inputs.
- Unit tests for burst label assignment confirming each label is deterministically produced from documented proxy signal inputs.
- Unit tests for consistency label assignment confirming each label is deterministically produced.
- Unit tests for composite score computation confirming component values and weights are correctly applied.
- Determinism tests confirming byte-identical Phase 5 artifact JSON output for identical Phase 4 aggregate fixture inputs across two independent invocations.
- Unit tests confirming Phase 5 generation terminates with a structured error when `AggregateSetCompletion` is absent.
- Unit tests confirming Phase 5 does not mutate any Phase 4 fixture aggregation record during generation.
- Unit tests confirming Phase 5 never reads raw evidence fixture objects.
- Unit tests for per-endpoint evidence trace completeness: every trace must include Phase 4 source field references, algorithm names, threshold values, and intermediate computation values.
- Unit tests for methodology disclosure completeness: all required fields present.
- Unit tests for all Phase 5 retrieval commands confirming correct artifact retrieval from known fixture intelligence state.
- Unit tests confirming deterministic retrieval output ordering for Phase 5 retrieval commands.
- Unit tests confirming provenance envelope is present on every retrieval command output.
- Tests confirming JSON and human-readable output formats for retrieval commands.
- Integration tests confirming Phase 5 generation produces correct artifacts against known Phase 4 aggregate fixtures.
- Integration tests confirming DynamoDB status records are written correctly at each generation status transition.
- Integration tests confirming S3 artifact is written correctly and contains all required sections.
- Phase 6 consumer contract compatibility gate tests: automated tests that validate Phase 6 consumer contract stability when Phase 5 artifact schema changes.
- Validation campaign (Phase 5.8): live intelligence generation against Phase 4A validation campaign audit data with HITL sign-off confirming correctness, reproducibility, and no hallucinated conclusions.

---

## 16. Scope Risks

- **Stability and burst analysis approximation risk.** Phase 4 aggregates are full-window summaries without per-run or time-bucketed sub-totals. Stability and burst characterization from these inputs requires proxy signals and approximations. There is a risk that the resulting labels are not meaningful enough to contribute to a credible Release Confidence Score, or that the methodology limitations undermine customer trust. Resolution: Phase 5.1 technical design must explicitly model what can and cannot be concluded, and the methodology disclosure must state limitations clearly. If proxy signals are insufficient, the technical design must either define what additional Phase 4 aggregate fields are needed (requiring a Phase 4 contract amendment) or scope down the analysis to what is genuinely supportable.
- **Composite score weight calibration.** Component weights in the Release Confidence Score are not pre-validated against real-world outcomes. There is a risk that initial weights produce scores that do not reflect operator intuition about reliability. Resolution: Phase 5.1 must define weights explicitly with documented rationale, and Phase 5.8 validation must include human review of score outputs against known-good and known-bad audit campaigns.
- **Phase 6 scope pull-in.** Phase 5 artifact schemas and retrieval commands may be pressured to include formatted report sections, executive summaries, or recommendation text. These are Phase 6 behaviors and are explicitly out of scope. Phase 5 intelligence artifacts contain structured data and methodology traces. Formatting and narrative are Phase 6 responsibilities.
- **Event-driven trigger scope creep.** The deferred `AggregateSetCompletion` Lambda trigger may be pressured into Phase 5 before manual generation is validated. This must not proceed until Phase 5.8 validation confirms that intelligence generation is deterministic and reproducible.
- **AI-assisted scoring rationalization.** There is a platform-level risk that scoring complexity may invite AI-assisted label or score generation. This is prohibited by the product constitution and by NFR-6. All scoring must remain deterministic and explicitly rule-based.
- **Phase 4 consumer contract stability.** If Phase 4 aggregate schema changes are needed to support Phase 5 analysis (e.g., additional statistical fields), those changes require a Phase 4 contract version increment, HITL approval, and compatibility gate test updates. Discovery of such requirements during Phase 5.1 must be escalated before implementation begins.
