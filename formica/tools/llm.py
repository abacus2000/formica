"""Strands agent wrapper used by castes - returns parsed JSON."""

from __future__ import annotations

import json
import logging
from typing import Any

from formica.config import FormicaConfig

log = logging.getLogger(__name__)


def _model(cfg: FormicaConfig):
    if cfg.model_provider in ("openai", "vllm"):
        from strands.models.openai import OpenAIModel
        return OpenAIModel(
            client_args={"base_url": cfg.model_base_url},
            model_id=cfg.model_id,
        )
    if cfg.model_provider == "ollama":
        from strands.models.ollama import OllamaModel
        host = cfg.model_base_url.replace("/v1", "").rstrip("/")
        return OllamaModel(host=host, model_id=cfg.model_id)
    if cfg.model_provider == "bedrock":
        from strands.models.bedrock import BedrockModel
        return BedrockModel(model_id=cfg.model_id)
    raise ValueError(f"unknown model provider: {cfg.model_provider}")


def run_json(
    system_prompt: str,
    input_text: str,
    config: FormicaConfig | None = None,
    tools: list | None = None,
) -> dict[str, Any] | None:
    """Call the LLM, parse first JSON object in response, return dict or None."""
    cfg = config or FormicaConfig()
    try:
        from strands import Agent  # type: ignore
    except Exception:
        log.debug("strands unavailable, caller should use fallback")
        return None

    agent = Agent(model=_model(cfg), system_prompt=system_prompt, tools=tools or [])
    out = str(agent(input_text))
    start = out.find("{")
    end = out.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(out[start:end])
        except Exception:
            pass
    # Followup asking strictly for JSON.
    out2 = str(agent("Respond with ONLY a JSON object this time. No prose."))
    s2 = out2.find("{")
    e2 = out2.rfind("}") + 1
    if s2 >= 0 and e2 > s2:
        try:
            return json.loads(out2[s2:e2])
        except Exception:
            return None
    return None
