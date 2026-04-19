"""Controller capacity logic against mocked k8s clients (no real cluster)."""

from __future__ import annotations

from types import SimpleNamespace

from formica.capacity.headroom import compute_headroom


class _FakeCore:
    def __init__(self, nodes, pods):
        self._nodes = nodes
        self._pods = pods

    def list_node(self):
        return SimpleNamespace(items=self._nodes)

    def list_pod_for_all_namespaces(self):
        return SimpleNamespace(items=self._pods)


def _node(name, cpu_m, mem_gi, gpus=0, pressure=()):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        status=SimpleNamespace(
            allocatable={
                "cpu": f"{cpu_m}m",
                "memory": f"{mem_gi}Gi",
                "nvidia.com/gpu": gpus,
            },
            conditions=[SimpleNamespace(type=p, status="True") for p in pressure],
        ),
    )


def _pod(phase="Running", labels=None):
    return SimpleNamespace(
        metadata=SimpleNamespace(labels=labels or {}),
        status=SimpleNamespace(phase=phase),
    )


def test_compute_headroom_counts_pools_and_pending():
    core = _FakeCore(
        nodes=[_node("n1", 2000, 4)],
        pods=[
            _pod(labels={"app.kubernetes.io/component": "forager"}),
            _pod(labels={"app.kubernetes.io/component": "forager"}),
            _pod(phase="Pending"),
        ],
    )
    h = compute_headroom(core, metrics_api=None)
    assert h.running_pods_by_pool.get("forager") == 2
    assert h.pending_pods == 1
    assert h.total_cpu_free_millis == 2000


def test_compute_headroom_picks_up_new_node():
    core1 = _FakeCore(nodes=[_node("n1", 1000, 2)], pods=[])
    assert compute_headroom(core1).total_cpu_free_millis == 1000
    # Now a node is added. Same controller, next tick.
    core2 = _FakeCore(nodes=[_node("n1", 1000, 2), _node("n2", 4000, 8)], pods=[])
    h2 = compute_headroom(core2)
    assert h2.total_cpu_free_millis == 5000
    assert len(h2.nodes) == 2


def test_node_pressure_propagates():
    core = _FakeCore(nodes=[_node("n1", 1000, 2, pressure=["MemoryPressure"])], pods=[])
    h = compute_headroom(core)
    assert h.any_node_under_pressure
