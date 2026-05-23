# GitHub Issue

GitHub Issue: #15
GitHub Issue URL: https://github.com/michaelseno/release-confidence-platform/issues/15

## 1. Feature Name

Backend Serverless Deploy Config

## 2. Problem Summary

Backend Serverless deployment configuration needed correction after PR 14 so all backend runtime handlers deploy correctly, Scheduler/IAM/stage environment resources are configured, backend packages are isolated from unrelated mock API content, the HITL `AWS_REGION` Lambda environment blocker is resolved, and the duplicate `config/stages 2` path is removed without affecting real stage configs.

## 3. Linked Planning Documents

- Bug Report: `docs/bugs/backend_serverless_deploy_config_bug_report.md`
- HITL Blocker Bug Report: `docs/bugs/backend_lambda_reserved_aws_region_bug_report.md`
- Implementation Plan: `docs/backend/backend_serverless_deploy_config_implementation_plan.md`
- Implementation Report: `docs/backend/backend_serverless_deploy_config_implementation_report.md`
- HITL Blocker Implementation Plan: `docs/backend/backend_lambda_reserved_aws_region_implementation_plan.md`
- HITL Blocker Implementation Report: `docs/backend/backend_lambda_reserved_aws_region_implementation_report.md`
- Deployment Docs: `docs/backend/backend_deployment.md`
- QA Test Plan: `docs/qa/backend_serverless_deploy_config_test_plan.md`
- QA Report: `docs/qa/backend_serverless_deploy_config_test_report.md`

## 4. Scope Summary

- Configure all backend handlers in `infra/serverless.yml`.
- Configure Scheduler resources, Lambda invocation role, IAM permissions, and stage-specific environment/resource settings.
- Preserve deployment scripts and stage config loading.
- Isolate backend Serverless package contents from mock target API artifacts and generated/cache files.
- Remove the reserved `AWS_REGION` user-defined Lambda environment variable that blocked HITL deployment.
- Remove duplicate `config/stages 2` artifacts while preserving real `config/stages/` configs.

## 5. QA Section

- QA approved with exact sign-off phrase: `[QA SIGN-OFF APPROVED]`.
- Full regression suite passed: `100 passed`.
- Infra regression suite passed.
- Serverless print/package validation passed for dev, staging, and prod.
- User deployment validation completed successfully.
- HITL validation successful.

## 6. Risks / Open Questions

- Serverless emitted a non-blocking Node `DEP0040` `punycode` deprecation warning during local validation.
- Live production deployment is outside this PR; validation included local package/print checks and user-reported successful deployment validation.

## 7. Definition of Done

- Backend deployment config deploys all current backend handlers.
- Scheduler, IAM, stage/env, package isolation, and documentation updates are complete.
- Reserved Lambda `AWS_REGION` blocker is resolved.
- Duplicate `config/stages 2` cleanup is complete.
- QA and HITL gates are satisfied before push and PR creation.
