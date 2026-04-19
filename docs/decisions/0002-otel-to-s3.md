# ADR-0002: OpenTelemetry to S3 Parquet for observability

**Status**: Accepted
**Date**: 2026-04-19

## Context

Rome's Censor is a FastAPI service with a PVC-backed JSONL store. This does not survive
a namespace delete, cannot be queried across runs, and has no trace/metric capability.

## Decision

All Python components emit OTLP (traces, metrics, logs). An in-cluster OpenTelemetry
Collector receives OTLP and exports to S3 in Parquet format via the `awss3` exporter.

- Bucket: `formica-otel-{env}-{region}` (Terraform-managed)
- Key layout: `year=YYYY/month=MM/day=DD/hour=HH/{signal}/{component}/{trace_id}.parquet`
- Glue table + Athena queries provided under `athena/`

## Consequences

- **+** Runs are fully reconstructable from S3 alone.
- **+** Partitioned Parquet → fast Athena scans over months of data.
- **+** Standard tooling (Grafana Tempo/Loki can also point at S3 later).
- **−** Requires IAM with `s3:PutObject` on the bucket, scoped to env+region.
