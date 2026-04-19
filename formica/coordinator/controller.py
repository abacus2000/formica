"""Capacity-aware spawn/retire controller.

This controller NEVER provisions new compute. It observes cluster headroom
each tick and schedules within existing capacity. Newly added nodes are
picked up passively on the next tick.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from formica.capacity.headroom import compute_headroom
from formica.capacity.pools import Pool, PoolBudget, budget
from formica.config import FormicaConfig
from formica.coordinator.anternet import anternet_signal
from formica.coordinator.phases import PhaseState, pool_weights
from formica.telemetry.logs import get_logger
from formica.telemetry.otel import get_tracer

log = get_logger(__name__)


@dataclass
class Controller:
    """Single-process controller loop. Runs as a Deployment with replicas=1."""

    pools: list[Pool]
    config: FormicaConfig = field(default_factory=FormicaConfig)
    phase_state: PhaseState = field(default_factory=PhaseState)
    _last_validated_mass: float = 0.0
    _last_tick_monotonic: float = 0.0
    # Injected for testability. Defaults instantiate real clients.
    core_v1_factory: Callable | None = None
    metrics_api_factory: Callable | None = None
    batch_v1_factory: Callable | None = None

    # ---------- Kubernetes client bootstrap ----------

    def _k8s_clients(self):
        from kubernetes import client, config as k8s_config

        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()
        core = (self.core_v1_factory or client.CoreV1Api)()
        batch = (self.batch_v1_factory or client.BatchV1Api)()
        metrics = (self.metrics_api_factory or client.CustomObjectsApi)() if self.metrics_api_factory else None
        if metrics is None:
            try:
                metrics = client.CustomObjectsApi()
            except Exception:
                metrics = None
        return core, batch, metrics

    # ---------- Spawn / retire ----------

    def _spawn_pod(self, batch_v1, pool: Pool, run_id: str | None = None) -> str:
        from kubernetes import client

        name = f"{pool.name}-{uuid.uuid4().hex[:8]}".lower().replace("_", "-").replace(".", "-")[:63]
        env = [
            client.V1EnvVar(name="FORMICA_COMPONENT", value=pool.name),
            client.V1EnvVar(name="FORMICA_ENV", value=self.config.env),
            client.V1EnvVar(name="FORMICA_REGION", value=self.config.region),
            client.V1EnvVar(name="FORMICA_NEO4J_URI", value=self.config.neo4j_uri),
            client.V1EnvVar(name="FORMICA_NEO4J_USER", value=self.config.neo4j_user),
            client.V1EnvVar(name="FORMICA_NEO4J_PASSWORD", value=self.config.neo4j_password),
            client.V1EnvVar(name="FORMICA_OTLP_ENDPOINT", value=self.config.otlp_endpoint),
            client.V1EnvVar(name="FORMICA_RUN_ID", value=run_id or ""),
        ]
        resources = client.V1ResourceRequirements(
            requests={
                "cpu": f"{pool.cpu_request_millis}m",
                "memory": f"{pool.memory_request_bytes}",
            },
            limits={
                "cpu": f"{pool.cpu_request_millis * 2}m",
                "memory": f"{pool.memory_request_bytes * 2}",
            },
        )
        if pool.gpu_request:
            resources.limits["nvidia.com/gpu"] = str(pool.gpu_request)
        container = client.V1Container(
            name="agent",
            image=pool.image,
            image_pull_policy="IfNotPresent",
            env=env,
            resources=resources,
        )
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=name,
                namespace=self.config.namespace,
                labels={
                    "app.kubernetes.io/instance": "formica",
                    "app.kubernetes.io/component": pool.name,
                    "formica.pool": pool.name,
                },
            ),
            spec=client.V1JobSpec(
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={
                            "app.kubernetes.io/instance": "formica",
                            "app.kubernetes.io/component": pool.name,
                            "formica.pool": pool.name,
                        },
                    ),
                    spec=client.V1PodSpec(
                        containers=[container],
                        restart_policy="Never",
                        service_account_name="formica-agent",
                    ),
                ),
                backoff_limit=1,
                ttl_seconds_after_finished=300,
            ),
        )
        batch_v1.create_namespaced_job(namespace=self.config.namespace, body=job)
        return name

    def _retire_oldest(self, batch_v1, pool: Pool, n: int) -> int:
        from kubernetes import client

        jobs = batch_v1.list_namespaced_job(
            namespace=self.config.namespace,
            label_selector=f"formica.pool={pool.name}",
        ).items
        jobs_sorted = sorted(jobs, key=lambda j: j.metadata.creation_timestamp or 0)
        retired = 0
        for j in jobs_sorted[:n]:
            try:
                batch_v1.delete_namespaced_job(
                    name=j.metadata.name,
                    namespace=self.config.namespace,
                    body=client.V1DeleteOptions(propagation_policy="Background"),
                )
                retired += 1
            except Exception as e:
                log.warning("retire failed", extra={"job": j.metadata.name, "err": str(e)})
        return retired

    # ---------- Main loop ----------

    def tick(
        self,
        validated_mass: float,
        entropy: float,
        run_id: str | None = None,
    ) -> list[PoolBudget]:
        """One controller tick. Returns the per-pool budget decisions taken."""
        tracer = get_tracer("formica.controller")
        with tracer.start_as_current_span("controller.tick") as span:
            phase, changed = self.phase_state.transition(entropy)
            if changed:
                log.info("phase transition", extra={"phase": phase.value, "entropy": entropy})
                span.add_event("phase_transition", {"phase": phase.value, "entropy": entropy})

            now = time.monotonic()
            compute_seconds = max(0.0, now - (self._last_tick_monotonic or now))
            self._last_tick_monotonic = now
            validated_delta = max(0.0, validated_mass - self._last_validated_mass)
            self._last_validated_mass = validated_mass
            antnet = anternet_signal(validated_delta, compute_seconds or 1e-6)
            weights = pool_weights(phase)

            core, batch, metrics = self._k8s_clients()
            headroom = compute_headroom(core, metrics)
            span.set_attribute("formica.phase", phase.value)
            span.set_attribute("formica.anternet", antnet)
            span.set_attribute("formica.pending_pods", headroom.pending_pods)
            span.set_attribute("formica.nodes", len(headroom.nodes))

            decisions: list[PoolBudget] = []
            for pool in self.pools:
                desired_base = headroom.running_pods_by_pool.get(pool.name, pool.min_replicas)
                desired = int(round(desired_base * weights.get(pool.name, 1.0) * antnet))
                desired = max(pool.min_replicas, min(pool.max_replicas, desired))
                b = budget(pool, headroom, desired, pending_backpressure=self.config.pending_backpressure)
                decisions.append(b)
                for _ in range(b.allowed_spawn):
                    try:
                        self._spawn_pod(batch, pool, run_id=run_id)
                    except Exception as e:
                        log.error("spawn failed", extra={"pool": pool.name, "err": str(e)})
                if b.allowed_retire > 0:
                    self._retire_oldest(batch, pool, b.allowed_retire)
                if b.throttled:
                    log.warning(
                        "pool throttled",
                        extra={"pool": pool.name, "reason": b.reason, "pending": headroom.pending_pods},
                    )
                    # Emit an alarm pheromone pathway via CLI/Forum if desired;
                    # the controller only logs, Forum writes happen from validators.
            span.set_attribute("formica.decisions", len(decisions))
            return decisions

    def run_forever(self, fetch_entropy: Callable[[], tuple[float, float]]) -> None:
        """Entrypoint. `fetch_entropy` returns (validated_mass, entropy)."""
        while True:
            try:
                validated_mass, entropy = fetch_entropy()
                self.tick(validated_mass, entropy)
            except Exception:
                log.exception("controller tick failed")
            time.sleep(self.config.capacity_tick_seconds)
