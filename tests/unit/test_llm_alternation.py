"""Regression test for the second LLM blocker (follow-up to issue #22):

Mistral-Instruct (and other models that use the 'user/assistant' alternating
chat template) reject requests that contain a separate 'system' role with::

    400 Bad Request: 'Conversation roles must alternate user/assistant/...'

Previously, `formica.tools.llm.run_json` passed the prompt via
`Agent(system_prompt=...)`. This test pins the contract: the system prompt
must be folded into the first user message so the wire-level conversation has
no standalone system role, keeping the client portable across models.
"""

from __future__ import annotations

from typing import Any

from formica.config import FormicaConfig
from formica.tools import llm as llm_mod


def _install_fake_agent(monkeypatch) -> dict[str, Any]:
    """Patch strands.Agent with a recorder. Returns a dict populated on call."""
    captured: dict[str, Any] = {"init_kwargs": None, "inputs": []}

    class _FakeAgent:
        def __init__(self, **kwargs):
            captured["init_kwargs"] = kwargs

        def __call__(self, text):
            captured["inputs"].append(text)
            return '{"ok": true}'

    import sys
    import types

    fake_root = sys.modules.get("strands") or types.ModuleType("strands")
    fake_root.Agent = _FakeAgent
    sys.modules["strands"] = fake_root

    # Also stub the model factory so we do not try to build a real OpenAIModel.
    monkeypatch.setattr(llm_mod, "_model", lambda cfg: object())
    return captured


def test_system_prompt_is_merged_into_user_message(monkeypatch):
    captured = _install_fake_agent(monkeypatch)

    cfg = FormicaConfig()
    result = llm_mod.run_json(
        system_prompt="You are a validator. Return JSON only.",
        input_text="Evidence: sqrt(2) is irrational.",
        config=cfg,
    )

    assert result == {"ok": True}
    init_kwargs = captured["init_kwargs"]
    assert init_kwargs is not None, "Agent was never constructed"
    # The critical assertion: we must NOT pass system_prompt, because Mistral
    # (and other strict chat-template models) reject a standalone system role.
    assert "system_prompt" not in init_kwargs or init_kwargs["system_prompt"] is None, (
        "run_json must not pass system_prompt to strands.Agent; some models "
        "(e.g. Mistral-Instruct) reject a standalone system role with HTTP 400 "
        "'Conversation roles must alternate user/assistant/...'."
    )
    # And the system text must still be delivered - folded into the first user msg.
    first_user = captured["inputs"][0]
    assert "You are a validator" in first_user
    assert "Evidence: sqrt(2) is irrational." in first_user


def test_empty_system_prompt_passes_input_unchanged(monkeypatch):
    captured = _install_fake_agent(monkeypatch)

    cfg = FormicaConfig()
    llm_mod.run_json(system_prompt="", input_text="raw input", config=cfg)

    assert captured["inputs"][0] == "raw input"
