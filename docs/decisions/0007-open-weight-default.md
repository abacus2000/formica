# ADR 0007: Default to open-weight Mistral-7B-AWQ served by local vLLM

- Status: Accepted
- Date: 2026-04-19

## Context

Formica is a long-running multi-agent system that issues many small LLM
calls per objective (one Scout decomposition, one Forager per
sub-problem, one Validator per Evidence, plus inquilines). Routing every
one of those calls through a hosted provider would:

1. Create an unbounded bill that is hard to predict per objective.
2. Couple the system's availability to an external vendor's API.
3. Ship potentially sensitive problem statements off the machine.

The `rome` project solved this by baking `TheBloke/Mistral-7B-Instruct-v0.2-AWQ`
into a GPU AMI (AL2023 + NVIDIA drivers + CUDA + Docker + vLLM image +
weights at `/opt/models/mistral-awq`). That AMI already exists
(`ami-079c82d610e02e480`) and is available for Formica to reuse as-is.

## Decision

Formica defaults to the same open-weight model, served the same way:

- `FormicaConfig.model_base_url` defaults to `http://localhost:8080/v1`.
- `FormicaConfig.model_id` defaults to `TheBloke/Mistral-7B-Instruct-v0.2-AWQ`.
- `FormicaConfig.model_provider` defaults to `openai` (the provider
  protocol, not the vendor — vLLM speaks it natively).
- `deploy/compose/docker-compose.yml` launches Neo4j + vLLM with the
  weights bind-mounted from `/opt/models/mistral-awq:ro`.
- `formica solve --local` runs the Scout/Forager/Validator/GC tick loop
  in-process so a single EC2 box is sufficient for end-to-end testing.

Hosted providers (Bedrock, OpenAI) remain opt-in via
`FORMICA_MODEL_PROVIDER=bedrock` + `FORMICA_MODEL_ID=…`.

## Alternatives considered

- **Default to Bedrock/OpenAI.** Rejected: contradicts the
  open-weight-first posture inherited from `rome`, and makes dev loops
  expensive.
- **Bake a Formica-specific AMI.** Rejected for now: the existing `rome`
  AMI satisfies the requirement and avoids duplicate maintenance. If
  Formica ever needs a different base layer (e.g. a larger model), we
  can fork the AMI and update this ADR.
- **Use Ollama (the pre-change default).** Rejected: Ollama has weaker
  batching and lower throughput than vLLM on the same GPU, and the T4
  is already borderline for Mistral-7B at fp16. AWQ on vLLM gives us
  fp16-equivalent quality at ~4.5 GB.

## Consequences

- A GPU EC2 box launched from `ami-079c82d610e02e480` is the canonical
  dev environment.
- CI still runs without a GPU because:
  - Unit and integration tests use `FakeForum` and never touch the LLM.
  - The e2e toy-math test monkeypatches `Validator._judge` so it also
    doesn't need the model.
- Any call site that wants the LLM must go through
  `formica/tools/llm.py::run_json`, which already honours
  `model_base_url` / `model_provider` so a switch is purely env-driven.
