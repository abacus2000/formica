# Single-box Formica (bare k3s on a GPU host)

Formica runs the same Kubernetes manifests whether you have one node or
fifty. For single-box development, we run [k3s](https://k3s.io/) directly
on the host as a systemd service, so you exercise the real controller /
Job / Service / RBAC path on your laptop or on a single GPU EC2 box.

k3s is bundled with containerd. There is no Docker layer, no k3d wrapper,
and no in-process `--local` mode. One node is first-class.

## What you need

Any Linux box that has:

1. An NVIDIA GPU with drivers installed and `/usr/bin/nvidia-container-runtime`
   on the PATH (install `nvidia-container-toolkit`). If you do not have a
   GPU, set `FORMICA_MODEL_PROVIDER=bedrock` and skip the GPU bits.
2. `curl`, `systemd`, and root access to install k3s.
3. Mistral-7B-AWQ weights at `/opt/models/mistral-awq` on the host. The
   vLLM pod mounts this via a `hostPath` volume.

The canonical environment is a `g5.xlarge` (or `g4dn.xlarge`) launched
from the prebaked open-weight AMI (`ami-079c82d610e02e480`) shared with
the [rome](https://github.com/abacus2000/rome) project. That AMI already
has everything in items 1–3.

For a step-by-step EC2 walkthrough, see [launch-on-aws.md](./launch-on-aws.md).

## Bring up the cluster

```bash
# 1. Install k3s as a systemd service. k3s v1.34+ auto-detects
#    nvidia-container-runtime on the host and registers it with containerd,
#    so you do NOT need a custom /var/lib/rancher/k3s/agent/etc/containerd
#    config template. Adding one will cause a 'toml: table nvidia already
#    exists' error on startup.
curl -sfL https://get.k3s.io | \
  INSTALL_K3S_EXEC="--disable=traefik --write-kubeconfig-mode=644" sh -

# 2. Wait for the node to go Ready.
sudo k3s kubectl wait --for=condition=Ready node --all --timeout=120s

# 3. Register the nvidia RuntimeClass so pods can opt into the nvidia runtime.
cat <<'YAML' | sudo k3s kubectl apply -f -
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: nvidia
handler: nvidia
YAML

# 4. Install the NVIDIA device plugin so pods can request nvidia.com/gpu.
#    The daemonset MUST run under runtimeClassName: nvidia; otherwise it
#    cannot see /dev/nvidia* and will never mark the GPU allocatable.
sudo k3s kubectl apply -f \
  https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.17.0/deployments/static/nvidia-device-plugin.yml

sudo k3s kubectl -n kube-system patch daemonset nvidia-device-plugin-daemonset \
  --type=json \
  -p '[{"op":"add","path":"/spec/template/spec/runtimeClassName","value":"nvidia"}]'

# 5. Confirm the GPU is allocatable. This should print "1".
sudo k3s kubectl get node -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}'
echo

# 6. Deploy Formica.
sudo k3s kubectl apply -k deploy/k8s/overlays/dev

# 7. Wait for vLLM to come up. The vllm/vllm-openai:latest image is ~10GB;
#    first pull is 3-5 minutes on a typical EC2 link. Model load is
#    another 60-120s with pre-baked AWQ weights.
sudo k3s kubectl -n formica rollout status deploy/vllm --timeout=20m
```

### Building the controller image

The `formica-controller` Deployment and the two `formica-*-evaporation`
CronJobs reference `image: formica:latest` with
`imagePullPolicy: IfNotPresent`. The image is not published to any
registry; you build it locally and the tag lives in k3s's containerd
image store.

Install [BuildKit](https://github.com/moby/buildkit) and build against
the k3s containerd socket so the resulting image is immediately visible
to kubelet:

```bash
BK_VERSION=v0.18.1
curl -fsSL "https://github.com/moby/buildkit/releases/download/${BK_VERSION}/buildkit-${BK_VERSION}.linux-amd64.tar.gz" \
  | sudo tar -C /usr/local -xzf -

# Run buildkitd with the containerd worker pointed at k3s's socket.
sudo nohup buildkitd \
  --oci-worker=false \
  --containerd-worker=true \
  --containerd-worker-addr=/run/k3s/containerd/containerd.sock \
  --containerd-worker-namespace=k8s.io \
  >/var/log/buildkitd.log 2>&1 &

# Build. The image lands directly in the k3s image store.
cd ~/formica
sudo buildctl build \
  --frontend dockerfile.v0 \
  --local context=. \
  --local dockerfile=. \
  --output type=image,name=docker.io/library/formica:latest

# Verify.
sudo k3s ctr -n k8s.io images ls -q | grep formica
```

No registry, no push, no Docker daemon.

## Submit an objective

From outside the cluster (e.g. the EC2 instance's shell):

```bash
pip install -e ".[dev]"

# The CLI is a thin client: it writes to Neo4j and polls. The colony
# lives in the cluster. Port-forward Neo4j and vLLM so local env vars
# Just Work.
sudo k3s kubectl -n formica port-forward svc/neo4j 7687:7687 &
sudo k3s kubectl -n formica port-forward svc/vllm  8080:8080 &

export FORMICA_NEO4J_URI=bolt://localhost:7687
export FORMICA_MODEL_BASE_URL=http://localhost:8080/v1

formica solve "Prove sqrt(2) is irrational" --budget 1 --timeout 600
```

You should see validated Evidence stream to stdout as Validator pods
emit it.

## Watch the colony work

```bash
# Controller decisions (spawn/retire/phase transitions).
sudo k3s kubectl -n formica logs -f deploy/formica-controller

# Live pod list: scouts, foragers, validators, gc appear and disappear
# as the controller reallocates roles.
watch sudo k3s kubectl -n formica get pods

# Neo4j browser (pheromones, subproblem graph).
# neo4j / changeme - override via deploy/k8s/base/neo4j.yaml for prod.
open http://localhost:7474
```

## Tearing down

```bash
sudo /usr/local/bin/k3s-uninstall.sh
```

This stops the service, removes containerd state, and wipes every Pod
and Volume on the node. Weights under `/opt/models` are preserved (they
live on the host, not in the cluster).

## From bare k3s to EKS

The exact same manifests work on a real multi-node EKS cluster; that's
the whole point. You only need to swap two things:

1. **vLLM weights.** The `vllm.yaml` base manifest uses a `hostPath`
   mount, which only works when every node has `/opt/models` populated.
   For EKS, patch it to a PVC (EFS, or an initContainer rsync from S3)
   in a prod overlay.
2. **IRSA.** Set `otel.serviceAccountAnnotations` and
   `fluentBit.serviceAccountAnnotations` to the IAM role ARNs that
   Terraform created (`deploy/terraform/iam.tf`).

Nothing in the application code changes.
