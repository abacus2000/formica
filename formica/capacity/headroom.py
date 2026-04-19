"""Read cluster capacity from the Kubernetes API and metrics-server.

This module only *observes*. It never provisions or requests new compute.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NodeSnapshot:
    name: str
    allocatable_cpu_millis: int = 0
    allocatable_memory_bytes: int = 0
    allocatable_gpus: int = 0
    cpu_used_millis: int = 0
    memory_used_bytes: int = 0
    pressure: list[str] = field(default_factory=list)

    @property
    def cpu_free_millis(self) -> int:
        return max(0, self.allocatable_cpu_millis - self.cpu_used_millis)

    @property
    def memory_free_bytes(self) -> int:
        return max(0, self.allocatable_memory_bytes - self.memory_used_bytes)


@dataclass
class ClusterHeadroom:
    nodes: list[NodeSnapshot] = field(default_factory=list)
    pending_pods: int = 0
    running_pods_by_pool: dict[str, int] = field(default_factory=dict)

    @property
    def total_cpu_free_millis(self) -> int:
        return sum(n.cpu_free_millis for n in self.nodes)

    @property
    def total_memory_free_bytes(self) -> int:
        return sum(n.memory_free_bytes for n in self.nodes)

    @property
    def total_gpus_allocatable(self) -> int:
        return sum(n.allocatable_gpus for n in self.nodes)

    @property
    def any_node_under_pressure(self) -> bool:
        return any(n.pressure for n in self.nodes)


def _parse_cpu(val: str | None) -> int:
    if not val:
        return 0
    v = str(val)
    if v.endswith("m"):
        return int(v[:-1])
    try:
        return int(float(v) * 1000)
    except Exception:
        return 0


def _parse_memory(val: str | None) -> int:
    if not val:
        return 0
    v = str(val)
    units = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4,
             "K": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4}
    for suf, mult in units.items():
        if v.endswith(suf):
            try:
                return int(float(v[: -len(suf)]) * mult)
            except Exception:
                return 0
    try:
        return int(v)
    except Exception:
        return 0


def compute_headroom(
    core_v1,
    metrics_api=None,
    pool_label: str = "app.kubernetes.io/component",
) -> ClusterHeadroom:
    """Read nodes, pods, and (optionally) metrics; return a ClusterHeadroom snapshot.

    The Kubernetes clients are injected for testability. Pass the real
    `CoreV1Api` in production.
    """
    snap = ClusterHeadroom()
    # Nodes
    nodes = core_v1.list_node().items
    usage_by_node: dict[str, tuple[int, int]] = {}
    if metrics_api is not None:
        try:
            nm = metrics_api.list_cluster_custom_object(
                group="metrics.k8s.io", version="v1beta1", plural="nodes"
            )
            for item in nm.get("items", []):
                name = item["metadata"]["name"]
                usage_by_node[name] = (
                    _parse_cpu(item.get("usage", {}).get("cpu")),
                    _parse_memory(item.get("usage", {}).get("memory")),
                )
        except Exception:
            pass

    for n in nodes:
        alloc = n.status.allocatable or {}
        pressure = []
        for cond in (n.status.conditions or []):
            if cond.status == "True" and cond.type in ("MemoryPressure", "DiskPressure", "PIDPressure"):
                pressure.append(cond.type)
        name = n.metadata.name
        cpu_used, mem_used = usage_by_node.get(name, (0, 0))
        snap.nodes.append(
            NodeSnapshot(
                name=name,
                allocatable_cpu_millis=_parse_cpu(alloc.get("cpu")),
                allocatable_memory_bytes=_parse_memory(alloc.get("memory")),
                allocatable_gpus=int(alloc.get("nvidia.com/gpu", 0) or 0),
                cpu_used_millis=cpu_used,
                memory_used_bytes=mem_used,
                pressure=pressure,
            )
        )

    # Pods
    pods = core_v1.list_pod_for_all_namespaces().items
    for p in pods:
        phase = getattr(p.status, "phase", None)
        if phase == "Pending":
            snap.pending_pods += 1
        labels = (p.metadata.labels or {})
        pool = labels.get(pool_label)
        if pool:
            snap.running_pods_by_pool[pool] = snap.running_pods_by_pool.get(pool, 0) + 1
    return snap
