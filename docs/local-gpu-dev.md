# Local GPU testing (single EC2 box)

The fastest way to smoke-test Formica end-to-end is on a single GPU EC2
instance launched from the prebaked open-weight AMI (shared with the
`rome` project). No Kubernetes, no cluster.

## What's on the AMI

The prebaked AMI (`ami-079c82d610e02e480`, baked 2026-04-18) contains:

- AL2023 base with NVIDIA drivers, CUDA, and Docker pre-installed.
- `vllm/vllm-openai` image pulled into the local Docker cache.
- **Mistral-7B-Instruct-v0.2-AWQ** weights on disk at `/opt/models/mistral-awq`
  (~4.5 GB, AWQ 4-bit quantized; fits the T4's 16 GB VRAM comfortably).

Formica's CLI and agents default to this model. You do not have to set
any env vars for the happy path.

## Launch + SSH

Launch any GPU instance from the prebaked AMI. `g4dn.xlarge` is the
cheapest box that fits the model comfortably (1× T4, ~$0.53/hr).

```bash
ssh -i <your-key.pem> ec2-user@<instance-public-ip>
```

Verify the GPU is visible:

```bash
nvidia-smi
ls /opt/models/mistral-awq   # should not be empty
```

## Bring up the stack

```bash
git clone https://github.com/abacus2000/formica.git
cd formica

# Bring up Neo4j + vLLM (both backgrounded).
docker compose -f deploy/compose/docker-compose.yml up -d

# vLLM is ready when /v1/models responds. On the prebaked AMI this
# takes ~60–120s; on a stock DLAMI (downloading from HuggingFace)
# expect 8–15 minutes.
until curl -sf http://localhost:8080/v1/models > /dev/null; do
  echo "waiting for vllm..."; sleep 10
done
echo "vllm ready"
```

Install the CLI:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Solve something

```bash
formica solve "Prove sqrt(2) is irrational." \
  --local \
  --budget 1 --timeout 600 \
  --env dev --region us-east-1
```

The `--local` flag runs Scout → Forager → Validator → GC in-process
against the real Neo4j. Validated evidence streams to stdout as JSON.

## Inspect the blackboard

Neo4j Browser is exposed on port `7474`:

```
http://<instance-public-ip>:7474
```

(default creds `neo4j / changeme` unless you overrode them in `.env`)

Useful queries:

```cypher
// All subproblems for the most recent objective
MATCH (o:Objective)<-[:CHILD_OF*1..6]-(sp:SubProblem)
WITH o ORDER BY o.created_at DESC LIMIT 1
MATCH (o)<-[:CHILD_OF*1..6]-(sp:SubProblem)
RETURN sp.id, sp.text;

// Pheromone levels on every active edge
MATCH ()-[r]->() WHERE r.pheromones IS NOT NULL
RETURN type(r), r.pheromones;
```

## Overriding the model

To point at a different vLLM / OpenAI-compatible endpoint (or to swap
the model id), set env vars before launching the CLI:

```bash
export FORMICA_MODEL_BASE_URL=http://my-vllm:8000/v1
export FORMICA_MODEL_ID=meta-llama/Llama-3.1-8B-Instruct
formica solve "..." --local
```

To use Bedrock instead:

```bash
export FORMICA_MODEL_PROVIDER=bedrock
export FORMICA_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
formica solve "..." --local
```

## Tearing down

```bash
docker compose -f deploy/compose/docker-compose.yml down -v
```

The `-v` flag also deletes the Neo4j volume, so the Forum starts fresh
next time.
