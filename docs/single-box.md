# Single-box Formica (k3d on a GPU EC2 instance)

Formica runs the same Kubernetes manifests whether you have one node or
fifty. For single-box development, we use [k3d](https://k3d.io/) — a
lightweight k3s cluster that runs inside Docker on a single host — so
you exercise the real controller / Job / Service / RBAC path on your
laptop or on a single GPU EC2 box.

> This is the **first-class** single-box workflow. There is no separate
> Docker Compose stack and no in-process `--local` mode.

## What you need

Any Linux box that has:

1. Docker (for k3d).
2. An NVIDIA GPU + drivers + `nvidia-container-toolkit` (if you want
   vLLM on-cluster; otherwise set `FORMICA_MODEL_PROVIDER=bedrock` and
   skip the GPU bits).
3. `kubectl`, `kustomize`, and `k3d` on your PATH.
4. Mistral-7B-AWQ weights at `/opt/models/mistral-awq` on the host (the
   k3d cluster mounts this into the vLLM pod; see below).

The canonical environment is a `g4dn.xlarge` launched from the prebaked
open-weight AMI (`ami-079c82d610e02e480`) shared with the
[rome](https://github.com/abacus2000/rome) project. That AMI already
has everything in items 1–4.

## Bring up the cluster

```bash
# 1. Create a GPU-enabled k3d cluster.
#    --gpus all  forwards the host's GPUs into the k3s node container.
#    --volume    bind-mounts the weights directory so the vllm pod can
#                hostPath-mount /opt/models.
k3d cluster create formica \
  --gpus all \
  --volume "/opt/models:/opt/models@all" \
  --port "8080:8080@loadbalancer" \
  --port "7474:7474@loadbalancer" \
  --port "7687:7687@loadbalancer"

# 2. Install the NVIDIA device plugin inside the cluster so pods can
#    request nvidia.com/gpu. (Skip if you use the NVIDIA GPU Operator.)
kubectl apply -f \
  https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.15.0/deployments/static/nvidia-device-plugin.yml

# 3. Deploy Formica.
kubectl apply -k deploy/k8s/overlays/dev

# 4. Wait for vLLM to come up (60–120s on the prebaked AMI).
kubectl -n formica rollout status deploy/vllm --timeout=15m
```

## Submit an objective

From outside the cluster (e.g. the EC2 instance's shell):

```bash
pip install -e ".[dev]"

# The CLI is a thin client — it writes to Neo4j and polls. The colony
# lives in the cluster. Port-forward Neo4j and vLLM so local env vars
# Just Work.
kubectl -n formica port-forward svc/neo4j 7687:7687 &
kubectl -n formica port-forward svc/vllm  8080:8080 &

export FORMICA_NEO4J_URI=bolt://localhost:7687
export FORMICA_MODEL_BASE_URL=http://localhost:8080/v1

formica solve "Prove sqrt(2) is irrational" --budget 1 --timeout 600
```

You should see validated Evidence stream to stdout as Validator pods
emit it.

## Watch the colony work

```bash
# Controller decisions (spawn/retire/phase transitions).
kubectl -n formica logs -f deploy/formica-controller

# Live pod list — scouts, foragers, validators, gc appear and disappear
# as the controller reallocates roles.
watch kubectl -n formica get pods

# Neo4j browser (pheromones, subproblem graph).
# neo4j / changeme  — override via deploy/k8s/base/neo4j.yaml for prod.
open http://localhost:7474
```

## Tearing down

```bash
k3d cluster delete formica
```

Neo4j's PVC is backed by the k3d node's local storage and is deleted
with the cluster, so this is a clean reset.

## From k3d to EKS

The exact same manifests work on a real multi-node EKS cluster — that's
the whole point. You only need to swap two things:

1. **vLLM weights.** The `vllm.yaml` base manifest uses a `hostPath`
   mount, which only works when every node has `/opt/models` populated.
   For EKS, patch it to a PVC (EFS, or an initContainer rsync from S3)
   in a prod overlay.
2. **IRSA.** Set `otel.serviceAccountAnnotations` and
   `fluentBit.serviceAccountAnnotations` to the IAM role ARNs that
   Terraform created (`deploy/terraform/iam.tf`).

Nothing in the application code changes.
