"""Capacity math — pool budgeting and headroom. Never provisions."""

from formica.capacity.headroom import ClusterHeadroom, NodeSnapshot
from formica.capacity.pools import Pool, budget


def _h(nodes, pending=0, by_pool=None):
    return ClusterHeadroom(
        nodes=nodes,
        pending_pods=pending,
        running_pods_by_pool=by_pool or {},
    )


def test_spawn_allowed_when_headroom_ample():
    nodes = [NodeSnapshot(name="n1", allocatable_cpu_millis=4000,
                          allocatable_memory_bytes=8 * 1024**3)]
    h = _h(nodes, by_pool={"forager": 2})
    p = Pool(name="forager", image="x", min_replicas=0, max_replicas=10,
             cpu_request_millis=250, memory_request_bytes=256 * 1024 * 1024)
    b = budget(p, h, desired=6)
    assert not b.throttled
    assert b.allowed_spawn == 4  # 6 - 2 currently running
    assert b.allowed_retire == 0


def test_spawn_throttled_when_pending_backpressure():
    nodes = [NodeSnapshot(name="n1", allocatable_cpu_millis=4000,
                          allocatable_memory_bytes=8 * 1024**3)]
    h = _h(nodes, pending=10, by_pool={"forager": 2})
    p = Pool(name="forager", image="x", min_replicas=0, max_replicas=10)
    b = budget(p, h, desired=6, pending_backpressure=5)
    assert b.throttled
    assert b.allowed_spawn == 0
    assert "pending_backpressure" in b.reason


def test_spawn_throttled_when_node_pressure():
    nodes = [NodeSnapshot(name="n1", allocatable_cpu_millis=4000,
                          allocatable_memory_bytes=8 * 1024**3,
                          pressure=["MemoryPressure"])]
    h = _h(nodes, by_pool={"forager": 2})
    p = Pool(name="forager", image="x", max_replicas=10)
    b = budget(p, h, desired=6)
    assert b.throttled
    assert b.reason == "node_pressure"
    assert b.allowed_spawn == 0


def test_passive_expansion_detected():
    # Start with zero capacity, then add a node.
    empty = _h([])
    p = Pool(name="forager", image="x", min_replicas=0, max_replicas=10,
             cpu_request_millis=250, memory_request_bytes=256 * 1024 * 1024)
    b = budget(p, empty, desired=4)
    assert b.allowed_spawn == 0

    # Operator (or external autoscaler) added a node.
    added = _h([NodeSnapshot(name="new", allocatable_cpu_millis=2000,
                             allocatable_memory_bytes=4 * 1024**3)])
    b2 = budget(p, added, desired=4)
    # The controller immediately uses the new headroom — no config change.
    assert b2.allowed_spawn > 0


def test_gpu_pool_respects_gpu_limit():
    nodes = [NodeSnapshot(name="gpu1", allocatable_cpu_millis=8000,
                          allocatable_memory_bytes=16 * 1024**3, allocatable_gpus=2)]
    h = _h(nodes, by_pool={"gpu-pool": 0})
    p = Pool(name="gpu-pool", image="x", min_replicas=0, max_replicas=10,
             cpu_request_millis=250, memory_request_bytes=256 * 1024 * 1024,
             gpu_request=1, headroom_quota=1.0)
    b = budget(p, h, desired=5)
    # Only 2 GPUs available → only 2 allowed.
    assert b.allowed_spawn == 2
