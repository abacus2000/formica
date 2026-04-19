# Capacity model

Formica **never requests new compute**. The spawn/retire controller only observes and
schedules within existing cluster capacity. When capacity changes (human adds a node,
external autoscaler reacts), the controller detects it passively on its next tick.

## Observed signals

Every `CAPACITY_TICK_SECONDS` (default: 10s) the controller reads:

| Signal                         | Source                          |
| ------------------------------ | ------------------------------- |
| Running pods per pool          | Kubernetes API (label selector) |
| Pending pods (any label)       | Kubernetes API                  |
| Per-node CPU/memory allocatable | `metrics-server` / node status |
| Per-node GPU allocatable       | Node labels `nvidia.com/gpu`    |
| Node pressure conditions       | Node status (`MemoryPressure`, `DiskPressure`, `PIDPressure`) |
| Recent validated-per-compute-sec | OTEL metrics (self-reported)  |

## Pool budgets

Agents belong to **pools**: `scout`, `forager`, `validator`, `gc`, `inquiline.*`.
Each pool has:

- `min_replicas`, `max_replicas` (hard caps from Helm values)
- `priority` (used to break ties under pressure)
- `headroom_quota` - fraction of remaining cluster headroom this pool may use

On each tick:

```python
headroom = compute_headroom(nodes, pods)
for pool in pools:
    target = min(
        pool.max_replicas,
        current(pool) + pool.spawn_signal(),
    )
    if pending_pods > PENDING_BACKPRESSURE:
        target = current(pool)                  # freeze
    if target > current(pool) and headroom_ok(pool, headroom):
        spawn(pool, target - current(pool))
    elif target < current(pool):
        retire(pool, current(pool) - target)
```

`spawn_signal()` combines:

- The **phase** (exploration raises scouts; consolidation raises validators/GC).
- The **`anternet` feedback**: recent `validated` yield per compute-second. If yield
  rises → spawn more of the pools that contributed most; if yield falls → retire.

## Back-pressure, not provisioning

When headroom is exhausted:

1. Spawn rate is throttled to zero for the affected pool.
2. The controller emits an `alarm` pheromone on a special `ColonyHealth` node. This
   wakes GC and validators to free capacity by pruning.
3. No external call is made. No MCP tool is called for new capacity.

## Passive expansion

The controller lists nodes by label selector each tick. When a new node appears, its
allocatable resources are included in the next headroom calculation. No restart, no
config change.

## Enforcement

- `ec2:RunInstances` is not in any Formica IAM policy.
- CI runs `grep -RIn "run_instances\|eks:UpdateNodegroup" formica/` and fails if any hits.
- The controller's unit tests include a case where the Kubernetes API is mocked to
  report zero headroom - the expected behavior is throttle + alarm, not any outbound call.
