# ADR-0003: Fluent Bit for CloudWatch error and driver logs

**Status**: Accepted
**Date**: 2026-04-19

## Context

OTEL carries structured signals. Operators still need low-latency, grep-able access
to raw pod stdout/stderr — especially for driver-layer noise (Neo4j client, Strands
runtime, Kubernetes client, AWS SDK, CUDA driver messages from GPU pods).

## Decision

Deploy `aws-for-fluent-bit` as a DaemonSet. Configure a routing filter that classifies
records by severity and component and writes to one of two log groups per env+region:

- `/formica/{env}/{region}/errors` — `ERROR` / `CRITICAL` from any component.
- `/formica/{env}/{region}/drivers` — all records from driver-layer components.

Log stream pattern: `{component}/{pod-name}/{start-timestamp}`. Retention is 30 days
(dev) / 180 days (prod). A CloudWatch metric-filter alarm on error rate publishes to
an SNS topic `formica-{env}-{region}-alerts`.

## Consequences

- **+** Two narrow, predictable log groups per environment instead of one firehose.
- **+** SNS alerts are easy to subscribe to (email/Slack).
- **−** A small amount of duplication with OTEL logs (intentional — different consumers).
