"""Forager caste — picks a SubProblem by gradient, produces Evidence."""

from __future__ import annotations

from dataclasses import dataclass

from formica.agents.base import Agent, AgentResult
from formica.blackboard.forum import new_id
from formica.blackboard.models import Evidence
from formica.pheromones.constants import PheromoneChannel
from formica.pheromones.sampler import gradient_weights, softmax_sample

FORAGER_PROMPT = """You are a Forager of the Formica colony.

Given a sub-problem, produce one piece of Evidence toward solving it. Evidence can be:
- A direct calculation (show the work).
- A cited fact (include the URL or source).
- A logical argument (state premises and conclusion).

Respond as JSON: {"content": "...", "sources": ["..."]}. Keep content under 400 words.
"""


@dataclass
class Forager(Agent):
    caste: str = "forager"

    def act(self, neighborhood: dict) -> AgentResult:
        # The Forager can be focused on either (a) a parent node whose neighbors
        # contain candidate SubProblems (then we softmax-sample by gradient), or
        # (b) a SubProblem directly (then we just produce Evidence for it).
        edges = neighborhood.get("edges") or []
        focus = neighborhood.get("focus") or {}
        neighbor_sps = [
            n for n in neighborhood.get("neighbors", []) if _has_label(n, "SubProblem")
        ]
        if _has_label(focus, "SubProblem"):
            sp_candidates = [focus]
        else:
            sp_candidates = neighbor_sps
        if not sp_candidates:
            return AgentResult(action="forager.no-op", notes="no subproblems in view")

        # Pair edges to subproblems where possible; otherwise uniform over subproblems.
        sp_ids = {n["id"] for n in sp_candidates}
        linked_edges = [e for e in edges if e.get("end") in sp_ids or e.get("start") in sp_ids]
        if linked_edges:
            weights = gradient_weights(linked_edges)
            idx = softmax_sample(weights)
            if idx < 0:
                idx = 0
            chosen = linked_edges[idx]
            chosen_sp_id = chosen.get("end") if chosen.get("end") in sp_ids else chosen.get("start")
        else:
            chosen_sp_id = sp_candidates[0]["id"]

        sp_node = next((n for n in sp_candidates if n["id"] == chosen_sp_id), None)
        if sp_node is None:
            return AgentResult(action="forager.no-op", notes="chosen subproblem missing")

        content, sources = self._research(sp_node.get("text", ""))
        ev = Evidence(
            id=new_id("ev"),
            subproblem_id=chosen_sp_id,
            content=content,
            agent_id=self.agent_id,
            sources=sources,
        )
        edge_id = self.forum.insert_evidence(ev)
        deposits: list[dict] = []
        if edge_id:
            deposits.append(
                {
                    "edge_id": edge_id,
                    "channel": PheromoneChannel.PROMISING.value,
                    "amount": 0.4,
                }
            )
            if sources:
                # Evidence with sources gets a secondary `needs-expert` tap for the
                # citation-checker inquiline.
                deposits.append(
                    {
                        "edge_id": edge_id,
                        "channel": PheromoneChannel.NEEDS_EXPERT.value,
                        "amount": 0.3,
                    }
                )
        return AgentResult(
            action="forager.evidence",
            wrote_node_id=ev.id,
            wrote_edge_id=edge_id or None,
            pheromone_deposits=deposits,
            notes=f"evidence for {chosen_sp_id}",
        )

    def _research(self, task_text: str) -> tuple[str, list[str]]:
        try:
            from formica.tools.llm import run_json
            from formica.tools.web import web_search, web_fetch
            resp = run_json(
                FORAGER_PROMPT,
                f"Sub-problem: {task_text}",
                config=self.config,
                tools=[web_search, web_fetch],
            ) or {}
            return (resp.get("content") or "").strip(), list(resp.get("sources") or [])
        except Exception:
            # Deterministic fallback for tests.
            return (f"Observation: {task_text} — preliminary analysis.", [])


def _has_label(node: dict, label: str) -> bool:
    labels = node.get("_labels") or []
    return label in labels or label.lower() in [str(x).lower() for x in labels]
