# Formica

**Formica** is a stigmergic, ant-colony-inspired multi-agent system for autonomous problem solving.
It is the spiritual successor to [`abacus2000/rome`](https://github.com/abacus2000/rome): same stack
(Kubernetes, Strands Agents, Neo4j, AWS), but the coordination model is replaced with stigmergy — agents
coordinate by reading and writing a shared artifact (a typed task graph with pheromone-weighted edges),
not by messaging each other.

> "Intelligence is a property of the colony, not the ant."

## What's different from Rome

| Rome                                   | Formica                                               |
| -------------------------------------- | ----------------------------------------------------- |
| Princeps decides deployment (hierarchy) | No dispatcher. Workers follow pheromone gradients.    |
| Legion / Civitas (direct / deliberative) | Single worker pool with role reallocation (Gordon).  |
| Censor as metrics sink                  | Validator caste emits `validated` pheromone.          |
| Inter-service HTTP messaging            | All coordination via the **Forum** (Neo4j blackboard).|
| Kaizen agents propose changes          | Phase cycling + `anternet`-style spawn feedback.      |
| Capacity provisioning                  | **Never provisions**. Capacity-aware, passive growth. |

See [`docs/port-notes.md`](docs/port-notes.md) for the full mapping.

## Core ideas

- **Forum (blackboard)** — Neo4j graph of sub-problems, partial solutions, evidence, validations.
- **Pheromones** — per-edge scalars across six channels (`promising`, `validated`, `risky`,
  `needs-expert`, `dead-end`, `alarm`), each with its own evaporation half-life.
- **Castes** — Scouts, Foragers, Validators (Censors), GC (Lustrum), and narrow Inquilines.
- **Role reallocation (Gordon's rule)** — agents re-specialize based on local encounter rates.
- **Phase cycling** — colony alternates exploration and consolidation based on pheromone entropy.
- **Necrophoresis** — a GC caste prunes stale / decayed branches.
- **Alarm propagation** — fast, short-lived pheromone that preempts work on failure / hallucination.
- **Capacity awareness** — spawn controller observes cluster headroom; never requests new compute;
  passively absorbs nodes added at runtime.

## Quick start (single GPU box)

Formica ships configured for the open-weight GPU AMI shared with `rome`
(`ami-079c82d610e02e480`: AL2023 + NVIDIA drivers + CUDA + Docker +
Mistral-7B-Instruct-v0.2-AWQ weights at `/opt/models/mistral-awq`).

```bash
ssh ec2-user@<instance>
git clone https://github.com/abacus2000/formica.git && cd formica
docker compose -f deploy/compose/docker-compose.yml up -d   # neo4j + vllm
pip install -e ".[dev]"
formica solve "Prove sqrt(2) is irrational" --local --budget 1 --timeout 600
```

Full walk-through: [`docs/local-gpu-dev.md`](docs/local-gpu-dev.md).

## Quick start (Kubernetes)

```bash
kubectl apply -k deploy/k8s/overlays/dev
formica solve "Prove sqrt(2) is irrational with three independent methods" \
  --budget 2 --timeout 600 --env dev --region us-east-1
```

## Observability

- **CloudWatch** (errors + driver logs): `/formica/{env}/{region}/errors`, `/formica/{env}/{region}/drivers`
- **S3 + Athena** (OTEL traces/metrics/logs as Parquet): `formica-otel-{env}-{region}`

See [`docs/observability.md`](docs/observability.md).

## Roman aliases

Formica's canonical vocabulary is ant-colony. Roman terms are available as readability aliases:

| Formica (canonical) | Rome alias |
| ------------------- | ---------- |
| agent pod           | Castra     |
| trail               | Via        |
| validator           | Censor     |
| GC pass             | Lustrum    |
| blackboard          | Forum      |

## License

[MIT](LICENSE)
