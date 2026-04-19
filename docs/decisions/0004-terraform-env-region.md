# ADR-0004: Terraform-managed AWS resources scoped by env + region

**Status**: Accepted
**Date**: 2026-04-19

## Context

Multiple Formica deployments (dev/prod × multiple regions) must coexist without
cross-contamination of logs, traces, or IAM.

## Decision

All AWS resources are provisioned by Terraform under `deploy/terraform/`, with naming
and IAM scoping keyed to `{env}` and `{region}`:

- S3 bucket: `formica-otel-{env}-{region}`
- Glue database: `formica_otel_{env}_{region}`
- CloudWatch log groups: `/formica/{env}/{region}/errors`, `/formica/{env}/{region}/drivers`
- SNS topic: `formica-{env}-{region}-alerts`
- IAM roles: `formica-agent-{env}-{region}`, `formica-controller-{env}-{region}`,
  `formica-otel-{env}-{region}`, `formica-fluentbit-{env}-{region}`

IAM policies use resource ARNs scoped to the env+region naming pattern only - no `*` resource wildcards.

## Consequences

- **+** Any blast radius is contained to one env+region.
- **+** Multi-region active/active is achievable without rename.
- **−** Terraform workspace discipline required (one state per env+region).
