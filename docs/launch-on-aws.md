# Launch Formica on a single EC2 GPU box

This is the exact recipe that brings up a working Formica cluster on AWS
from scratch. It uses the prebaked open-weight AMI from the
[rome](https://github.com/abacus2000/rome) project, which ships with
CUDA 13, NVIDIA drivers, `nvidia-container-toolkit`, `nerdctl`, and the
Mistral-7B-Instruct-v0.2-AWQ weights already staged at
`/opt/models/mistral-awq`.

If you are on a different AMI, first install drivers and
`nvidia-container-toolkit` per the
[NVIDIA docs](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
and stage weights yourself. Everything else below is identical.

## TL;DR

```bash
aws ssm start-session --target i-XXXXXXXXXXXXXXXXX --region us-east-1
sudo su - ec2-user
git clone https://github.com/abacus2000/formica.git ~/formica
cd ~/formica
bash scripts/launch-single-box.sh
```

The script takes ~10 minutes on a fresh instance (most of that is
pulling the 10 GB vLLM image). It is idempotent; if it fails partway,
re-run it.

## 1. Launch the instance

| Setting             | Value                                                   |
| ------------------- | ------------------------------------------------------- |
| Instance type       | `g5.xlarge` (A10G, 24 GB GPU memory, 4 vCPU, 16 GB RAM) |
| AMI                 | `ami-079c82d610e02e480` (shared from rome)              |
| Root volume         | **200 GB gp3** (non-negotiable, see below)              |
| IAM instance profile| role with `AmazonSSMManagedInstanceCore` attached       |
| Security group      | egress any (pulls from Docker Hub, nvcr.io, GitHub)     |

**Why 200 GB.** k3s's containerd store unpacks the `vllm/vllm-openai`
image to ~30 GB by itself. Add the formica build cache, kubelet
ephemeral storage, the OS, and logs, and anything under 150 GB triggers
kubelet DiskPressure eviction during the first pull. 100 GB does not
work. The launcher script refuses to continue with less than 120 GB
free.

You do not need to open inbound ports. All access is via SSM Session
Manager or `kubectl port-forward` tunneled over SSM.

## 2. Connect and clone

```bash
aws ssm start-session --target i-XXXXXXXXXXXXXXXXX --region us-east-1
sudo su - ec2-user

git clone https://github.com/abacus2000/formica.git ~/formica
cd ~/formica
```

## 3. Run the launcher

```bash
bash scripts/launch-single-box.sh
```

What it does, in order:

1. Sanity-checks the GPU and root disk.
2. Installs k3s v1.34 with Traefik disabled and a readable kubeconfig,
   then wires `~/.kube/config` for `ec2-user`.
3. Registers the `nvidia` RuntimeClass, installs the NVIDIA device
   plugin v0.17.0, and pins the plugin daemonset to the nvidia runtime
   so it can see `/dev/nvidia*`.
4. Installs BuildKit v0.18.1 and builds `formica:latest` directly into
   k3s's containerd image store (no registry push, no Docker).
5. Applies `deploy/k8s/overlays/dev`, which includes the dev
   otel-collector ConfigMap (debug exporter, not the production
   parquet exporter).
6. Waits for Neo4j, controller, otel, and vLLM to roll out.
7. Runs a final `kubectl exec -n formica deploy/formica-controller -- formica --help`
   smoke test against the controller pod.

Set `SKIP_SMOKE=1` to stop after step 6. Other knobs
(`K3S_VERSION`, `BUILDKIT_VERSION`, `DEVICE_PLUGIN_VER`) are documented
at the top of the script.

## Expected steady state

```
NAME                                  READY   STATUS    RESTARTS   AGE
aws-for-fluent-bit-xxxxx              1/1     Running   0          2m
formica-controller-xxxxxxxxxx-xxxxx   1/1     Running   0          1m
neo4j-0                               1/1     Running   0          2m
otel-collector-xxxxxxxxxx-xxxxx       1/1     Running   0          1m
vllm-xxxxxxxxxx-xxxxx                 1/1     Running   0          8m
```

Agent pods (`scout-*`, `forager-*`, `validator-*`) come and go as the
controller allocates roles. That is correct: Formica treats agents as
ephemeral Jobs, not long-lived Deployments.

## Running more solves

Run solves inside the controller pod with `kubectl exec`. The controller
image already has Python 3.12 and the `formica` CLI installed, and the
pod is wired to Neo4j and vLLM via in-cluster Services, so no
port-forwards or host-side installs are needed:

```bash
kubectl exec -n formica deploy/formica-controller -- \
  formica solve "Prove sqrt(2) is irrational" --budget 1 --timeout 600 --stream
```

**Why not `pip install -e .` on the host?** Amazon Linux 2023 ships
Python 3.9, but `strands-agents-tools>=0.1.0` (a transitive dependency)
requires Python `>=3.10`. A host-side editable install fails at
resolution. Rather than install a second Python toolchain on the host,
the canonical single-box smoke test goes through `kubectl exec` into
the controller pod, which already has a working environment.

## Neo4j credentials

The Neo4j container reads its password from the `neo4j-auth` Secret in
the `formica` namespace (key `NEO4J_PASSWORD`). The default shipped in
`deploy/k8s/base/neo4j.yaml` is `changeme`, which is fine for a
single-box dev instance behind SSM with no inbound ports but is not
appropriate for anything shared.

To override, add a kustomize patch in your own overlay:

```yaml
# deploy/k8s/overlays/mydev/neo4j-auth.yaml
apiVersion: v1
kind: Secret
metadata:
  name: neo4j-auth
  namespace: formica
stringData:
  NEO4J_PASSWORD: "your-strong-password"
```

and reference it from the overlay's `kustomization.yaml`:

```yaml
resources:
  - ../../base
patches:
  - path: neo4j-auth.yaml
```

The controller reads the same Secret via its Deployment env, so
rotating the Secret and restarting both `neo4j-0` and
`deploy/formica-controller` is sufficient.

## What the script is doing, manually

If you need to diagnose a failure or integrate this into another tool,
here are the same operations broken out step by step.

### k3s

```bash
curl -sfL https://get.k3s.io | \
  INSTALL_K3S_EXEC="--disable=traefik --write-kubeconfig-mode=644" sh -

mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config

kubectl wait --for=condition=Ready node --all --timeout=120s
```

**Gotcha.** Do not drop a `config.toml.tmpl` under
`/var/lib/rancher/k3s/agent/etc/containerd/`. k3s v1.34+ auto-detects
`nvidia-container-runtime` in `$PATH` and registers it. A custom
template causes containerd to fail with
`toml: table nvidia already exists` and the node never becomes Ready.

### GPU

```bash
# RuntimeClass
cat <<'YAML' | kubectl apply -f -
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: nvidia
handler: nvidia
YAML

# Device plugin
kubectl apply -f \
  https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.17.0/deployments/static/nvidia-device-plugin.yml

# Pin to nvidia runtime so the plugin can see /dev/nvidia*
kubectl -n kube-system patch daemonset nvidia-device-plugin-daemonset \
  --type=json \
  -p '[{"op":"add","path":"/spec/template/spec/runtimeClassName","value":"nvidia"}]'

# Verify: expect "1"
kubectl get node -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}'
```

### Image

```bash
BK_VERSION=v0.18.1
curl -fsSL "https://github.com/moby/buildkit/releases/download/${BK_VERSION}/buildkit-${BK_VERSION}.linux-amd64.tar.gz" \
  | sudo tar -C /usr/local -xzf -

sudo nohup buildkitd \
  --oci-worker=false \
  --containerd-worker=true \
  --containerd-worker-addr=/run/k3s/containerd/containerd.sock \
  --containerd-worker-namespace=k8s.io \
  >/var/log/buildkitd.log 2>&1 &

cd ~/formica
sudo buildctl build \
  --frontend dockerfile.v0 \
  --local context=. \
  --local dockerfile=. \
  --output type=image,name=docker.io/library/formica:latest

sudo k3s ctr -n k8s.io images ls -q | grep formica
```

### Deploy and solve

```bash
kubectl apply -k deploy/k8s/overlays/dev
kubectl -n formica rollout status deploy/vllm --timeout=20m

kubectl exec -n formica deploy/formica-controller -- \
  formica solve "Prove sqrt(2) is irrational" --budget 1 --timeout 600 --stream
```

## Troubleshooting

**Disk pressure during the first pull.**
Usually means the root volume is under 150 GB. The script preflights
for 120 GB free; if you started with 100 GB and DiskPressure fires
anyway, the cleanest fix is to terminate, relaunch with 200 GB, and
re-run.

**`neo4j-0` CrashLoopBackOff with `Unrecognized setting. No declared setting with name: PORT.7687.TCP.PORT`.**
Kubernetes auto-injects `*_PORT_*` env vars for every Service in the
namespace, and Neo4j's strict config validator rejects them. The base
manifest sets `enableServiceLinks: false`; if you edited it, confirm
that line is present.

**`otel-collector` crashes with `cannot start pipelines: unknown marshaler "otlp_parquet"`.**
You applied the base instead of the dev overlay. The production
manifest uses an `awss3` exporter with the `otlp_parquet` marshaler,
which is not compiled into the stock contrib image. The dev overlay
patches the ConfigMap to use the `debug` exporter; run
`kubectl apply -k deploy/k8s/overlays/dev` rather than
`kubectl apply -k deploy/k8s/base`.

**vLLM stuck in `ContainerCreating` for 10+ minutes.**
Check the pull: `kubectl describe -n formica pod -l app.kubernetes.io/component=vllm`.
The image is ~10 GB; on a fresh instance with a cold cache, 5-8 minutes
is normal. Longer than that usually means network egress is blocked
or the kubelet hit DiskPressure and evicted the sandbox.

**`ErrImagePull` for `formica:latest`.**
The image is not published to Docker Hub. The launcher builds it via
BuildKit in step 4. If buildkitd died or was pointed at the wrong
containerd socket, the build succeeds but the image never lands in
k3s's store. Verify with
`sudo k3s ctr -n k8s.io images ls -q | grep formica`.

## Teardown

```bash
sudo /usr/local/bin/k3s-uninstall.sh
```

Then terminate the EC2 instance.
