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
        # The underlying `openai.AsyncOpenAI` client refuses to start without
        # an api_key, even when talking to a local vLLM server that ignores it.
        # We therefore always pass a key: either the configured one (for real
        # OpenAI) or a harmless placeholder (for vLLM / any OpenAI-compatible
        # local server). Without this, every agent tick silently fell into the
        # `no LLM` fallback path and produced naive non-LLM results.
        client_args: dict[str, Any] = {
            "base_url": cfg.model_base_url,
            "api_key": cfg.model_api_key or "not-needed",
        }
        return OpenAIModel(
            client_args=client_args,
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
        log.warning("strands unavailable, caller should use fallback")
        return None

    try:
        agent = Agent(model=_model(cfg), system_prompt=system_prompt, tools=tools or [])
        out = str(agent(input_text))
    except Exception as e:
        # The fallback paths that call this function swallow their own
        # exceptions, so log loudly here to make silent LLM outages visible
        # (e.g. missing api_key, DNS resolution, vLLM down).
        log.warning("LLM call failed: %s: %s", type(e).__name__, e)
        return None
    start = out.find("{")
    end = out.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(out[start:end])
        except Exception:
            pass
    # Followup asking strictly for JSON.
    try:
        out2 = str(agent("Respond with ONLY a JSON object this time. No prose."))
    except Exception as e:
        log.warning("LLM followup call failed: %s: %s", type(e).__name__, e)
        return None
    s2 = out2.find("{")
    e2 = out2.rfind("}") + 1
    if s2 >= 0 and e2 > s2:
        try:
            return json.loads(out2[s2:e2])
        except Exception:
            return None
    return None
