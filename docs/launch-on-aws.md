# Launch Formica on a single EC2 GPU box

This is the exact recipe that is known to bring up a working Formica
cluster on AWS from scratch. It uses the prebaked open-weight AMI from
the [rome](https://github.com/abacus2000/rome) project, which ships with
CUDA 13, NVIDIA drivers, `nvidia-container-toolkit`, `nerdctl`, and the
Mistral-7B-Instruct-v0.2-AWQ weights already staged at
`/opt/models/mistral-awq`.

If you are on a different AMI, first install drivers and
`nvidia-container-toolkit` per the
[NVIDIA docs](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
and stage weights yourself. Everything else below is identical.

## 1. Launch the instance

| Setting             | Value                                             |
| ------------------- | ------------------------------------------------- |
| Instance type       | `g5.xlarge` (A10G, 24 GB GPU memory, 4 vCPU, 16 GB RAM) |
| AMI                 | `ami-079c82d610e02e480` (shared from rome)        |
| Root volume         | 100 GB gp3 (you will regret anything smaller)     |
| IAM instance profile| role with `AmazonSSMManagedInstanceCore` attached |
| Security group      | egress any (pulls from Docker Hub, nvcr.io, GitHub) |

You do not need to open inbound ports. All access is via SSM Session
Manager or `kubectl port-forward` tunneled over SSH / SSM.

## 2. Connect

```bash
aws ssm start-session --target i-XXXXXXXXXXXXXXXXX --region us-east-1
sudo su - ec2-user
```

Clone the repo:

```bash
git clone https://github.com/abacus2000/formica.git ~/formica
cd ~/formica
```

## 3. Install k3s

```bash
curl -sfL https://get.k3s.io | \
  INSTALL_K3S_EXEC="--disable=traefik --write-kubeconfig-mode=644" sh -

# Give kubectl access to the non-root user.
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config

kubectl wait --for=condition=Ready node --all --timeout=120s
```

Known gotcha: do NOT drop a `config.toml.tmpl` under
`/var/lib/rancher/k3s/agent/etc/containerd/`. k3s v1.34+ auto-detects
`nvidia-container-runtime` in `$PATH` and registers it. Adding your own
template causes containerd to fail with
`toml: table nvidia already exists` and the node never becomes Ready.

## 4. Expose the GPU to pods

```bash
# 4a. Register the RuntimeClass.
cat <<'YAML' | kubectl apply -f -
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: nvidia
handler: nvidia
YAML

# 4b. Install the NVIDIA device plugin.
kubectl apply -f \
  https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.17.0/deployments/static/nvidia-device-plugin.yml

# 4c. Pin the plugin to the nvidia runtime. Without this it cannot see
#     /dev/nvidia* and the GPU stays unallocatable.
kubectl -n kube-system patch daemonset nvidia-device-plugin-daemonset \
  --type=json \
  -p '[{"op":"add","path":"/spec/template/spec/runtimeClassName","value":"nvidia"}]'

# 4d. Verify. Expect "1" (or however many GPUs the instance has).
kubectl get node -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}'
echo
```

## 5. Install BuildKit and build the controller image

`formica-controller` and the evaporation CronJobs reference
`image: formica:latest`. The image is not published; we build it
directly into k3s's containerd image store with BuildKit.

```bash
BK_VERSION=v0.18.1
curl -fsSL "https://github.com/moby/buildkit/releases/download/${BK_VERSION}/buildkit-${BK_VERSION}.linux-amd64.tar.gz" \
  | sudo tar -C /usr/local -xzf -

# Long-running daemon; running it under nohup is fine for a dev box.
sudo nohup buildkitd \
  --oci-worker=false \
  --containerd-worker=true \
  --containerd-worker-addr=/run/k3s/containerd/containerd.sock \
  --containerd-worker-namespace=k8s.io \
  >/var/log/buildkitd.log 2>&1 &

# Build. ~30s on a g5.xlarge (pure Python deps).
cd ~/formica
sudo buildctl build \
  --frontend dockerfile.v0 \
  --local context=. \
  --local dockerfile=. \
  --output type=image,name=docker.io/library/formica:latest

sudo k3s ctr -n k8s.io images ls -q | grep formica
```

## 6. Deploy Formica

```bash
kubectl apply -k deploy/k8s/overlays/dev

# vLLM pulls vllm/vllm-openai:latest (~10 GB). First pull is slow.
kubectl -n formica rollout status deploy/vllm --timeout=20m
```

You should see pods settle into this steady state:

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

## 7. Run a solve

```bash
cd ~/formica
pip3 install -e ".[dev]"

kubectl -n formica port-forward svc/neo4j 7687:7687 &
kubectl -n formica port-forward svc/vllm  8080:8080 &

export FORMICA_NEO4J_URI=bolt://localhost:7687
export FORMICA_MODEL_BASE_URL=http://localhost:8080/v1

formica solve "Prove sqrt(2) is irrational" --budget 1 --timeout 600
```

You should see validated Evidence stream as Validator pods emit it.

## Troubleshooting

**Node goes `NotReady` with disk pressure.**
The 100 GB root fills up fast when you have Docker + k3s containerd
both hoarding images. If you came from the k3d path and still have
`/var/lib/docker`, reclaim it:

```bash
sudo systemctl stop docker docker.socket
sudo dnf remove -y docker docker-ce docker-ce-cli containerd.io
sudo rm -rf /var/lib/docker
```

On the prebaked AMI the taint clears automatically once free space
crosses the kubelet eviction threshold.

**`neo4j-0` CrashLoopBackOff with `Unrecognized setting. No declared setting with name: PORT.7687.TCP.PORT`.**
Kubernetes auto-injects `*_PORT_*` env vars for every Service in the
namespace, and neo4j's strict config validator rejects them. The base
manifest already sets `enableServiceLinks: false`; if you edited it
check that line is present.

**`otel-collector` crashes with `cannot start pipelines: unknown marshaler "otlp_parquet"`.**
You are running the production (`awss3` + `otlp_parquet`) exporter on a
collector build that does not include the parquet marshaler. The dev
overlay in `deploy/k8s/overlays/dev/` patches the ConfigMap to use the
`debug` exporter instead; make sure you applied the overlay and not
the bare base.

**vLLM is stuck in `ContainerCreating` for 10+ minutes.**
Check the pull: `kubectl describe -n formica pod -l app.kubernetes.io/component=vllm`.
The image is ~10 GB; on a fresh instance with a cold image layer cache
this can realistically take 5–8 minutes.

**I get `ErrImagePull` for `formica:latest`.**
The image is not published to Docker Hub. You must build it locally per
step 5. If buildkitd is not running or pointed at the wrong containerd
socket, the build succeeds but the image never lands in k3s's store.
Check `sudo k3s ctr -n k8s.io images ls -q | grep formica`.

## Teardown

```bash
sudo /usr/local/bin/k3s-uninstall.sh
```

Then terminate the EC2 instance.
