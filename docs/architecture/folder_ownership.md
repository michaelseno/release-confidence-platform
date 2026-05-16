# Folder Ownership Standards

- `apps/backend/orchestrator`: future audit/run orchestration.
- `apps/backend/runner`: future endpoint/scenario execution.
- `apps/backend/aggregator`: future raw result aggregation.
- `apps/backend/analytics`: future deterministic analytics and scoring.
- `apps/backend/reporting`: future report assembly.
- `apps/backend/handlers`: future Lambda entrypoints.
- `apps/frontend`: Phase 0 README placeholder only.
- `packages/core`: shared constants, schemas, models, and exceptions.
- `packages/config`: future config loading/validation boundaries.
- `packages/data-generation`: future deterministic data generation boundary; not import-safe in Phase 0.
- `packages/sanitization`: future redaction boundary.
- `packages/storage`: future AWS client wrappers; no live calls in Phase 0.
- `packages/report-engine`: future report rendering boundary; not import-safe in Phase 0.
- `infra`: Serverless Framework and CloudFormation resource fragments.
- `configs/samples`: safe, fake sample configuration only.
- `tests`: local validation tests and future mock API scaffolding.
- `scripts`: local developer validation utilities that do not mutate cloud resources.
