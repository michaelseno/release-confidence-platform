# ADR: Phase 4A — Engineering Retrieval Layer and Phase 5 Consumer Contract

## Status

Proposed

## Context

Phase 4 delivered the deterministic aggregation core. The following gaps remain before Phase 5 may begin:

1. **No operational retrieval interface.** Engineers must query DynamoDB directly or parse unstructured CloudWatch logs to inspect aggregation state, lineage, lifecycle transitions, or retry history. This is operationally unsafe and prevents systematic debugging.

2. **No Phase 5 consumer contract.** Phase 5 (Reliability Intelligence) is the next phase of the platform. Without a formally published contract defining what Phase 5 may consume from aggregation and what boundaries it must respect, Phase 5 implementation risks coupling to raw evidence, internal aggregation implementation details, or aggregation metadata that is not stable.

3. **src/packages divergence.** Two directory trees contain copies of the same modules: `src/release_confidence_platform/` and `packages/`. This dual-copy pattern creates synchronization risk. Bug fixes applied to one copy may not propagate to the other, causing silent behavioral divergence.

4. **Inconsistent structured logging.** Lifecycle stages emit structured events at inconsistent granularity. Timeline reconstruction across scheduling, execution, finalization, and aggregation requires manual cross-correlation.

These gaps must be addressed before Phase 5 begins. Phase 4A is the brownfield initiative that closes them.

## Decision

### Decision 1: Engineering Retrieval Layer as CLI, Not API

The Engineering Retrieval Layer will be implemented as a CLI extension (`rcp retrieve`) within the existing operator CLI infrastructure, not as a new HTTP API or Lambda function.

**Rationale:**
- Engineering retrieval is an internal operational tool, not a product feature.
- CLI delivery is faster to implement, easier to secure (IAM-gated local execution), and does not introduce a new HTTP surface.
- Existing DynamoDB access patterns can be reused directly.
- A CLI is appropriate for the operational debugging, evidence inspection, and audit traceability use cases.

**Constraint:**
- Retrieval commands are strictly read-only.
- Sensitive data exclusion rules from Phase 4 aggregation apply to all retrieval output.
- The CLI is not customer-facing. Customer-facing evidence retrieval belongs to a later phase.

### Decision 2: Phase 5 Consumer Contract Published as Platform Constitution Document

The Phase 5 consumer contract will be a formally published document (`docs/architecture/phase_4a_phase5_consumer_contract.md`) that is HITL-approved before Phase 5 implementation begins. It is not a runtime API contract; it is a design-time contract that governs what Phase 5 may consume.

**Rationale:**
- A runtime enforcement mechanism would require additional infrastructure (e.g., a read-through API layer) that is premature and out of scope.
- A design-time contract enforced through HITL review is appropriate for an internal multi-phase platform where all phases are built by the same team.
- Publishing the contract as a platform constitution document makes it durable, discoverable, and formally under governance.

**Contract Principles:**
1. Aggregation owns data. Phase 5 owns interpretation.
2. Phase 5 must not consume raw execution evidence.
3. Phase 5 must not mutate aggregation artifacts.
4. Phase 5 must require the `AggregateSetCompletion` marker before consuming child aggregate records.
5. Phase 5 must not reinterpret raw evidence through its own summarization logic.

**Versioning:**
- The contract is versioned alongside `aggregation_version`. Changes to Phase 4A.3 contract require a new version and HITL approval.

### Decision 3: src/packages Divergence — src/ Is Canonical, packages/ Is Synchronized

`src/release_confidence_platform/` is the canonical implementation. Lambda functions must import from `src/`. `packages/` copies will be synchronized to match `src/`, and a divergence detection test will be added.

**Rationale:**
- The `packages/` directory appears to be a legacy deployment artifact from an earlier packaging strategy.
- All Phase 4 aggregation code exists only in `src/`, not `packages/`. This confirms `src/` is the active development path.
- Synchronizing `packages/` to `src/` eliminates divergence while preserving the `packages/` directory structure for any external tooling that may reference it.

**Implementation:**
- Audit each divergent module pair before making changes.
- Apply `src/` changes to `packages/` where divergence exists.
- Add a CI test that validates behavioral equivalence for critical functions.
- Add startup validation to Lambda handlers to catch import failures at cold start.

**Alternative considered:** Remove `packages/` entirely. Rejected because it may break external tooling or deployment scripts that reference `packages/`. Synchronization is safer.

### Decision 4: Structured Logging Improvements Are Additive

Structured logging improvements in Phase 4A.5 will add new structured log events alongside existing ones. Existing log events will not be renamed, removed, or restructured.

**Rationale:**
- Breaking existing log patterns would invalidate any existing CloudWatch dashboards, alerts, or queries.
- Additive improvement is backward compatible.
- New events can be selectively adopted by operational tooling without forcing migration.

**Constraint:**
- New log events must follow the structured logging standard in `docs/architecture/structured_logging.md`.
- Logs must not include sensitive payload content.

## Alternatives Considered

### Engineering Retrieval as a Lambda Function

Rejected. A Lambda function would require a new invocation surface, IAM configuration, and deployment plumbing. The retrieval use case is operational debugging, which a CLI handles without those costs.

### Phase 5 Consumer Contract as a Runtime Enforcement Layer

Rejected. A runtime enforcement layer (e.g., a read-through aggregation API that Phase 5 calls) would require additional infrastructure that is premature in Phase 4A. Design-time governance through a HITL-approved constitution document is sufficient.

### Remove packages/ Entirely

Rejected. External tooling may reference `packages/`. Synchronization is the safer approach.

### Rewrite src/ to match packages/ Where They Diverge

Rejected. `src/release_confidence_platform/aggregation/` — the most recently implemented module — exists only in `src/`, confirming `src/` is the active development canonical. `packages/` should follow `src/`, not the reverse.

### Structured Logging Replacement (Replace Old Events)

Rejected. Replacing existing log events would break existing observability configuration. Additive improvement is the correct approach.

## Consequences

### Benefits

- Engineers gain a read-only CLI to inspect any aggregation artifact, lineage record, or lifecycle timeline without direct DynamoDB access.
- Phase 5 has a formally approved stable contract that defines its data access boundaries before it begins implementation.
- `src/packages` synchronization eliminates the silent divergence risk accumulated since Phase 4.
- Improved structured logging enables timeline reconstruction across all lifecycle stages.

### Costs and Risks

- Engineering Retrieval CLI adds implementation scope in Phase 4A.5. Retrieval commands must be validated against real aggregation data to confirm correctness.
- Phase 5 consumer contract may require additions as Phase 5 implementation discovers gaps; each addition requires formal versioning and HITL approval.
- `src/packages` audit may reveal more behavioral divergence than expected, expanding Phase 4A.6 scope.
- Structured logging improvements add test coverage requirements.

## Traceability

- Product spec: `docs/product/phase_4a_aggregation_foundation_product_spec.md`
- Technical design: `docs/architecture/phase_4a_aggregation_foundation_technical_design.md`
- Test plan: `docs/qa/phase_4a_aggregation_foundation_test_plan.md`
- Phase 5 consumer contract: `docs/architecture/phase_4a_phase5_consumer_contract.md` (Phase 4A.3 deliverable)
- Phase 4 ADR: `docs/architecture/adr_phase_4_evidence_lineage_aggregation.md`
