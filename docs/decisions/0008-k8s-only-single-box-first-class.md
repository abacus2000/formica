# ADR 0008: Kubernetes-only runtime, single-box as a first-class k3d cluster

- Status: Accepted
- Date: 2026-04-19
- Supersedes parts of: ADR-0007

## Context

Before this ADR, Formica shipped two parallel single-box paths:

1. A Docker Compose stack (`deploy/compose/docker-compose.yml`) bringing
   up Neo4j + vLLM, paired with an in-process tick loop exposed as
   `formica solve --local`.
2. A full Kubernetes stack (`deploy/k8s/overlays/dev`) that ran the
   actual capacity-aware controller (`formica.coordinator.controller`)
   and spawned per-agent Kubernetes Jobs per caste.

These two paths executed *different code*. Path 1 skipped the
controller entirely and drove Scouts/Foragers/Validators/GC inline from
the CLI process. Path 2 was the real system. This created two
maintenance burdens and, more importantly, meant single-box users were
not exercising the code that runs in production - defeating the point
of single-box dev.

The controller's use of Kubernetes (Jobs for agents, CoreV1 for node
headroom, BatchV1 for retire) is *not* intrinsically multi-node. A
single-node k3s cluster (via k3d) runs all of it unchanged: Jobs land
on the one available node, `compute_headroom` reads that node's free
CPU/mem, and `budget()` scales spawns against it. The only thing
single-box mode actually needs that multi-node doesn't is a local vLLM
with GPU access - and that's a `hostPath`-mounted Deployment, not a
reason to have a second runtime.

## Decision

1. Delete `deploy/compose/` and `docs/local-gpu-dev.md`.
2. Remove the `--local` flag and `_build_local_tick` from the CLI.
   `formica solve` is now unconditionally a thin client that talks to
   the Forum and expects a running controller.
3. Add `deploy/k8s/base/vllm.yaml` (Deployment + Service) and the
   matching Helm template so vLLM is a first-class in-cluster
   component, not a Compose-only artifact.
4. Change `FormicaConfig.model_base_url` default from
   `http://localhost:8080/v1` to the in-cluster Service DNS
   `http://vllm.formica.svc.cluster.local:8080/v1`. Out-of-cluster
   callers port-forward and override via `FORMICA_MODEL_BASE_URL`.
5. Document k3d as *the* single-box workflow in `docs/single-box.md`.

## Alternatives considered

- **Keep both paths.** Rejected: it's exactly the divergence this ADR
  exists to eliminate. Every controller/agent change had to be
  hand-mirrored into `_build_local_tick`, and the two paths had
  already drifted (Compose had no controller, no RBAC, no OTEL
  collector by default).
- **Keep Compose, delete `--local`.** Rejected: Compose without
  `--local` is just "two infra containers with no colony running,"
  which is a footgun - users would `docker compose up` and see
  nothing happen.
- **Delete K8s, make Compose canonical.** Rejected: throws away the
  capacity-aware controller, per-agent resource isolation, RBAC, IRSA,
  and the "same manifests scale to EKS" guarantee. That story is
  central to Formica's design.

## Consequences

- Single-box users now need `k3d`, `kubectl`, and `kustomize` on the
  box. The prebaked GPU AMI already has Docker; adding k3d is a single
  `curl | bash`. We'll update the AMI bake script in a follow-up.
- GPU access in k3d requires the NVIDIA device plugin (or the GPU
  Operator). `docs/single-box.md` points users at the device plugin
  install; the GPU Operator is the preferred choice on EKS.
- `test_default_model_base_url_targets_local_vllm` was renamed to
  `test_default_model_base_url_targets_in_cluster_vllm` and updated
  to assert the new default.
- The `docs/local-gpu-dev.md` walkthrough is gone. `docs/single-box.md`
  replaces it and covers the same ground end-to-end.
- Existing unit/integration/e2e tests are unaffected: they already
  used `FakeForum` and never depended on the `--local` path.
