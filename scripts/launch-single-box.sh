#!/usr/bin/env bash
#
# launch-single-box.sh
#
# One-shot bring-up for a Formica single-box deployment on a fresh
# Amazon Linux 2023 EC2 GPU instance (validated on g5.xlarge with the
# rome AMI, ami-079c82d610e02e480).
#
# Produces a cluster with:
#   - k3s v1.34 (containerd, no Docker)
#   - NVIDIA device plugin with RuntimeClass "nvidia"
#   - BuildKit building formica:latest directly into k3s containerd
#   - Formica controller, Neo4j, vLLM, and the dev otel collector
#
# The script is idempotent: each step checks whether it has already run
# and skips cleanly. Safe to re-run if interrupted.
#
# Run as ec2-user (NOT root, NOT via sudo). The script will invoke
# sudo itself where needed.
#
# Usage:
#   cd ~/formica
#   bash scripts/launch-single-box.sh
#
# Environment knobs:
#   FORMICA_REPO_DIR  Path to the cloned repo (default: $HOME/formica)
#   K3S_VERSION       Pin a specific k3s channel (default: v1.34 via get.k3s.io)
#   BUILDKIT_VERSION  BuildKit release (default: v0.18.1)
#   DEVICE_PLUGIN_VER NVIDIA device plugin (default: v0.17.0)
#   SKIP_SMOKE        If set to 1, skip the final formica solve smoke test.

set -euo pipefail

REPO_DIR="${FORMICA_REPO_DIR:-$HOME/formica}"
BUILDKIT_VERSION="${BUILDKIT_VERSION:-v0.18.1}"
DEVICE_PLUGIN_VER="${DEVICE_PLUGIN_VER:-v0.17.0}"
SKIP_SMOKE="${SKIP_SMOKE:-0}"

STEP=0
step() {
  STEP=$((STEP + 1))
  echo
  echo "========================================"
  echo "[step $STEP] $*"
  echo "========================================"
}
note() { echo "    $*"; }

if [[ $EUID -eq 0 ]]; then
  echo "Do not run this as root. Run as ec2-user; sudo is invoked internally."
  exit 1
fi

if [[ ! -d "$REPO_DIR" ]]; then
  echo "Repo not found at $REPO_DIR. Clone it first:"
  echo "  git clone https://github.com/abacus2000/formica.git $REPO_DIR"
  exit 1
fi

cd "$REPO_DIR"

# ---------------------------------------------------------------
step "Preflight: GPU, disk, and tools"
# ---------------------------------------------------------------
if ! command -v nvidia-smi >/dev/null; then
  echo "nvidia-smi not found. This script assumes the rome AMI (CUDA + driver preinstalled)."
  echo "On a vanilla AMI, install driver + nvidia-container-toolkit first."
  exit 1
fi
nvidia-smi -L

ROOT_FREE_GB=$(df -BG / | awk 'NR==2 {gsub("G",""); print $4}')
ROOT_TOTAL_GB=$(df -BG / | awk 'NR==2 {gsub("G",""); print $2}')
note "Root volume: ${ROOT_TOTAL_GB} GB total, ${ROOT_FREE_GB} GB free"

# Two checks. Total size is structural and always enforced: under 150 GB
# the vLLM image plus build cache plus kubelet ephemeral cannot all fit
# at once and DiskPressure will evict pods during the first pull.
if [[ "$ROOT_TOTAL_GB" -lt 150 ]]; then
  echo
  echo "ERROR: root volume is only ${ROOT_TOTAL_GB} GB. Need at least 200 GB."
  echo "       Relaunch the instance with a 200 GB gp3 root volume."
  exit 1
fi

# Free-space check is advisory and only matters on the very first run,
# before we have pulled the vLLM image. After that, 80+ GB free is fine.
if [[ "$ROOT_FREE_GB" -lt 60 ]]; then
  echo
  echo "ERROR: only ${ROOT_FREE_GB} GB free on /. Need 60 GB headroom."
  echo "       Run 'sudo k3s ctr -n k8s.io images prune' or grow the volume."
  exit 1
fi

# ---------------------------------------------------------------
step "Install k3s (no Traefik, readable kubeconfig)"
# ---------------------------------------------------------------
if systemctl is-active --quiet k3s; then
  note "k3s already active, skipping install"
else
  curl -sfL https://get.k3s.io | \
    INSTALL_K3S_EXEC="--disable=traefik --write-kubeconfig-mode=644" sh -
fi

# Wire kubectl for ec2-user
mkdir -p "$HOME/.kube"
sudo cp /etc/rancher/k3s/k3s.yaml "$HOME/.kube/config"
sudo chown "$(id -u):$(id -g)" "$HOME/.kube/config"
export KUBECONFIG="$HOME/.kube/config"

kubectl wait --for=condition=Ready node --all --timeout=180s
note "k3s up. Node:"
kubectl get nodes

# ---------------------------------------------------------------
step "Expose GPU to pods (RuntimeClass + device plugin)"
# ---------------------------------------------------------------
cat <<'YAML' | kubectl apply -f -
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: nvidia
handler: nvidia
YAML

kubectl apply -f \
  "https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/${DEVICE_PLUGIN_VER}/deployments/static/nvidia-device-plugin.yml"

# Pin the plugin daemonset to the nvidia runtime so it can see /dev/nvidia*.
# This patch is a no-op on re-apply.
CURRENT_RC=$(kubectl -n kube-system get ds nvidia-device-plugin-daemonset \
  -o jsonpath='{.spec.template.spec.runtimeClassName}' 2>/dev/null || echo "")
if [[ "$CURRENT_RC" != "nvidia" ]]; then
  kubectl -n kube-system patch daemonset nvidia-device-plugin-daemonset \
    --type=json \
    -p '[{"op":"add","path":"/spec/template/spec/runtimeClassName","value":"nvidia"}]'
fi

note "Waiting for device plugin to advertise nvidia.com/gpu..."
for i in {1..30}; do
  GPU=$(kubectl get node -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}' 2>/dev/null || echo "")
  if [[ -n "$GPU" && "$GPU" != "0" ]]; then
    note "Allocatable GPUs: $GPU"
    break
  fi
  sleep 4
done
[[ -n "${GPU:-}" && "$GPU" != "0" ]] || { echo "GPU never became allocatable"; exit 1; }

# ---------------------------------------------------------------
step "Install BuildKit and build formica:latest into k3s containerd"
# ---------------------------------------------------------------
if ! command -v buildctl >/dev/null; then
  curl -fsSL "https://github.com/moby/buildkit/releases/download/${BUILDKIT_VERSION}/buildkit-${BUILDKIT_VERSION}.linux-amd64.tar.gz" \
    | sudo tar -C /usr/local -xzf -
fi

if ! pgrep -x buildkitd >/dev/null; then
  # Redirect must be inside the sudo'd shell or it runs as the calling user
  # and fails with Permission denied on /var/log/.
  sudo sh -c 'nohup /usr/local/bin/buildkitd \
    --oci-worker=false \
    --containerd-worker=true \
    --containerd-worker-addr=/run/k3s/containerd/containerd.sock \
    --containerd-worker-namespace=k8s.io \
    >/var/log/buildkitd.log 2>&1 &'
  # /run/buildkit is mode 0770 root:root, so 'test -S' must run as root.
  for i in {1..20}; do
    if sudo test -S /run/buildkit/buildkitd.sock; then break; fi
    sleep 1
  done
  if ! sudo test -S /run/buildkit/buildkitd.sock; then
    echo "buildkitd failed to start. Last 40 lines of /var/log/buildkitd.log:"
    sudo tail -40 /var/log/buildkitd.log || true
    exit 1
  fi
fi

note "Verifying buildkitd worker is reachable..."
sudo /usr/local/bin/buildctl debug workers >/dev/null

note "Building formica:latest (this pulls the base image on first run)..."
sudo /usr/local/bin/buildctl build \
  --frontend dockerfile.v0 \
  --local context=. \
  --local dockerfile=. \
  --output type=image,name=docker.io/library/formica:latest

sudo k3s ctr -n k8s.io images ls -q | grep -q '^docker.io/library/formica:latest$' \
  || { echo "Build succeeded but image not in k3s containerd store"; exit 1; }
note "formica:latest is in k3s containerd store."

# ---------------------------------------------------------------
step "Deploy Formica (dev overlay)"
# ---------------------------------------------------------------
kubectl apply -k deploy/k8s/overlays/dev

note "Waiting for the core deployments. vLLM pulls ~10 GB on a fresh box,"
note "so it can legitimately take 5-10 minutes."

# Neo4j is a StatefulSet and comes up in ~1 minute.
kubectl -n formica rollout status statefulset/neo4j --timeout=5m

# Controller typically Ready in under a minute once neo4j is.
kubectl -n formica rollout status deploy/formica-controller --timeout=5m

# Otel collector is immediate.
kubectl -n formica rollout status deploy/otel-collector --timeout=2m

# vLLM is the long pole.
kubectl -n formica rollout status deploy/vllm --timeout=20m

note "Pod status:"
kubectl -n formica get pods -o wide

# ---------------------------------------------------------------
step "Smoke test: formica solve"
# ---------------------------------------------------------------
if [[ "$SKIP_SMOKE" == "1" ]]; then
  note "SKIP_SMOKE=1, skipping."
  exit 0
fi

# Install the CLI into the user's site-packages.
if ! command -v formica >/dev/null; then
  note "Installing formica CLI (pip install -e)..."
  python3 -m pip install --user -e ".[dev]"
  export PATH="$HOME/.local/bin:$PATH"
fi

# Port-forwards. Kill any old ones first.
pkill -f "kubectl.*port-forward.*neo4j"  2>/dev/null || true
pkill -f "kubectl.*port-forward.*vllm"   2>/dev/null || true
sleep 1
kubectl -n formica port-forward svc/neo4j 7687:7687 >/tmp/pf-neo4j.log 2>&1 &
kubectl -n formica port-forward svc/vllm  8080:8080 >/tmp/pf-vllm.log  2>&1 &
sleep 3

export FORMICA_NEO4J_URI="bolt://localhost:7687"
export FORMICA_MODEL_BASE_URL="http://localhost:8080/v1"

note "Running: formica solve \"Prove sqrt(2) is irrational\" --budget 1 --timeout 600"
formica solve "Prove sqrt(2) is irrational" --budget 1 --timeout 600

echo
echo "==================================================="
echo "Formica is up. Pod state:"
echo "==================================================="
kubectl -n formica get pods
