# ADR-0006: No capacity provisioning - ever

**Status**: Accepted (constraint)
**Date**: 2026-04-19

## Context

Rome's `RomeK8sClient.create_worker_job` blindly creates Jobs; if the cluster is
out of capacity, pods pile up in `Pending`. Rome assumes the cluster autoscaler
(or a human) will add nodes. Formica tightens the contract.

## Decision

The Formica controller **must not** request new compute. No autoscaler hooks, no EC2
Run-Instances, no Karpenter triggers, no GPU-capacity MCP. The spawn/retire controller:

1. Reads cluster headroom (pod count, CPU/GPU/memory, pending-pod depth, node
   pressure) every tick from the Kubernetes API and `metrics-server`.
2. Respects per-pool budgets derived from headroom.
3. If headroom is insufficient: throttles spawn rate, promotes lower-priority agents
   to retirement, or emits `alarm` pheromone. Never escalates outward.
4. Detects newly added nodes (human action or external autoscaler) passively -
   on the next tick, headroom increases and spawns resume with no config change.

## Consequences

- **+** Predictable cost ceiling per cluster.
- **+** Playing nicely with existing autoscaler strategies (Karpenter, CA) - the
  controller is agnostic to how nodes arrive.
- **−** Users must size the cluster for peak load or accept back-pressure.

## Enforcement

- Code search `grep -r "run_instances\|create_node\|capacity_request"` in CI fails the build.
- No IAM policy grants `ec2:RunInstances` or `eks:UpdateNodegroupConfig`.
