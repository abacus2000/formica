"""End-to-end style test - drives a toy math problem through the tick loop
against the in-memory FakeForum. Verifies that:

  1. Scouts decompose the objective.
  2. Foragers produce evidence.
  3. Validators deposit `validated` pheromone above threshold.
  4. The CLI-equivalent loop would see N stable validated evidence nodes.

This avoids the need for a live Neo4j while exercising the agent code.
"""

from __future__ import annotations


from formica.agents.forager import Forager
from formica.agents.scout import Scout
from formica.agents.validator import Validator
from formica.config import FormicaConfig
from tests.integration.test_tick_loop import FakeForum


def test_toy_math_converges(monkeypatch):
    forum = FakeForum()
    # Objective.
    oid = "obj-math"
    forum.nodes[oid] = {"_labels": ["Objective"], "id": oid,
                        "text": "Prove sqrt(2) is irrational", "run_id": "r-math"}

    # 1) Scout decomposes.
    Scout(agent_id="s", caste="scout", forum=forum,
          config=FormicaConfig(), focus_id=oid).tick()
    subs = [n for n in forum.nodes.values() if "SubProblem" in n["_labels"]]
    assert len(subs) >= 2

    # 2) Forager produces evidence for each subproblem.
    for sp in subs:
        Forager(agent_id="f-" + sp["id"], caste="forager", forum=forum,
                config=FormicaConfig(), focus_id=sp["id"]).tick()
    evs = [n for n in forum.nodes.values() if "Evidence" in n["_labels"]]
    assert len(evs) == len(subs)

    # 3) Validator verdicts - force `validated` by monkeypatching _judge.
    def _always_validate(self, content, sources):
        return "validated", 0.95, "forced-pass for test"

    monkeypatch.setattr(Validator, "_judge", _always_validate, raising=True)
    for ev in evs:
        Validator(agent_id="v-" + ev["id"], caste="validator",
                  forum=forum, config=FormicaConfig(),
                  focus_id=ev["id"]).tick()

    # 4) Check validated pheromone deposits exist on SUPPORTS edges.
    supports_validated = [
        e for e in forum.edges.values()
        if e["type"] == "SUPPORTS"
        and any(p["channel"] == "validated" and p["value"] >= 0.7 for p in e["pheromones"])
    ]
    assert len(supports_validated) == len(evs)
