"""Scout caste - decomposes an Objective or SubProblem into new SubProblems."""

from __future__ import annotations

from dataclasses import dataclass

from formica.agents.base import Agent, AgentResult
from formica.blackboard.forum import new_id
from formica.blackboard.models import SubProblem
from formica.pheromones.constants import PheromoneChannel

SCOUT_PROMPT = """You are a Scout of the Formica colony.

Given a parent problem (either an Objective or a SubProblem), produce 2-4 SubProblem
decompositions. Each decomposition should be:
- Specific and actionable by a single Forager in under 2 minutes.
- Non-overlapping with its siblings.
- Phrased as a direct instruction: "Prove X using Y" not "investigate X".

Return JSON: {"subproblems": [{"text": "..."}, ...]}
"""


@dataclass
class Scout(Agent):
    caste: str = "scout"

    def act(self, neighborhood: dict) -> AgentResult:
        focus = neighborhood.get("focus") or {}
        parent_id = focus.get("id")
        parent_text = focus.get("text") or focus.get("objective") or ""
        if not parent_id or not parent_text:
            return AgentResult(action="scout.no-op", notes="no focus")

        # LLM call is optional - a deterministic fallback lets us run without a model
        # (e.g. unit tests, the toy math e2e).
        subproblem_texts = self._decompose(parent_text)

        deposits: list[dict] = []
        last_edge: str | None = None
        for t in subproblem_texts:
            sp = SubProblem(id=new_id("sp"), text=t, parent_id=parent_id)
            edge_id = self.forum.insert_subproblem(sp)
            if edge_id:
                deposits.append(
                    {
                        "edge_id": edge_id,
                        "channel": PheromoneChannel.PROMISING.value,
                        "amount": 0.6,
                    }
                )
                last_edge = edge_id

        return AgentResult(
            action="scout.decomposed",
            wrote_edge_id=last_edge,
            pheromone_deposits=deposits,
            notes=f"created {len(subproblem_texts)} subproblems",
        )

    def _decompose(self, text: str) -> list[str]:
        try:
            from formica.tools.llm import run_json
            resp = run_json(SCOUT_PROMPT, text, config=self.config) or {}
            subs = resp.get("subproblems") or []
            out = [s["text"] for s in subs if isinstance(s, dict) and "text" in s]
            if out:
                return out[:4]
        except Exception:
            pass
        # Fallback: naive decomposition for tests and degraded operation.
        return [
            f"Approach 1: {text}",
            f"Approach 2 (alternative method): {text}",
            f"Approach 3 (cross-check): {text}",
        ]
