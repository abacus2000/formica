"""Tick loop integration: scouts → foragers → validators, against an in-memory
fake of the Forum. We exercise the agent code paths without Neo4j.
"""

from __future__ import annotations

import uuid


from formica.agents.forager import Forager
from formica.agents.inquiline.numeric_sanity import NumericSanityChecker
from formica.agents.scout import Scout
from formica.blackboard.models import Evidence, SubProblem, Validation
from formica.config import FormicaConfig


class FakeForum:
    """In-memory Forum — enough of the API for the tick loop."""

    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}
        self.deposits: list[dict] = []

    def _eid(self) -> str:
        return f"e-{uuid.uuid4().hex[:8]}"

    def insert_subproblem(self, sp: SubProblem) -> str:
        self.nodes[sp.id] = {"_labels": ["SubProblem"], **sp.model_dump()}
        eid = self._eid()
        self.edges[eid] = {"id": eid, "type": "CHILD_OF",
                           "start": sp.id, "end": sp.parent_id, "pheromones": []}
        return eid

    def insert_evidence(self, ev: Evidence) -> str:
        self.nodes[ev.id] = {"_labels": ["Evidence"], **ev.model_dump()}
        eid = self._eid()
        self.edges[eid] = {"id": eid, "type": "SUPPORTS",
                           "start": ev.id, "end": ev.subproblem_id, "pheromones": []}
        return eid

    def insert_validation(self, v: Validation) -> str:
        self.nodes[v.id] = {"_labels": ["Validation"], **v.model_dump()}
        eid = self._eid()
        self.edges[eid] = {"id": eid, "type": "VERDICTS",
                           "start": v.id, "end": v.evidence_id, "pheromones": []}
        return eid

    def deposit(self, edge_id, channel, amount, half_life_s=None):
        self.deposits.append({"edge_id": edge_id, "channel": channel, "amount": amount})
        edge = self.edges[edge_id]
        edge["pheromones"].append({"channel": channel, "value": amount})

    def read_neighborhood(self, focus_id, radius=2):
        focus = self.nodes.get(focus_id)
        edges = [e for e in self.edges.values() if e["start"] == focus_id or e["end"] == focus_id]
        neighbor_ids = {e["start"] for e in edges} | {e["end"] for e in edges}
        neighbors = [self.nodes[nid] for nid in neighbor_ids if nid in self.nodes and nid != focus_id]
        return {"focus": focus, "neighbors": neighbors, "edges": edges}


def _seed_objective(forum: FakeForum) -> str:
    oid = "obj-1"
    forum.nodes[oid] = {"_labels": ["Objective"], "id": oid,
                        "text": "Prove sqrt(2) is irrational", "run_id": "r1"}
    return oid


def test_scout_creates_subproblems(monkeypatch):
    forum = FakeForum()
    oid = _seed_objective(forum)
    # Force the deterministic fallback (no LLM available in CI).
    scout = Scout(agent_id="scout-1", caste="scout", forum=forum,
                  config=FormicaConfig(), focus_id=oid)
    res = scout.tick()
    assert res.action == "scout.decomposed"
    sps = [n for n in forum.nodes.values() if "SubProblem" in n["_labels"]]
    assert len(sps) >= 2


def test_forager_writes_evidence_on_a_subproblem():
    forum = FakeForum()
    oid = _seed_objective(forum)
    # Plant a subproblem.
    sp = SubProblem(id="sp-1", text="Assume sqrt(2)=p/q in lowest terms", parent_id=oid)
    forum.insert_subproblem(sp)
    # Forager focuses on the subproblem.
    f = Forager(agent_id="f-1", caste="forager", forum=forum,
                config=FormicaConfig(), focus_id=sp.id)
    res = f.tick()
    assert res.action == "forager.evidence"
    evs = [n for n in forum.nodes.values() if "Evidence" in n["_labels"]]
    assert len(evs) == 1


def test_numeric_inquiline_flags_bad_arithmetic():
    forum = FakeForum()
    sp_id = "sp-x"
    forum.nodes[sp_id] = {"_labels": ["SubProblem"], "id": sp_id, "text": "x"}
    ev = Evidence(id="ev-bad", subproblem_id=sp_id,
                  content="since 2 + 2 = 5, qed", agent_id="f-x")
    forum.insert_evidence(ev)

    ins = NumericSanityChecker(agent_id="iq-1", caste="inquiline.numeric",
                               forum=forum, config=FormicaConfig(),
                               focus_id=ev.id)
    res = ins.tick()
    assert res.action == "numeric.dead_end"
    assert res.alarm is True
