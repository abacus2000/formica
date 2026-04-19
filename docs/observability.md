# Observability

Formica logs are split into two sinks by purpose and environment:

## 1. CloudWatch — error and driver logs

| Log group                               | What lands here                                                                    |
| --------------------------------------- | ---------------------------------------------------------------------------------- |
| `/formica/{env}/{region}/errors`        | `ERROR`/`CRITICAL` from any component, panics, tool failures, validator rejections, alarm pheromone events |
| `/formica/{env}/{region}/drivers`       | Driver-layer logs — Neo4j client, Strands runtime, Kubernetes client, AWS SDK, MCP clients, CUDA / GPU driver messages from GPU pods |

Log stream pattern: `{component}/{pod-name}/{start-timestamp}`.

Routing is done by an `aws-for-fluent-bit` DaemonSet (see `deploy/fluent-bit/`).
A Fluent Bit filter inspects each record:

- Records with `level=ERROR` or `level=CRITICAL` → errors log group.
- Records with `logger` matching `neo4j\.|strands\.|kubernetes\.|botocore\.|boto3\.|aws\.|mcp\.|cuda\.|nvidia\.` → drivers log group.
- A record can land in both (intentional).

Retention: **30 days (dev), 180 days (prod)**. Configurable via Helm values.

An alarm on the 5-minute error rate publishes to SNS topic
`formica-{env}-{region}-alerts`.

## 2. S3 — OpenTelemetry Parquet

Every agent tick, pheromone write, validator verdict, alarm event, and spawn/retire
decision emits a structured OTEL span.

- **Collector**: deployed as a Deployment + Service (see `deploy/otel-collector/`),
  receives OTLP gRPC (4317) and HTTP (4318).
- **Exporter**: `awss3` exporter, Parquet format.
- **Bucket**: `formica-otel-{env}-{region}`
- **Key layout**:
  `year=YYYY/month=MM/day=DD/hour=HH/{signal}/{component}/{trace_id}.parquet`
  where `signal ∈ {traces, metrics, logs}`.
- **Glue table**: defined in `deploy/terraform/glue/` — one external table per signal.
- **Athena**: pre-built queries in `athena/` — `recent_errors.sql`,
  `pheromone_history.sql`, `agent_lifecycle.sql`, `validation_outcomes.sql`.

## Finding the logs for a run

Every `formica solve` invocation creates a `run_id` (UUID) and an OTEL root span whose
`trace_id` is stamped on every child span. To investigate a run:

```bash
# CloudWatch — scope to a run
aws logs filter-log-events \
  --log-group-name /formica/dev/us-east-1/errors \
  --filter-pattern '{ $.run_id = "abcd1234" }'

# Athena — scope to a trace_id
SELECT * FROM formica_otel_dev_us_east_1.traces
WHERE trace_id = 'abcd1234...' ORDER BY start_time_unix_nano;
```

## Alarm pheromone → SNS

Alarm pheromones emitted on the Forum are mirrored to the error log group with
`level=ERROR` and tag `pheromone.alarm=true`, which triggers the metric filter and
the SNS alert. This unifies "the colony is in distress" with "the operator gets paged".

## Local dev

`deploy/otel-collector/config.dev.yaml` uses the `debug` exporter instead of `awss3`,
so no AWS creds are needed for minikube/kind dev loops.
