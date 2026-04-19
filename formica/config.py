"""Centralized environment-based configuration for Formica."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class FormicaConfig(BaseSettings):
    """All Formica configuration, loaded from env vars prefixed with FORMICA_."""

    # Environment / region identity (drives log group and S3 bucket names)
    env: str = "dev"
    region: str = "us-east-1"

    # Neo4j (Forum)
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "changeme"
    neo4j_database: str = "neo4j"

    # LLM model.
    #
    # Formica defaults to the open-weight model that is pre-baked into the GPU
    # AMI (shared with the rome project): Mistral-7B-Instruct-v0.2-AWQ, served
    # by vLLM on :8080 with an OpenAI-compatible API. Weights live at
    # /opt/models/mistral-awq on the AMI; the bundled docker-compose mounts
    # that path into the vllm container read-only so nothing is downloaded at
    # boot. See docs/local-gpu-dev.md and docs/decisions/0007-open-weight-default.md.
    #
    # To switch to another provider (e.g. Bedrock for prod) override with env:
    #   FORMICA_MODEL_PROVIDER=bedrock FORMICA_MODEL_ID=anthropic.claude-3-...
    model_base_url: str = "http://localhost:8080/v1"
    model_id: str = "TheBloke/Mistral-7B-Instruct-v0.2-AWQ"
    model_provider: str = "openai"  # openai | ollama | bedrock

    # Kubernetes
    namespace: str = "formica"

    # OpenTelemetry
    otlp_endpoint: str = "http://otel-collector:4317"
    otel_service_name: str = "formica"

    # Capacity controller
    capacity_tick_seconds: int = 10
    pending_backpressure: int = 5

    # Pheromone defaults
    min_pheromone: float = 1e-4
    alarm_preempt: float = 0.5
    validated_threshold: float = 0.7
    n_stable_cycles: int = 3

    model_config = {"env_prefix": "FORMICA_", "extra": "ignore"}
