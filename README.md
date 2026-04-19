# Formica

**Formica** is a stigmergic, ant-colony-inspired multi-agent system for
autonomous problem solving. Agents do not message each other. They
coordinate by reading and writing a shared artifact: a typed task
graph with pheromone-weighted edges, stored in Neo4j.

> "Intelligence is a property of the colony, not the ant."

## What is Formica

- **Forum (blackboard).** Neo4j graph of sub-problems, partial
  solutions, evidence, and validations. This is the only coordination
  channel. No inter-agent HTTP.
- **Pheromones.** Per-edge scalars across six channels (`promising`,
  `validated`, `risky`, `needs-expert`, `dead-end`, `alarm`), each
  with its own evaporation half-life. Agents follow gradients.
- **Castes.** Scouts decompose problems. Foragers produce evidence.
  Validators judge it. A GC caste prunes stale branches. Inquilines
  are narrow specialists (citation checking, numeric sanity).
- **Role reallocation (Gordon's rule).** Agents re-specialize based on
  local encounter rates, so the colony rebalances without a central
  scheduler.
- **Phase cycling.** The colony alternates exploration and
  consolidation phases based on pheromone entropy.
- **Alarm propagation.** Fast, short-lived pheromone that preempts
  work on failure or hallucination.
- **Capacity awareness, never provisioning.** The spawn controller
  observes cluster headroom each tick and schedules within it. It
  never requests new compute. Nodes added at runtime are absorbed
  passively on the next tick.

### Architecture

```mermaid
flowchart LR
    CLI["formica solve<br/>(thin client)"]

    subgraph cluster["Kubernetes cluster (k3d or EKS)"]
        direction TB

        CTRL["Controller<br/>capacity-aware<br/>spawn / retire"]

        subgraph castes["Agent castes (Jobs)"]
            direction TB
            SC["Scout"]
            FO["Forager"]
            VA["Validator"]
            GC["GC"]
            INQ["Inquilines"]
        end

        NEO[("Forum<br/>Neo4j: task graph<br/>+ pheromones")]
        VLLM["vLLM<br/>OpenAI-compatible"]
    end

    subgraph aws["AWS (observability)"]
        direction TB
        CW[("CloudWatch<br/>errors + drivers")]
        S3[("S3 + Athena<br/>OTEL Parquet")]
    end

    CLI -->|write Objective / poll| NEO

    CTRL -->|spawns / retires<br/>within headroom| castes

    castes <-->|read / write| NEO
    castes -->|LLM calls| VLLM

    castes -.->|OTEL| S3
    castes -.->|logs| CW
```

Agents never talk to each other. Every arrow into or out of the
colony goes through the Forum (Neo4j) or the model server. The
controller's only job is to keep the right mix of pods running
within whatever cluster headroom happens to exist.

## Launch

Formica is Kubernetes-native end-to-end. The same manifests work on a
single box (via [k3d](https://k3d.io/)) and on a real EKS cluster.
There is no separate Docker Compose stack and no in-process mode.

### Prerequisites

- Docker, `kubectl`, `kustomize`, and `k3d` on your PATH.
- For local GPU inference: an NVIDIA GPU with drivers and
  `nvidia-container-toolkit` installed, plus Mistral-7B-AWQ weights at
  `/opt/models/mistral-awq` on the host. (Skip this if you override to
  Bedrock or OpenAI via `FORMICA_MODEL_PROVIDER`.)
- For AWS observability: valid AWS credentials in the shell that runs
  `kubectl apply` (IRSA handles pod-level auth once deployed).

### 1. Create a single-node GPU cluster

```bash
k3d cluster create formica \
  --gpus all \
  --volume "/opt/models:/opt/models@all" \
  --port "8080:8080@loadbalancer" \
  --port "7474:7474@loadbalancer" \
  --port "7687:7687@loadbalancer"

kubectl apply -f \
  https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.15.0/deployments/static/nvidia-device-plugin.yml
```

### 2. Deploy Formica

```bash
git clone https://github.com/abacus2000/formica.git && cd formica
kubectl apply -k deploy/k8s/overlays/dev
kubectl -n formica rollout status deploy/vllm --timeout=15m
```

The `vllm` rollout is the slow one (60-120s on the prebaked GPU AMI,
up to 15 minutes if weights are downloaded from HuggingFace). The
controller, Neo4j, and OTEL collector come up in seconds.

### 3. Submit an objective

```bash
pip install -e ".[dev]"

# Port-forward Neo4j and vLLM so the CLI can reach them from outside
# the cluster.
kubectl -n formica port-forward svc/neo4j 7687:7687 &
kubectl -n formica port-forward svc/vllm  8080:8080 &

export FORMICA_NEO4J_URI=bolt://localhost:7687
export FORMICA_MODEL_BASE_URL=http://localhost:8080/v1

formica solve "Prove sqrt(2) is irrational" --budget 1 --timeout 600
```

Validated Evidence streams to stdout as Validator pods emit it.

### Watch the colony

```bash
kubectl -n formica logs -f deploy/formica-controller   # spawn/retire decisions
watch kubectl -n formica get pods                       # live caste mix
open http://localhost:7474                              # Neo4j browser
```

### Multi-node (EKS)

Same manifests, with a prod overlay that swaps the vLLM `hostPath` for
a PVC and sets IRSA annotations:

```bash
kubectl apply -k deploy/k8s/overlays/prod
formica solve "Prove sqrt(2) is irrational with three independent methods" \
  --budget 2 --timeout 600 --env prod --region us-east-1
```

Full walkthrough: [`docs/single-box.md`](docs/single-box.md).

## Observability

- **CloudWatch** (errors + driver logs):
  `/formica/{env}/{region}/errors`, `/formica/{env}/{region}/drivers`
- **S3 + Athena** (OTEL traces / metrics / logs as Parquet):
  `formica-otel-{env}-{region}`

See [`docs/observability.md`](docs/observability.md).

## Credits and inspiration

Formica's design draws on peer-reviewed work in multi-agent systems,
distributed algorithms, and ant colony biology. The annotated reading
list - with notes on which paper shaped which component - lives in
[`docs/references.md`](docs/references.md).

A few load-bearing sources:

- Rodriguez 2026, *Pressure Fields and Temporal Decay* - the core
  coordination model behind Formica's pheromone grid and decay.
- Garg, Shiragur, Gordon, Charikar 2023, *Distributed algorithms from
  arboreal ants* - shortest-path reinforcement on the evidence graph.
- Chandrasekhar, Gordon, Navlakha 2018, *Trail repair* - how the
  colony recovers after a pod is retired or a Validator fails.
- Prabhakar, Dektar, Gordon 2012, *Anternet* - outgoing-rate control
  tuned by return signals; Formica's Controller spawns new Workers by
  the same rule.
- Gordon & Mehdiabadi 1999, *Encounter rate and task allocation* -
  the local-interaction basis for Gordon's rule in the Controller.
- Friedman et al 2021, *Active Inferants* - active-inference framing
  for individual agents inside a stigmergic colony.

## License

[MIT](LICENSE)
