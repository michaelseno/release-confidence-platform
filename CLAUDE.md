# Release Confidence Platform (RCP)

## Authoritative Sources

Read and follow these documents before making product, architecture, or implementation decisions:

### Product Constitution

- `RCP_Product_Strategy.md`

This is the authoritative product constitution.

### Architecture

- `docs/architecture/architecture_overview.md`
- `docs/architecture/execution_lifecycle.md`
- `docs/architecture/naming_and_schema_versioning.md`
- `docs/architecture/structured_logging.md`

### Methodology

- `docs/audit-methodology/raw_evidence_philosophy.md`
- `docs/operational-safety/operational_philosophy.md`

### Architecture Decisions

Review relevant ADRs before modifying behavior that affects architecture, execution lifecycle, evidence handling, aggregation, scheduling, storage, or reporting.

---

# Product Identity

RCP is an Independent API Reliability Audit Platform.

RCP is NOT:

- a testing framework
- a QA automation platform
- a CI/CD utility
- a monitoring platform
- a synthetic monitoring platform
- an AI testing platform
- a dashboard-first product

RCP exists to generate trustworthy, evidence-backed Release Confidence Assessments.

---

# Decision Hierarchy

When conflicts exist, follow this order:

1. Product Constitution
2. ADRs
3. Architecture Documents
4. Technical Design Documents
5. Implementation Convenience

Implementation convenience never overrides architecture or product principles.

---

# Core Product Principles

Trust is the product.

Always prioritize:

1. Runner correctness
2. Evidence integrity
3. Deterministic execution
4. Data integrity
5. Audit repeatability
6. Operational safety
7. Customer trust

Do not recommend shortcuts that compromise these principles.

---

# Phase Governance

Follow the locked roadmap defined in `RCP_Product_Strategy.md`.

Current completed phases:

- Phase 0
- Phase 1
- Phase 2
- Phase 3

Current active focus:

- Phase 4
- Phase 4A

Do not introduce future-phase functionality unless explicitly requested.

When proposing a solution, identify the impacted phase.

---

# Architecture Principles

Every implementation should be:

- deterministic by default
- explainable by default
- auditable by default
- traceable by default
- secure by default

Avoid:

- hidden behavior
- magic automation
- opaque scoring
- unverifiable conclusions

---

# Evidence Principles

Raw evidence is the source of truth.

All conclusions, reports, scores, findings, recommendations, and assessments must trace back to evidence lineage.

Never introduce derived conclusions without traceability.

---

# Safety Requirements

Do not bypass:

- production authorization requirements
- destructive operation controls
- request caps
- concurrency caps
- audit duration limits
- payload safety controls
- environment restrictions

---

# Development Workflow

Before implementation:

1. Identify the impacted phase.
2. Review relevant ADRs.
3. Review relevant technical design documents.
4. Create a concise implementation plan.
5. Implement incrementally.
6. Update tests when behavior changes.
7. Validate before claiming completion.
8. Update documentation when architecture, behavior, contracts, or methodology change.

---

# Review Triggers

Use architecture review when changes affect:

- execution lifecycle
- scheduling
- aggregation
- storage
- API contracts
- persistence
- infrastructure

Use security review when changes affect:

- authentication
- authorization
- secrets
- credentials
- permissions
- production execution
- external integrations

Use QA review when changes affect:

- runner behavior
- evidence generation
- aggregation output
- scheduling
- finalization
- audit results

---

# Documentation Rules

Prefer updating existing documents before creating new ones.

Implementation plans, reports, QA reports, issues, and PR documents are historical artifacts.

Do not treat historical artifacts as the primary source of truth.

Prefer:

1. Product Constitution
2. ADRs
3. Architecture Documents
4. Active Phase Technical Design
5. Historical Artifacts

---

# Release Rules

Do not create a PR until:

- implementation is complete
- validation passes
- QA approval exists
- human validation exists

Required approval phrase:

HITL validation successful

---

# Response Expectations

When proposing changes include:

- impacted phase
- affected modules
- risks
- validation required
- documentation impact

Prefer correctness over speed.
