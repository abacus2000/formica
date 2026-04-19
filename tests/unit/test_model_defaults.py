"""Guardrail: the default FormicaConfig must target the open-weight GPU AMI.

Per ADR-0007, Formica defaults to Mistral-7B-AWQ served by local vLLM on
port 8080. If these tests fail, either the default was changed on purpose
(update ADR-0007 and these tests) or by accident (revert).
"""

from __future__ import annotations

import os

import pytest

from formica.config import FormicaConfig


# pydantic-settings reads env vars at instantiation; make sure leftover
# FORMICA_MODEL_* from the runner's environment don't mask the defaults.
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith("FORMICA_MODEL_"):
            monkeypatch.delenv(k, raising=False)


def test_default_model_is_mistral_awq():
    cfg = FormicaConfig()
    assert cfg.model_id == "TheBloke/Mistral-7B-Instruct-v0.2-AWQ"


def test_default_model_base_url_targets_local_vllm():
    cfg = FormicaConfig()
    assert cfg.model_base_url == "http://localhost:8080/v1"


def test_default_model_provider_speaks_openai_protocol():
    # vLLM exposes an OpenAI-compatible API, so provider stays 'openai'.
    cfg = FormicaConfig()
    assert cfg.model_provider == "openai"


def test_env_override_works(monkeypatch):
    monkeypatch.setenv("FORMICA_MODEL_PROVIDER", "bedrock")
    monkeypatch.setenv("FORMICA_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
    cfg = FormicaConfig()
    assert cfg.model_provider == "bedrock"
    assert cfg.model_id.startswith("anthropic.claude")
