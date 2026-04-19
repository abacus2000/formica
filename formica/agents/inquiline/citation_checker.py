"""Citation-checker inquiline — runs only on Evidence with `needs-expert` and sources."""

from __future__ import annotations

import re
from dataclasses import dataclass

from formica.agents.base import Agent, AgentResult
from formica.blackboard.forum import new_id
from formica.blackboard.models import Validation
from formica.pheromones.constants import PheromoneChannel

_URL_RE = re.compile(r"https?://\S+")


@dataclass
class CitationChecker(Agent):
    caste: str = "inquiline.citation"

    def act(self, neighborhood: dict) -> AgentResult:
        focus = neighborhood.get("focus") or {}
        if not focus or not focus.get("sources"):
            return AgentResult(action="citation.no-op", notes="no sources to check")

        ev_id = focus["id"]
        bad: list[str] = []
        good: list[str] = []
        try:
            import httpx

            for src in focus["sources"]:
                m = _URL_RE.search(str(src))
                if not m:
                    bad.append(src)
                    continue
                url = m.group(0)
                try:
                    r = httpx.head(url, timeout=5, follow_redirects=True)
                    (good if 200 <= r.status_code < 400 else bad).append(url)
                except Exception:
                    bad.append(url)
        except Exception:
            return AgentResult(action="citation.skip", notes="httpx unavailable")

        if not good and bad:
            verdict, channel = "dead_end", PheromoneChannel.DEAD_END.value
        elif bad:
            verdict, channel = "needs_expert", PheromoneChannel.RISKY.value
        else:
            verdict, channel = "validated", PheromoneChannel.VALIDATED.value

        v = Validation(
            id=new_id("val"),
            evidence_id=ev_id,
            validator_id=self.agent_id,
            validator_kind="citation",
            verdict=verdict,
            confidence=0.8 if verdict == "validated" else 0.6,
            note=f"good={len(good)} bad={len(bad)}",
        )
        edge = self.forum.insert_validation(v)
        deposits = []
        if edge:
            deposits.append({"edge_id": edge, "channel": channel, "amount": 0.5})
        return AgentResult(
            action=f"citation.{verdict}",
            wrote_node_id=v.id,
            wrote_edge_id=edge,
            pheromone_deposits=deposits,
            notes=v.note,
        )
