# Product Specification

## 1. Feature Overview

Phase 4A is a brownfield initiative that validates, formalizes, and extends the deterministic aggregation foundation delivered by Phase 4. It introduces the Engineering Retrieval Layer, defines the authoritative Phase 5 consumer contract, and eliminates accumulated brownfield operational debt.

Phase 4 implemented the aggregation core: lifecycle-triggered job orchestration, evidence integrity validation, deterministic aggregate computation, immutable lineage manifests, and aggregate-set completion markers. Phase 4A confirms that implementation is production-ready and adds the operational tooling and contractual boundaries required before Phase 5 may begin.

Phase 4A has seven sequential subphases. Phases 4A.1–4A.3 are documentation-only. Phase 4A.4 validates and hardens aggregation persistence. Phase 4A.5 implements the Engineering Retrieval CLI. Phase 4A.6 eliminates brownfield debt. Phase 4A.7 closes the phase through a controlled operational validation campaign.

Phase 4A does not implement reliability scoring, AI insights, reporting, dashboards, release recommendations, or any customer-facing or operator-facing experience.

### Backend / System Impact

- Aggregation persistence is validated and confirmed production-ready.
- An Engineering Retrieval CLI is introduced for internal operational debugging, evidence inspection, and audit traceability.
- The Phase 5 consumer contract is formally published as a platform constitution document.
- The `src/` and `packages/` dual-copy divergence is remediated.
- Structured logging is improved across orchestration, scheduling, execution, lifecycle, finalization, and aggregation.

## 2. Problem Statement

Phase 4 delivered the aggregation core but the platform lacks:

1. **Engineering Retrieval** — no tooling exists to inspect aggregation artifacts, lineage, lifecycle transitions, retry history, or consolidated operational logs. Engineers must query DynamoDB directly or read CloudWatch logs to investigate aggregation state.

2. **Phase 5 Consumer Contract** — there is no formally published stable contract defining what aggregation exposes to Phase 5, what Phase 5 may consume, and what boundaries Phase 5 must respect. Without this contract, Phase 5 implementation risks consuming raw evidence directly or creating coupling that undermines aggregation's authoritative role.

3. **Brownfield Operational Debt** — the `src/release_confidence_platform/` and `packages/` directories contain divergent copies of the same modules. This synchronization risk will cause silent behavioral divergence as features evolve. Deterministic startup validation and import smoke testing are absent.

4. **Operational Validation Gap** — no extended operational validation has been performed. Short-duration development tests are insufficient to confirm sustained deterministic behavior under real execution conditions.

## 3. User Persona / Target User

- **Platform engineer / developer:** inspects aggregation state, debugs lifecycle failures, validates evidence lineage, and uses the Engineering Retrieval CLI for operational support.
- **QA engineer:** validates retrieval command correctness, aggregation persistence, lineage, operational logging, and retry behavior.
- **Future internal analytical consumer (Phase 5):** consumes the Phase 5 consumer contract to implement reliability intelligence without re-implementing aggregation or accessing raw evidence directly.

No operator or customer-facing persona is in scope for Phase 4A.

## 4. User Stories

- As a platform engineer, I want an Engineering Retrieval CLI so that I can inspect aggregation results, lineage, lifecycle transitions, retry history, and operational logs without querying DynamoDB directly or reading raw CloudWatch logs.
- As a platform engineer, I want consolidated engineering logs for any audit so that I can trace the full lifecycle from scheduling through aggregation in a single operation.
- As a QA engineer, I want retrieval commands with JSON output so that I can script assertions against aggregation state without parsing unstructured logs.
- As a future Phase 5 implementer, I want a formally published consumer contract so that I can implement reliability intelligence against stable aggregation outputs without coupling to raw evidence or internal aggregation implementation details.
- As a platform engineer, I want the `src/packages` divergence resolved so that code changes propagate consistently without silent divergence risk.

## 5. Goals / Success Criteria

Phase 4A is successful when:

- Multiple independent 48-hour audit campaigns complete successfully with deterministic lifecycle progression to `COMPLETED`.
- Aggregation executes successfully and artifacts persist for every eligible audit.
- Engineering Retrieval CLI returns deterministic, correct results for all required commands.
- Evidence lineage is intact and traceable through retrieval commands.
- Aggregation reproducibility is validated.
- Structured logging provides sufficient operational traceability without exposing sensitive payload content.
- Retry behavior is validated under operational conditions.
- `src/packages` divergence is remediated with no behavioral regressions.
- Phase 5 consumer contract is formally published and HITL-approved.
- All GitHub Issues closed, all HITL gates passed, all implementation PRs merged.

## 6. Feature Scope

### In Scope

Phase 4A includes only the following:

- Aggregation persistence validation and hardening (Phase 4A.4).
- Engineering Retrieval CLI for internal operational debugging and evidence inspection (Phase 4A.5).
- Structured logging improvements across orchestration, scheduling, execution, lifecycle, finalization, and aggregation (Phase 4A.5).
- Phase 5 consumer contract publication as a platform constitution document with explicit ownership boundary statement: Aggregation owns facts. Phase 5 owns interpretation (Phase 4A.3).
- Remediation of the `src/packages` dual-copy divergence (Phase 4A.6).
- Deterministic startup validation and import smoke testing improvements (Phase 4A.6).
- Controlled operational validation campaign with multiple 48-hour audits (Phase 4A.7).
- GitHub Issues for each subphase with predecessor/successor references (all).

### Out of Scope

The following are explicitly excluded from Phase 4A:

- Phase 5 Reliability Intelligence implementation.
- Phase 6 Reporting implementation.
- Phase 7 CI/CD Integration implementation.
- Customer-facing retrieval CLI or evidence export.
- Operator-facing aggregation workflows.
- Reliability scoring, AI insights, release confidence conclusions, or release gating.
- Predictive analytics, trend interpretation, or root-cause inference.
- Public or customer-facing API surface.
- Raw evidence mutation, deletion, compaction, or reclassification.
- New dashboards, visualizations, or operator reports.
- Authentication, RBAC, billing, subscriptions, or account management.

### Future Considerations

- Customer-facing evidence retrieval CLI belongs to a later roadmap phase.
- Phase 4A retrieval architecture must allow future expansion without breaking compatibility.
- Privileged administrative disaster-recovery aggregation invocation remains deferred from Phase 4A.

## 7. Functional Requirements

### FR-P1: Engineering Retrieval Layer — Constitutional Read-Only Guarantee

The Engineering Retrieval Layer is a platform invariant. It SHALL NEVER create, update, delete, repair, recompute, compact, or otherwise modify persisted audit evidence, aggregation artifacts, lineage manifests, lifecycle records, or any platform state.

Allowed operations are limited to: **inspect**, **retrieve**, **list**, **summarize**, **verify**, and **export**.

This guarantee is unconditional and applies regardless of the requested output format, filtering parameters, or operational context. Violation of this invariant compromises evidence integrity and trustworthiness.

### FR-P1a: Engineering Retrieval CLI — Required Commands

The Engineering Retrieval CLI must implement the following commands:

| Command | Purpose |
| --- | --- |
| `retrieve aggregation-results` | Return the complete aggregation artifact set for an audit |
| `retrieve aggregation-metadata` | Return job metadata: status, counts, timestamps |
| `retrieve aggregation-lineage` | Return lineage manifest references and source ref counts |
| `retrieve aggregation-status` | Return current aggregation job status and reason code |
| `retrieve orchestration-timeline` | Return chronological orchestration events |
| `retrieve lifecycle-transitions` | Return lifecycle state history for an audit |
| `retrieve execution-summary` | Return execution counts, durations, and outcome summary |
| `retrieve audit-event-timeline` | Return ordered event timeline across audit lifecycle |
| `retrieve engineering-logs` | Return consolidated sanitized engineering log events |
| `retrieve retry-history` | Return aggregation job retry attempts and outcomes |
| `retrieve aggregation-generation-status` | Return aggregation completeness and generation state |
| `retrieve aggregation-version` | Return aggregation version metadata |
| `retrieve evidence-references` | Return bounded lineage manifest source references |
| `retrieve failure-summaries` | Return failure classification counts and reason codes |
| `retrieve processing-timeline` | Return per-stage processing timestamps |

### FR-P1b: Engineering Retrieval CLI — Output Provenance

Every retrieval command output must include provenance metadata as a top-level envelope:

```
retrieved_at        — UTC ISO-8601 timestamp of this retrieval
retrieval_version   — version of the retrieval layer
aggregation_version — aggregation_version of the artifact(s) retrieved
manifest_hash       — manifest_hash from the AggregateSetCompletion marker (when applicable)
audit_id            — scoped audit identifier
client_id           — scoped client identifier
```

Retrieved output must include the following disclaimer in human-readable format:

> "This output is for engineering diagnostics only. Authoritative evidence resides in immutable aggregation artifacts."

For JSON output, this disclaimer must appear as a top-level `_notice` field with a fixed controlled string value.

### FR-P1c: Engineering Retrieval CLI — Deterministic Output Ordering

The retrieval layer must produce deterministically ordered output for all collections. For identical persisted aggregation state, retrieval output must be identical across repeated invocations.

Canonical ordering precedence for all collections:

1. `audit_id`
2. `audit_execution_id`
3. `endpoint_id`
4. `scenario_id`
5. `timestamp` (ascending)

### FR-P1d: Engineering Retrieval CLI — Storage Abstraction Layering

The Engineering Retrieval CLI must not interact with storage implementation details directly. The retrieval architecture must follow this layering:

```
CLI Command
    ↓
RetrievalService
    ↓
RetrievalRepository
    ↓
Storage Provider (DynamoDB / S3)
```

`RetrievalService` owns all query logic and returns immutable snapshot DTOs. `RetrievalRepository` owns all storage provider interactions. CLI commands own only argument parsing and output formatting.

This layering ensures future storage evolution does not require changes to retrieval commands.

### FR-P1e: Engineering Retrieval CLI — Immutable Retrieval DTOs

`RetrievalService` must return immutable snapshot DTOs. Formatting and serialization layers must not mutate retrieval objects. This guarantees deterministic behavior and simplifies future validation.

### FR-P1f: Engineering Retrieval CLI — Canonical Serialization

`RetrievalFormatter` must normalize before output generation:

- Field ordering (canonical alphabetical or defined priority order)
- Collection ordering (canonical precedence per FR-P1c)
- Timestamp formatting (UTC ISO-8601)
- Numeric precision (consistent decimal representation)

For identical persisted state, serialized JSON output must be byte-identical across invocations.

### FR-P2: Engineering Retrieval CLI — Output Formats

All retrieval commands must support:

- `--output json` — machine-readable JSON for scripting and QA assertions.
- `--output human` (default) — formatted human-readable output for operational inspection.

### FR-P3: Engineering Retrieval CLI — Filtering

All retrieval commands must support filtering by:

- `--client <client_id>`
- `--audit <audit_id>`
- `--run <run_id>` (where applicable)
- `--endpoint <endpoint_id>` (where applicable)
- `--scenario <scenario_id>` (where applicable)
- `--window <execution_window>` (where applicable — ISO-8601 range)

### FR-P4: Engineering Retrieval CLI — Sensitive Data Exclusion

Retrieval command output must not expose:

- Raw request or response bodies.
- Headers, cookies, tokens, credentials, PII.
- Raw S3 keys in log output (use sanitized key references).
- Tenant-sensitive raw evidence content.

The same sensitive-data exclusion policy from Phase 4 aggregation applies to all retrieval output.

### FR-P5: Structured Logging Improvements

Structured logs are operational diagnostics. They shall never become authoritative evidence or replace immutable aggregation artifacts. The platform evidence hierarchy is: raw execution evidence → aggregation artifacts → lineage manifests → aggregate-set completion markers. Structured logs support debugging but are not part of this chain.

Structured logging must be improved to provide sufficient operational traceability across all lifecycle stages without exposing sensitive payload content. Logs must include stable correlation fields enabling cross-stage timeline reconstruction.

Required log coverage:

- Orchestration: job claim, eligibility decision, integrity gate result, write outcome.
- Scheduling: schedule creation, execution trigger, window evaluation.
- Execution: run started, run completed, evidence captured, evidence count.
- Lifecycle: state transitions with from/to state, reason, actor, timestamp.
- Finalization: eligibility, gate result, aggregation intent recorded, invocation status.
- Aggregation: job started, integrity gate passed/failed, manifest written, set completed, failure outcome.

### FR-P6: src/packages Divergence Remediation

The `src/release_confidence_platform/` and `packages/` directories must be synchronized. Divergent logic, inconsistent implementations, and duplicate module copies must be resolved. The resolution strategy must:

- Eliminate behavioral divergence without introducing regressions.
- Define a clear authority for each module.
- Include startup validation to detect future divergence early.

### FR-P7: Deterministic Startup and Import Validation

Deterministic startup validation must confirm that critical module imports succeed and that required environment configuration is present before serving requests. Import smoke tests must be executable as part of deployment validation.

## 8. Non-Functional Requirements

### NFR-P1: Engineering Retrieval CLI Correctness

Retrieval commands must return data consistent with the persisted aggregation state. Commands must not mutate any persisted state.

### NFR-P2: Retrieval Output Determinism

For the same persisted aggregation state, retrieval commands must return identical output. Human-readable and JSON outputs must reflect the same underlying data.

### NFR-P3: Operational Traceability

Structured logs must enable reconstruction of the complete audit lifecycle timeline from scheduling through aggregation using only the Engineering Retrieval CLI and structured log queries.

### NFR-P4: Backward Compatibility

Phase 4A changes must not break existing Phase 4 behavior. The aggregation lifecycle, persistence, and lineage contracts remain unchanged.

### NFR-P5: Phase 5 Consumer Contract Stability

The Phase 5 consumer contract published in Phase 4A.3 must remain stable. Any change to aggregation output that would break the contract must follow a formal versioning process.

## 9. Acceptance Criteria

### AC-P1: Engineering Retrieval CLI Completeness

Given an audit that has completed aggregation successfully  
When `retrieve aggregation-results` is executed with the correct client and audit identifiers  
Then the command returns the complete aggregate artifact set with correct counts, distributions, and lineage references.

Given an audit with a failed aggregation job  
When `retrieve failure-summaries` is executed  
Then the command returns the failure classification, reason code, failure category, and job metadata without exposing raw evidence content.

### AC-P1a: Retrieval Output Provenance

Given any retrieval command executed for a completed audit  
When the command output is inspected  
Then the output includes provenance metadata: `retrieved_at`, `retrieval_version`, `aggregation_version`, `manifest_hash`, `audit_id`, `client_id`, and the engineering diagnostic disclaimer.

### AC-P1b: Deterministic Retrieval Reproducibility

Given any retrieval command executed twice for the same audit with identical persisted aggregation state  
When both outputs are compared  
Then the serialized JSON output is byte-identical across both invocations.

### AC-P2: JSON Output Format

Given any retrieval command  
When `--output json` is specified  
Then the command returns well-formed JSON that can be parsed programmatically.

### AC-P3: Filtering by Audit and Client

Given a system with multiple audits across multiple clients  
When a retrieval command is executed with `--client` and `--audit` filters  
Then the command returns data only for the specified client/audit combination.

### AC-P4: Sensitive Data Exclusion From Retrieval Output

Given an audit with raw evidence containing headers, response bodies, and raw URLs  
When any retrieval command is executed  
Then the command output contains no raw headers, response bodies, raw URLs, credentials, PII, or sensitive payload fragments.

### AC-P5: Structured Logging Coverage

Given aggregation is triggered after successful finalization  
When the engineering log retrieval command is executed for that audit  
Then the output includes log events covering orchestration, integrity gate evaluation, manifest write, and aggregate-set completion.

### AC-P6: src/packages Divergence Resolved

Given the Phase 4A.6 operational hardening PR is merged  
When the same code path is exercised through both `src/` and `packages/` module paths  
Then behavior is identical and no divergence-related test failures occur.

### AC-P7: Import Smoke Test Passes

Given a clean deployment environment  
When the import smoke test suite is executed  
Then all critical handler and module imports succeed without errors.

### AC-P8: Operational Validation Campaign

Given Phase 4A.4–4A.6 are merged  
When multiple independent 48-hour audit campaigns are executed  
Then all campaigns complete with the lifecycle reaching `COMPLETED`, aggregation artifacts persisting, retrieval commands returning deterministic results, and no operational regressions.

## 10. Edge Cases

- Retrieval commands executed for an audit with no aggregation yet triggered.
- Retrieval commands executed for an audit with an in-progress aggregation job.
- Retrieval commands executed for an audit with a failed aggregation job.
- Retrieval commands executed with an unknown client or audit identifier.
- Retrieval of a very large aggregation artifact set.
- Structured log retrieval for an audit that experienced lifecycle state retries.
- Import smoke test executed in an environment missing required environment variables.
- `src/packages` divergence remediation applied to a module with behavioral differences between copies.

## 11. Constraints

- Phase 4A.5 Engineering Retrieval CLI is engineering-facing only; customer-facing retrieval is out of scope.
- Phase 4A must not implement Phase 5, Phase 6, or Phase 7 behavior.
- All Phase 4 aggregation invariants (immutability, lineage, idempotency, determinism) remain in effect throughout Phase 4A.
- Retrieval commands must not mutate persisted state. The Engineering Retrieval Layer is a platform invariant: allowed operations are inspect, retrieve, list, summarize, verify, and export only.
- Structured logs are operational diagnostics only. They shall never become authoritative evidence or replace immutable aggregation artifacts.
- The Phase 5 consumer contract once published is immutable except through a formal versioning process requiring contract version increment, HITL approval, and explicit consumer migration documentation.
- The Phase 5 consumer contract constitutes a compatibility gate. Future aggregation changes that would break the published contract require a new contract version, HITL approval, and automated regression test validation before implementation.
- Aggregation owns facts. Phase 5 owns interpretation. Phase 5 shall never redefine or reinterpret persisted aggregation facts.
- Operational validation campaign requires multiple 48-hour audits; short-duration audits do not satisfy Phase 4A closure requirements.

## 12. Dependencies

- Phase 4 implementation: aggregation persistence, lineage manifests, aggregate-set completion markers, and DynamoDB data models.
- Existing operator CLI infrastructure (`apps/operator_cli/` or `apps/backend/`).
- Phase 3 lifecycle and finalization metadata in DynamoDB.
- Phase 1/2 raw execution evidence in S3.
- Existing identifier validation, sanitization utilities, and DynamoDB/S3 access patterns.

## 13. Assumptions

- Phase 4 aggregation is fully implemented and merged on `main` before Phase 4A documentation is produced.
- The Engineering Retrieval CLI will be implemented as an extension of or separate addition to the existing operator CLI infrastructure.
- Structured logging improvements will use the existing structured logging standard defined in `docs/architecture/structured_logging.md`.
- The `src/packages` divergence resolution will not require breaking changes to deployment infrastructure.

## 14. Open Questions

- None.

## 15. QA Expectations

QA validation for Phase 4A must include:

- Unit tests for each retrieval command confirming correct data extraction and formatting.
- Unit tests confirming sensitive data exclusion from retrieval output.
- Provenance validation tests confirming every retrieval output includes `retrieved_at`, `retrieval_version`, `aggregation_version`, `manifest_hash`, `audit_id`, `client_id`, and the engineering diagnostic disclaimer.
- Deterministic serialization tests confirming byte-identical JSON output for identical persisted state across two independent invocations.
- Integration tests confirming retrieval returns correct data for known fixture aggregation state.
- Tests confirming JSON and human-readable output formats.
- Tests confirming filtering by client, audit, run, endpoint, scenario, and window.
- Consumer contract compatibility gate tests: automated regression tests that validate Phase 5 consumer contract stability when aggregation artifacts change.
- Structured logging coverage tests confirming required log events are emitted.
- Import smoke tests covering all Lambda handlers and critical module imports.
- `src/packages` divergence tests confirming behavioral equivalence post-remediation.
- Operational validation: multiple independent 48-hour audit campaigns with HITL sign-off.

## 16. Scope Risks

- The Engineering Retrieval CLI may be pressured to include customer-facing evidence output. This remains explicitly out of scope.
- Phase 5 timeline pressure may attempt to pull reliability conclusions into Phase 4A retrieval output. The consumer contract must remain a read-only data interface with no scoring or conclusions.
- `src/packages` divergence remediation may expose hidden behavioral differences that require additional investigation before resolution.
- Structured logging improvements must not inadvertently log sensitive payload content.
