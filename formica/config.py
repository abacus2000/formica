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
    # Formica defaults to the open-weight model pre-baked into the GPU AMI
    # (shared with the rome project): Mistral-7B-Instruct-v0.2-AWQ, served
    # by vLLM on :8080 with an OpenAI-compatible API. Weights live at
    # /opt/models/mistral-awq on the AMI and are mounted into the vLLM pod
    # read-only so nothing is downloaded at boot. See docs/single-box.md and
    # docs/decisions/0007-open-weight-default.md.
    #
    # The default base_url targets in-cluster DNS (the `vllm` Service in the
    # `formica` namespace). The CLI, when run from outside the cluster,
    # should point to a port-forward: FORMICA_MODEL_BASE_URL=http://localhost:8080/v1
    #
    # To switch to another provider (e.g. Bedrock for prod) override with env:
    #   FORMICA_MODEL_PROVIDER=bedrock FORMICA_MODEL_ID=anthropic.claude-3-...
    model_base_url: str = "http://vllm.formica.svc.cluster.local:8080/v1"
    model_id: str = "TheBloke/Mistral-7B-Instruct-v0.2-AWQ"
    model_provider: str = "openai"  # openai | ollama | bedrock
    # API key for OpenAI-compatible endpoints. Optional for local vLLM (it
    # ignores the value) but required by the underlying `openai.AsyncOpenAI`
    # client, which refuses to initialise without one. Leave empty to use the
    # placeholder "not-needed"; set FORMICA_MODEL_API_KEY for real OpenAI.
    model_api_key: str = ""

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
