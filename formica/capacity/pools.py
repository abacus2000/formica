"""Agent pools and per-pool capacity budgets."""

from __future__ import annotations

from dataclasses import dataclass

from formica.capacity.headroom import ClusterHeadroom


@dataclass
class Pool:
    name: str
    image: str
    min_replicas: int = 0
    max_replicas: int = 4
    priority: int = 5
    cpu_request_millis: int = 250
    memory_request_bytes: int = 256 * 1024 * 1024
    gpu_request: int = 0
    headroom_quota: float = 0.25  # fraction of remaining headroom this pool may use


@dataclass
class PoolBudget:
    """Outcome of a budgeting pass."""

    pool: Pool
    current: int
    target: int
    allowed_spawn: int
    allowed_retire: int
    throttled: bool
    reason: str = ""


def budget(
    pool: Pool,
    headroom: ClusterHeadroom,
    desired: int,
    pending_backpressure: int = 5,
) -> PoolBudget:
    """Compute how many of `pool` may spawn/retire given headroom and desired count."""
    current = headroom.running_pods_by_pool.get(pool.name, 0)
    desired = max(pool.min_replicas, min(pool.max_replicas, desired))

    # Back-pressure: if too many pending pods cluster-wide, freeze spawning.
    if headroom.pending_pods >= pending_backpressure:
        return PoolBudget(
            pool=pool,
            current=current,
            target=current,
            allowed_spawn=0,
            allowed_retire=max(0, current - desired),
            throttled=True,
            reason=f"pending_backpressure={headroom.pending_pods}",
        )

    # Node pressure → freeze spawning.
    if headroom.any_node_under_pressure:
        return PoolBudget(
            pool=pool,
            current=current,
            target=current,
            allowed_spawn=0,
            allowed_retire=max(0, current - desired),
            throttled=True,
            reason="node_pressure",
        )

    spawn_needed = max(0, desired - current)
    retire_needed = max(0, current - desired)

    # Per-pool CPU/memory/GPU headroom check, scaled by pool's quota.
    cpu_budget_millis = int(headroom.total_cpu_free_millis * pool.headroom_quota)
    mem_budget_bytes = int(headroom.total_memory_free_bytes * pool.headroom_quota)
    gpu_budget = int(headroom.total_gpus_allocatable * pool.headroom_quota)

    max_by_cpu = cpu_budget_millis // max(1, pool.cpu_request_millis)
    max_by_mem = mem_budget_bytes // max(1, pool.memory_request_bytes)
    max_by_gpu = (
        gpu_budget // max(1, pool.gpu_request) if pool.gpu_request > 0 else spawn_needed
    )
    allowed_spawn = min(spawn_needed, max_by_cpu, max_by_mem, max_by_gpu)

    throttled = allowed_spawn < spawn_needed
    reason = (
        f"cpu_max={max_by_cpu} mem_max={max_by_mem} gpu_max={max_by_gpu}"
        if throttled
        else ""
    )
    return PoolBudget(
        pool=pool,
        current=current,
        target=desired,
        allowed_spawn=allowed_spawn,
        allowed_retire=retire_needed,
        throttled=throttled,
        reason=reason,
    )
