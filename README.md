# Release Confidence Platform

Release Confidence Platform is an **Operational API Reliability Audit Platform** focused on release confidence, deterministic evidence collection, operational reliability assessment, evidence-driven API auditing, and trustworthy operational findings.

The platform is backend-first. It is designed to collect sanitized, versioned operational evidence from API audit executions so later findings can remain traceable to raw execution records. It does not currently provide a dashboard or frontend application beyond the placeholder boundary in `apps/frontend/README.md`.

## Architecture Overview

Current backend flow:

```text
EventBridge Scheduler
  -> Lambda Orchestrator / scheduled handlers
  -> Config Resolver
  -> Runner Execution
  -> Sanitization
  -> S3 Raw Evidence
  -> DynamoDB Metadata
  -> aggregation / analytics / reporting boundaries
```

Key architectural boundaries:

- **EventBridge Scheduler:** triggers scheduled audit occurrences for baseline, burst, repeated, and finalization scenarios. Scheduler payloads are minimal and secret-free.
- **Lambda orchestrator and handlers:** validate scheduled events, enforce lifecycle and operational rules, claim occurrence IDs, and invoke the existing execution contract.
- **Config resolver:** loads and validates audit/client/endpoint configuration and ensures only approved references are used.
- **Runner execution:** performs outbound API requests within configured safety limits and produces raw execution records.
- **Sanitization:** removes or masks sensitive values before persistence or logging.
- **S3 raw evidence:** stores sanitized raw result evidence as the source of truth for later assessment.
- **DynamoDB metadata:** stores audit lifecycle metadata, run metadata, schedule metadata, duplicate-delivery claims, and execution counters.
- **Aggregation/analytics/reporting boundaries:** placeholder backend boundaries exist, but scoring, analytics workflows, generated reports, and dashboard behavior are not implemented in the current platform.

## Developer Setup

Use Python 3.11 with a local virtual environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Serverless packaging uses Node.js/npm from `infra/`:

```bash
cd infra
npm install
```

## Local Validation Commands

Run Python validation from the repository root:

```bash
python --version
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts/validate_config.py --samples-dir configs/samples
```

## Deployment Process

Deployment is backend-first and stage-aware. Use local package validation before deploying so infrastructure configuration issues are caught without mutating AWS resources. Actual deployment requires configured AWS credentials, sufficient IAM permissions for the platform resources, and should start with `dev` before progressing to `staging` or `prod`.

### Local Package Validation

Run Serverless package validation locally from `infra/` only. These commands package locally and must not deploy or mutate AWS resources:

```bash
cd infra
npx serverless package --stage dev
npx serverless package --stage staging
npx serverless package --stage prod
```

Unsupported stages must fail. The `qa` stage is intentionally not supported:

```bash
npx serverless package --stage qa
# expected: fails because only dev, staging, prod are supported
```

### Actual AWS Deployment

Run deployments from `infra/` only after local package validation succeeds and AWS credentials/IAM permissions are configured:

```bash
cd infra
npx serverless deploy --stage dev
npx serverless deploy --stage staging
npx serverless deploy --stage prod
```

## Supported Stages and Resource Naming

Supported Serverless stages are limited to:

- `dev`
- `staging`
- `prod`

Required stage-aware resource names include:

- `release-confidence-platform-${stage}-raw-results`
- `release-confidence-platform-${stage}-metadata`

Environment variables use uppercase `SNAKE_CASE`, including `STAGE`, `AWS_REGION`, `RAW_RESULTS_BUCKET`, `METADATA_TABLE`, and `LOG_LEVEL`.

## Operational Safety Notes

- Secrets must not be written to logs, scheduler payloads, raw results, lifecycle metadata, or test output.
- Secrets Manager references may be stored and passed by reference only; raw secret values must not be persisted.
- Sanitization is required before persistence and before logging any execution-derived data.
- Production target execution is blocked unless explicitly allowed by validated configuration, and production caps are stricter than non-production caps.
- Scheduler duplicate delivery is handled with `schedule_occurrence_id` idempotency claims before execution.
- The platform remains backend-only: no frontend dashboard, user onboarding, public self-service scheduling UI, scoring workflow, or generated reporting workflow is implemented.

## Mandatory Identifiers

Evidence, metadata, and logs reserve these exact snake_case identifiers:

- `client_id`
- `audit_id`
- `run_id`
- `endpoint_id`
- `scenario_id`
- `raw_result_version`

Scheduled execution events omit caller-supplied `run_id`; each accepted occurrence receives a new execution `run_id` from the backend execution path.
