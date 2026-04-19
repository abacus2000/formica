"""Validator caste (Censors) — verify Evidence nodes."""

from __future__ import annotations

from dataclasses import dataclass

from formica.agents.base import Agent, AgentResult
from formica.blackboard.forum import new_id
from formica.blackboard.models import Validation
from formica.pheromones.constants import PheromoneChannel

VALIDATOR_KINDS = ("unit_test", "consistency", "citation", "numeric")

VALIDATOR_PROMPT = """You are a Validator of the Formica colony.

Given a piece of Evidence, return a verdict.

- "validated" if the evidence is correct, internally consistent, and (when sources are provided) the sources support the claim.
- "dead_end" if the evidence contains an error, contradiction, or unsupported claim.
- "needs_expert" if you cannot tell without a specialist.

Respond as JSON: {"verdict": "validated|dead_end|needs_expert", "confidence": 0.0-1.0, "note": "..."}.
"""


@dataclass
class Validator(Agent):
    caste: str = "validator"
    kind: str = "consistency"

    def act(self, neighborhood: dict) -> AgentResult:
        # Focus is an Evidence node; neighbors include its SupporT edge.
        focus = neighborhood.get("focus") or {}
        ev_id = focus.get("id")
        ev_content = focus.get("content")
        if not ev_id or ev_content is None:
            return AgentResult(action="validator.no-op", notes="no evidence in focus")

        verdict, confidence, note = self._judge(ev_content, focus.get("sources") or [])

        v = Validation(
            id=new_id("val"),
            evidence_id=ev_id,
            validator_id=self.agent_id,
            validator_kind=self.kind,
            verdict=verdict,
            confidence=float(confidence),
            note=note,
        )
        val_edge = self.forum.insert_validation(v)

        # Also deposit on the evidence's SUPPORTS edge so foragers see the verdict.
        supports_edges = [
            e
            for e in neighborhood.get("edges") or []
            if e.get("type") == "SUPPORTS" and e.get("start") == ev_id
        ]
        deposits: list[dict] = []
        if val_edge:
            # On the Validation→Evidence edge, mark validated/dead-end directly.
            channel = {
                "validated": PheromoneChannel.VALIDATED.value,
                "dead_end": PheromoneChannel.DEAD_END.value,
                "needs_expert": PheromoneChannel.NEEDS_EXPERT.value,
            }.get(verdict, PheromoneChannel.RISKY.value)
            deposits.append({"edge_id": val_edge, "channel": channel, "amount": confidence})

        for e in supports_edges:
            if verdict == "validated":
                deposits.append(
                    {
                        "edge_id": e["id"],
                        "channel": PheromoneChannel.VALIDATED.value,
                        "amount": confidence,
                    }
                )
            elif verdict == "dead_end":
                deposits.append(
                    {
                        "edge_id": e["id"],
                        "channel": PheromoneChannel.DEAD_END.value,
                        "amount": confidence,
                    }
                )

        alarm = verdict == "dead_end" and confidence >= 0.9
        return AgentResult(
            action=f"validator.{verdict}",
            wrote_node_id=v.id,
            wrote_edge_id=val_edge or None,
            pheromone_deposits=deposits,
            notes=note,
            alarm=alarm,
        )

    def _judge(self, content: str, sources: list[str]) -> tuple[str, float, str]:
        try:
            from formica.tools.llm import run_json
            resp = run_json(
                VALIDATOR_PROMPT,
                f"Evidence: {content}\nSources: {sources}",
                config=self.config,
            ) or {}
            verdict = str(resp.get("verdict", "needs_expert"))
            if verdict not in ("validated", "dead_end", "needs_expert"):
                verdict = "needs_expert"
            return verdict, float(resp.get("confidence", 0.5)), str(resp.get("note", ""))
        except Exception:
            # Fallback: mark as needs_expert so an inquiline can re-judge.
            return "needs_expert", 0.5, "fallback: no LLM"
