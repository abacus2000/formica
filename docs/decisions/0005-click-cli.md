# ADR-0005: Click-based CLI

**Status**: Accepted
**Date**: 2026-04-19

## Context

Rome exposes a FastAPI `POST /decree` as the entry point. For a command-line native
workflow (`formica solve ...`) we want a real CLI, not a curl invocation.

## Decision

Use [Click](https://click.palletsprojects.com/) for the CLI. Entry point is
`formica solve "<problem>" --budget <usd> --timeout <s> --env <env> --region <region>`.

The CLI connects to Neo4j (via port-forward or in-cluster DNS) and inserts an `Objective`
node with a starter `promising` pheromone, then streams validated-evidence nodes back to
stdout until a termination condition fires.

## Consequences

- **+** Simple to script and compose.
- **+** Works identically in-cluster (kubectl exec) and out-of-cluster (with a port-forward).
- **−** Needs Neo4j connectivity; no thin HTTP wrapper.
