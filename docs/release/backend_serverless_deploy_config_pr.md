# Pull Request

## 1. Feature Name

Backend Serverless Deploy Config

## 2. Summary

Fixes backend Serverless deployment configuration so the backend service can deploy all runtime handlers with required Scheduler/IAM/stage environment wiring, isolated package contents, and the HITL `AWS_REGION` deployment blocker resolved. Also records cleanup of the duplicate `config/stages 2` path after successful user deployment validation.

## 3. Related Documents

- Product Spec: docs/product/phase_1_core_engine_foundation_spec.md
- Technical Design: docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md
- UI/UX Spec: docs/uiux/phase_3_audit_scheduling_lifecycle_design_spec.md
- Bug Report: docs/bugs/backend_serverless_deploy_config_bug_report.md
- HITL Blocker Bug Report: docs/bugs/backend_lambda_reserved_aws_region_bug_report.md
- Implementation Report: docs/backend/backend_serverless_deploy_config_implementation_report.md
- HITL Blocker Implementation Report: docs/backend/backend_lambda_reserved_aws_region_implementation_report.md
- Deployment Docs: docs/backend/backend_deployment.md
- QA Report: docs/qa/backend_serverless_deploy_config_test_report.md
- Release Issue: docs/release/backend_serverless_deploy_config_issue.md

## 4. Changes Included

- Updates backend Serverless deployment config for all backend handlers: orchestrator, scheduled execution, and audit finalization.
- Adds/updates Scheduler resources, Lambda invocation role, IAM permissions, DynamoDB/S3 resource wiring, stage configuration, and Lambda environment configuration.
- Removes user-defined reserved `AWS_REGION` from Lambda environment configuration to unblock HITL deployment.
- Improves backend package isolation so mock target API content and generated/cache artifacts are excluded from backend packages.
- Preserves deployment scripts and documents backend deployment usage.
- Cleans up duplicate `config/stages 2` artifacts while preserving real `config/stages/` configs.
- Adds bug, implementation, QA, and release traceability artifacts.

## 5. QA Status

- Approved: YES
- QA sign-off phrase confirmed in `docs/qa/backend_serverless_deploy_config_test_report.md`: `[QA SIGN-OFF APPROVED]`
- HITL validation phrase provided by requester: `HITL validation successful`
- User deployment validation reported successful.

## 6. Test Coverage

- `npx serverless print --stage dev/staging/prod` passed.
- `npx serverless package --stage dev/staging/prod` passed.
- Generated CloudFormation/package inspection confirmed all three Lambda handlers, no user-defined `AWS_REGION`, no API Gateway resources, required IAM/Scheduler resources, and backend package isolation.
- `python3.11 -m pytest tests/unit/test_infra_configuration.py` passed.
- `python3.11 -m pytest tests` passed: 100 passed.
- Final cleanup validation confirmed `config/stages 2` absent, `config/stages/` intact, no stale references, and backend dev package still succeeds.

## 7. Risks / Notes

- Serverless emitted a non-blocking Node `DEP0040` `punycode` deprecation warning during local validation.
- Production deployment is not performed by this PR; validation includes local package/print checks plus successful user deployment/HITL validation.
- Backend remains event-driven; no backend API Gateway resources were introduced.

## 8. Linked Issue

- Closes #15
