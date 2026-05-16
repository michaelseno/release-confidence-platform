# Release Confidence Platform

Release Confidence Platform is an operational API reliability audit platform focused on release confidence, deterministic evidence collection, evidence-first architecture, and trustworthy operational findings.

Phase 0 establishes the project foundation only: repository structure, Python tooling, documentation standards, sample configuration, local tests, and Serverless Framework package validation. It does not execute audits, deploy cloud resources, provide a dashboard, implement authentication, or generate findings.

## Philosophy

- **Operational reliability focus:** future features should help teams understand release risk from observable API behavior.
- **Release confidence over hype:** the platform is intended to support cautious, evidence-backed release decisions.
- **Deterministic analytics:** later analytics should be reproducible from versioned raw evidence, not opaque or self-healing behavior.
- **Evidence-first architecture:** raw results are the future source of truth; derived findings must remain traceable.
- **AWS-native event-driven direction:** infrastructure is organized for Serverless Framework and AWS resources, while Phase 0 validation remains local packaging only.

## Phase 0 Scope

In scope:

- Monorepo structure for backend, frontend placeholder, shared packages, infrastructure, configs, scripts, tests, and docs.
- Python 3.11 dependency and tooling configuration in `pyproject.toml`.
- Required Python dependencies/tools: `pytest`, `ruff`, `boto3`, and `requests`.
- Serverless Framework YAML under `infra/` with `dev`, `staging`, and `prod` stage support.
- Local validation commands for linting, formatting, tests, sample config validation, and Serverless packaging.
- Documentation for architecture, lifecycle, raw evidence, operational philosophy, coding standards, logging, naming, schema versioning, and folder ownership.

Out of scope:

- Runtime audit orchestration, runner behavior, scheduler runtime logic, raw evidence persistence, analytics, reporting, frontend/dashboard implementation, auth/RBAC/billing, AI insights, advanced observability, load testing, chaos engineering, heavy frameworks, and real AWS deployment.

## Local Setup

Use Python 3.11 with `venv`:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Serverless packaging uses Node.js/npm. From `infra/`, install the pinned Serverless Framework major version if needed:

```bash
npm install
```

## Validation Commands

Run from the repository root unless noted:

```bash
python --version
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts/validate_config.py --samples-dir configs/samples
```

Package validation is local-only and must not deploy or mutate AWS resources:

```bash
cd infra
npx serverless package --stage dev
```

Optional package checks for stage resolution:

```bash
cd infra
npx serverless package --stage staging
npx serverless package --stage prod
```

## Stage and Resource Naming

Supported stages are selected with `--stage` and limited to:

- `dev`
- `staging`
- `prod`

Required stage-aware resource names:

- `release-confidence-platform-${stage}-raw-results`
- `release-confidence-platform-${stage}-metadata`

Environment variables use uppercase `SNAKE_CASE`, including `STAGE`, `AWS_REGION`, `RAW_RESULTS_BUCKET`, `METADATA_TABLE`, and `LOG_LEVEL`.

## Mandatory Identifiers

Future evidence, metadata, and logs reserve these exact snake_case identifiers:

- `client_id`
- `audit_id`
- `run_id`
- `endpoint_id`
- `scenario_id`
- `raw_result_version`

## Frontend Boundary

`apps/frontend/README.md` is the only frontend Phase 0 artifact. No frontend framework, route, dashboard, package manager setup, component library, or build pipeline is implemented.
