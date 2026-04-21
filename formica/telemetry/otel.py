"""OpenTelemetry tracing, metrics, and logs setup.

All components import this module and call `setup_otel(component_name)` during
startup. Every tick, pheromone write, validator verdict, alarm event, and
spawn/retire decision emits a span.
"""

from __future__ import annotations

import os
from functools import lru_cache

from formica.config import FormicaConfig

_INITIALIZED = False


def setup_otel(component: str, config: FormicaConfig | None = None) -> None:
    """Configure OTLP exporters keyed by component, env, and region.

    MVP: when FORMICA_OBSERVABILITY != "on" this is a no-op. Agents still
    log to stdout via structlog (see telemetry/logs.py), and get_tracer()
    still works (returns a no-op tracer), so no call sites need to change.
    Flip FORMICA_OBSERVABILITY=on and re-add otel-collector + fluent-bit
    to deploy/k8s/base/kustomization.yaml to turn the pipeline back on.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return
    cfg = config or FormicaConfig()

    if cfg.observability != "on":
        _INITIALIZED = True
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    except Exception:
        # OTEL is optional at import time; components degrade to stdout.
        _INITIALIZED = True
        return

    resource = Resource.create(
        {
            "service.name": f"{cfg.otel_service_name}.{component}",
            "deployment.environment": cfg.env,
            "cloud.region": cfg.region,
            "formica.component": component,
            "formica.env": cfg.env,
            "formica.region": cfg.region,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=cfg.otlp_endpoint, insecure=True))
    )
    trace.set_tracer_provider(provider)
    os.environ.setdefault("OTEL_SERVICE_NAME", f"{cfg.otel_service_name}.{component}")
    _INITIALIZED = True


@lru_cache(maxsize=16)
def get_tracer(name: str):
    from opentelemetry import trace

    return trace.get_tracer(name)
