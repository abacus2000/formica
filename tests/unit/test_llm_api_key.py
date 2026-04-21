"""Regression test for issue #22 (will be filed): agents silently fell into the
no-LLM fallback because `formica.tools.llm._model` did not pass `api_key` to
strands' OpenAIModel. The underlying `openai.AsyncOpenAI` client refuses to
initialise without one, even when talking to local vLLM, so every agent tick
raised `OpenAIError` inside the swallow-all `try/except` in each caste and
produced deterministic non-LLM output for 238+ validations in a row.
"""

from __future__ import annotations

import os

import pytest

from formica.config import FormicaConfig
from formica.tools import llm as llm_mod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith(("FORMICA_MODEL_", "OPENAI_API_KEY")):
            monkeypatch.delenv(k, raising=False)


def test_model_factory_passes_api_key_when_none_configured():
    """With no FORMICA_MODEL_API_KEY, we must still pass a placeholder so the
    openai client will initialise against local vLLM."""
    cfg = FormicaConfig()
    assert cfg.model_provider == "openai"
    assert cfg.model_api_key == ""

    captured: dict = {}

    class _FakeOpenAIModel:
        def __init__(self, client_args, model_id):
            captured["client_args"] = client_args
            captured["model_id"] = model_id

    import sys
    import types

    fake_module = types.ModuleType("strands.models.openai")
    fake_module.OpenAIModel = _FakeOpenAIModel
    fake_parent = types.ModuleType("strands.models")
    fake_parent.openai = fake_module
    fake_root = sys.modules.get("strands") or types.ModuleType("strands")
    fake_root.models = fake_parent
    sys.modules["strands"] = fake_root
    sys.modules["strands.models"] = fake_parent
    sys.modules["strands.models.openai"] = fake_module

    llm_mod._model(cfg)

    assert "api_key" in captured["client_args"], (
        "api_key must always be present in client_args, otherwise openai.AsyncOpenAI "
        "raises OpenAIError and every agent tick silently falls to its non-LLM fallback."
    )
    assert captured["client_args"]["api_key"], "api_key must be non-empty"
    assert captured["client_args"]["base_url"] == cfg.model_base_url


def test_model_factory_honours_configured_api_key(monkeypatch):
    """When FORMICA_MODEL_API_KEY is set (real OpenAI / Bedrock gateway), use it."""
    monkeypatch.setenv("FORMICA_MODEL_API_KEY", "sk-test-real-key")
    cfg = FormicaConfig()

    captured: dict = {}

    class _FakeOpenAIModel:
        def __init__(self, client_args, model_id):
            captured["client_args"] = client_args

    import sys
    import types

    fake_module = types.ModuleType("strands.models.openai")
    fake_module.OpenAIModel = _FakeOpenAIModel
    fake_parent = types.ModuleType("strands.models")
    fake_parent.openai = fake_module
    fake_root = sys.modules.get("strands") or types.ModuleType("strands")
    fake_root.models = fake_parent
    sys.modules["strands"] = fake_root
    sys.modules["strands.models"] = fake_parent
    sys.modules["strands.models.openai"] = fake_module

    llm_mod._model(cfg)

    assert captured["client_args"]["api_key"] == "sk-test-real-key"
