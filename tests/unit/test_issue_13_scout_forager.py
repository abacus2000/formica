"""Regression tests for issue #13: scout re-decomposes leaves, forager no-ops on valid leaf.

These tests pin down the two symptoms observed on the k3s cluster:

1. Scout decomposes SubProblems that already have children, producing nested
   "Approach N: Approach N: ..." chains up to 6 levels deep.
2. Forager always returns `forager.no-op` even when handed a valid leaf
   SubProblem as its focus, because `read_neighborhood` does not populate
   `_labels` on the returned node dicts, so `_has_label` is never True.

Both tests are written against an in-memory Forum stub that mimics the
real `read_neighborhood` contract. No Neo4j, no LLM, no k3s.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from formica.agents.forager import Forager
from formica.agents.scout import Scout
from formica.blackboard.forum import Forum
from formica.config import FormicaConfig


@dataclass
class FakeNode:
    id: str
    labels: list[str]
    props: dict = field(default_factory=dict)


@dataclass
class FakeEdge:
    id: str
    type: str
    start: str
    end: str
    pheromones: list = field(default_factory=list)


class FakeForum(Forum):
    """In-memory Forum that mirrors the real contract for read_neighborhood
    and captures writes (insert_subproblem / insert_evidence) so tests can
    inspect side effects without Neo4j."""

    def __init__(self):
        # Skip parent __init__ (no Neo4j driver)
        self.config = FormicaConfig()
        self._driver = None
        self.nodes: dict[str, FakeNode] = {}
        self.edges: list[FakeEdge] = []
        self.inserted_subproblems: list = []
        self.inserted_evidence: list = []
        self.deposits: list[dict] = []

    # --- test helpers ---

    def add_node(self, node_id: str, labels: list[str], **props) -> None:
        self.nodes[node_id] = FakeNode(id=node_id, labels=labels, props={"id": node_id, **props})

    def add_edge(self, edge_id: str, type_: str, start: str, end: str) -> None:
        self.edges.append(FakeEdge(id=edge_id, type=type_, start=start, end=end))

    def is_leaf_subproblem(self, sp_id: str) -> bool:
        """A SubProblem is a leaf if no other SubProblem has it as parent
        (no incoming CHILD_OF from another SubProblem)."""
        for e in self.edges:
            if e.type == "CHILD_OF" and e.end == sp_id:
                child = self.nodes.get(e.start)
                if child and "SubProblem" in child.labels:
                    return False
        return True

    # --- Forum contract used by agents ---

    def read_neighborhood(self, focus_id: str, radius: int = 2) -> dict:
        focus = self.nodes.get(focus_id)
        if focus is None:
            return {"focus": None, "neighbors": [], "edges": []}

        # BFS within `radius` hops.
        visited = {focus_id}
        frontier = {focus_id}
        for _ in range(radius):
            next_frontier = set()
            for node_id in frontier:
                for e in self.edges:
                    for other in (e.start, e.end):
                        if node_id in (e.start, e.end) and other not in visited:
                            visited.add(other)
                            next_frontier.add(other)
            frontier = next_frontier

        neighbor_ids = visited - {focus_id}
        neighbors = []
        for nid in neighbor_ids:
            n = self.nodes.get(nid)
            if n is None:
                continue
            d = dict(n.props)
            # Contract: include labels so agents can filter by type.
            d["_labels"] = list(n.labels)
            neighbors.append(d)

        edges = [
            {
                "id": e.id,
                "type": e.type,
                "start": e.start,
                "end": e.end,
                "pheromones": list(e.pheromones),
            }
            for e in self.edges
            if e.start in visited and e.end in visited
        ]

        focus_dict = dict(focus.props)
        focus_dict["_labels"] = list(focus.labels)
        return {"focus": focus_dict, "neighbors": neighbors, "edges": edges}

    def insert_subproblem(self, sp) -> str:
        self.inserted_subproblems.append(sp)
        eid = f"edge-{len(self.edges)}"
        self.add_edge(eid, "CHILD_OF", sp.id, sp.parent_id)
        self.add_node(sp.id, ["SubProblem"], text=sp.text, parent_id=sp.parent_id)
        return eid

    def insert_evidence(self, ev) -> str:
        self.inserted_evidence.append(ev)
        eid = f"edge-{len(self.edges)}"
        self.add_edge(eid, "SUPPORTS", ev.id, ev.subproblem_id)
        self.add_node(ev.id, ["Evidence"], content=ev.content)
        return eid

    def deposit(self, edge_id, channel, amount, half_life_s=None):
        self.deposits.append(
            {"edge_id": edge_id, "channel": channel, "amount": amount}
        )


# ---------------------------------------------------------------------------
# BUG 1: Scout re-decomposes SubProblems that already have children.
# ---------------------------------------------------------------------------


def test_scout_does_not_redecompose_internal_subproblem():
    """A SubProblem that already has children should not be decomposed again.

    This test reproduces the nesting bug where the scout repeatedly expands
    already-expanded nodes, producing "Approach 3: Approach 3: ..." chains.
    """
    forum = FakeForum()
    # Graph: Objective -> SubProblem(already decomposed) -> 3 leaf SubProblems
    forum.add_node("obj-1", ["Objective"], objective="Prove sqrt(2) is irrational")
    forum.add_node("sp-parent", ["SubProblem"], text="Approach 1: Prove sqrt(2) is irrational", parent_id="obj-1")
    forum.add_edge("e0", "CHILD_OF", "sp-parent", "obj-1")
    for i in range(3):
        sid = f"sp-leaf-{i}"
        forum.add_node(sid, ["SubProblem"], text=f"Leaf {i}", parent_id="sp-parent")
        forum.add_edge(f"e{i+1}", "CHILD_OF", sid, "sp-parent")

    assert not forum.is_leaf_subproblem("sp-parent"), "test fixture sanity: parent is internal"
    assert forum.is_leaf_subproblem("sp-leaf-0"), "test fixture sanity: sp-leaf-0 is a leaf"

    scout = Scout(agent_id="scout-test", caste="scout", forum=forum, focus_id="sp-parent")
    result = scout.tick()

    assert result.action == "scout.no-op", (
        f"scout should skip internal SubProblems but returned action={result.action!r}. "
        f"This means scout created {len(forum.inserted_subproblems)} new children on "
        f"'sp-parent' despite it already having 3 children."
    )
    assert forum.inserted_subproblems == [], (
        f"scout inserted {len(forum.inserted_subproblems)} subproblems under an "
        f"already-decomposed parent (issue #13 nesting bug)."
    )


def test_scout_still_decomposes_leaf_subproblem():
    """Sanity counterpart: scout SHOULD decompose a leaf SubProblem."""
    forum = FakeForum()
    forum.add_node("obj-1", ["Objective"], objective="Prove sqrt(2) is irrational")
    forum.add_node("sp-leaf", ["SubProblem"], text="Show sqrt(2)=a/b leads to contradiction", parent_id="obj-1")
    forum.add_edge("e0", "CHILD_OF", "sp-leaf", "obj-1")

    scout = Scout(agent_id="scout-test", caste="scout", forum=forum, focus_id="sp-leaf")
    result = scout.tick()

    assert result.action == "scout.decomposed", (
        f"scout should decompose leaf subproblems but returned action={result.action!r}"
    )
    assert len(forum.inserted_subproblems) >= 2, "scout should create at least 2 children on a leaf"


def test_scout_decomposes_objective_with_no_children():
    """Objectives are always valid decomposition targets (they have no CHILD_OF-from-SubProblem edges)."""
    forum = FakeForum()
    forum.add_node("obj-1", ["Objective"], objective="Prove sqrt(2) is irrational")

    scout = Scout(agent_id="scout-test", caste="scout", forum=forum, focus_id="obj-1")
    result = scout.tick()

    assert result.action == "scout.decomposed"
    assert len(forum.inserted_subproblems) >= 2


# ---------------------------------------------------------------------------
# BUG 2: Forager returns no-op on a valid leaf SubProblem focus.
# ---------------------------------------------------------------------------


def test_forager_produces_evidence_for_leaf_subproblem_focus():
    """When the forager is focused directly on a leaf SubProblem, it must
    produce Evidence. Today it always returns forager.no-op because
    Forum.read_neighborhood does not populate _labels on the focus node,
    making `_has_label(focus, 'SubProblem')` always False.
    """
    forum = FakeForum()
    forum.add_node("obj-1", ["Objective"], objective="Prove sqrt(2) is irrational")
    forum.add_node(
        "sp-leaf",
        ["SubProblem"],
        text="Show sqrt(2)=a/b in lowest terms leads to a,b both even",
        parent_id="obj-1",
    )
    forum.add_edge("e0", "CHILD_OF", "sp-leaf", "obj-1")

    forager = Forager(agent_id="forager-test", caste="forager", forum=forum, focus_id="sp-leaf")
    result = forager.tick()

    assert result.action == "forager.evidence", (
        f"forager should produce evidence for a leaf SubProblem focus but returned "
        f"action={result.action!r} (issue #13 no-op bug)."
    )
    assert len(forum.inserted_evidence) == 1, "forager must insert exactly one Evidence node"


def test_forager_produces_evidence_when_subproblems_are_neighbors():
    """When focus is an Objective and SubProblems are neighbors, forager should
    pick one and produce Evidence."""
    forum = FakeForum()
    forum.add_node("obj-1", ["Objective"], objective="Prove sqrt(2) is irrational")
    for i in range(3):
        sid = f"sp-{i}"
        forum.add_node(sid, ["SubProblem"], text=f"approach {i}", parent_id="obj-1")
        forum.add_edge(f"e{i}", "CHILD_OF", sid, "obj-1")

    forager = Forager(agent_id="forager-test", caste="forager", forum=forum, focus_id="obj-1")
    result = forager.tick()

    assert result.action == "forager.evidence", (
        f"forager should produce evidence when SubProblems are in-neighborhood but "
        f"returned action={result.action!r}."
    )
    assert len(forum.inserted_evidence) == 1


def test_forager_no_op_when_no_subproblems_anywhere():
    """Sanity counterpart: legitimately no-op when there are no SubProblems at all."""
    forum = FakeForum()
    forum.add_node("obj-1", ["Objective"], objective="Prove sqrt(2) is irrational")

    forager = Forager(agent_id="forager-test", caste="forager", forum=forum, focus_id="obj-1")
    result = forager.tick()

    assert result.action == "forager.no-op"
    assert forum.inserted_evidence == []


# ---------------------------------------------------------------------------
# BUG 2b: Forum._node_to_dict contract - labels must round-trip.
#
# The forager no-op in production traced back to Forum.read_neighborhood
# flattening neo4j nodes with dict(node), which drops labels. Guards the
# fix by calling the real helper against a fake neo4j Node.
# ---------------------------------------------------------------------------


class _FakeNeoNode:
    """Mimics neo4j.graph.Node for the label/property flattening contract.

    - dict(node) iterates (key, value) pairs (properties only)
    - node.labels is a frozenset of labels
    """

    def __init__(self, labels: list[str], **props):
        self._props = dict(props)
        self.labels = frozenset(labels)

    def keys(self):
        return self._props.keys()

    def __iter__(self):
        return iter(self._props)

    def __getitem__(self, key):
        return self._props[key]


def test_node_to_dict_preserves_labels():
    from formica.blackboard.forum import _node_to_dict

    node = _FakeNeoNode(["SubProblem"], id="sp-1", text="leaf problem", parent_id="obj-1")
    d = _node_to_dict(node)

    assert d["id"] == "sp-1"
    assert d["text"] == "leaf problem"
    assert "_labels" in d, "Forum must surface neo4j labels under _labels"
    assert "SubProblem" in d["_labels"]


def test_node_to_dict_handles_plain_dict_defensively():
    """Helper should not crash when handed a plain dict (e.g. from a test fake)."""
    from formica.blackboard.forum import _node_to_dict

    d = _node_to_dict({"id": "x", "foo": "bar"})
    assert d["id"] == "x"
    assert d["foo"] == "bar"
    # No _labels key required; just must not raise.
