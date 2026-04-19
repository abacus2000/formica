"""Numeric-sanity inquiline - checks arithmetic claims in Evidence content."""

from __future__ import annotations

import re
from dataclasses import dataclass

from formica.agents.base import Agent, AgentResult
from formica.blackboard.forum import new_id
from formica.blackboard.models import Validation
from formica.pheromones.constants import PheromoneChannel

# Matches "a + b = c", "a * b = c", "a - b = c", "a / b = c" with ints/floats.
_EQ_RE = re.compile(
    r"(?P<a>-?\d+(?:\.\d+)?)\s*(?P<op>[+\-*/])\s*(?P<b>-?\d+(?:\.\d+)?)\s*=\s*(?P<c>-?\d+(?:\.\d+)?)"
)


def _check(a: float, op: str, b: float, c: float) -> bool:
    try:
        ops = {"+": lambda x, y: x + y, "-": lambda x, y: x - y,
               "*": lambda x, y: x * y, "/": lambda x, y: x / y if y != 0 else float("inf")}
        return abs(ops[op](a, b) - c) < 1e-6 * max(1.0, abs(c))
    except Exception:
        return False


@dataclass
class NumericSanityChecker(Agent):
    caste: str = "inquiline.numeric"

    def act(self, neighborhood: dict) -> AgentResult:
        focus = neighborhood.get("focus") or {}
        content = focus.get("content") or ""
        ev_id = focus.get("id")
        if not ev_id:
            return AgentResult(action="numeric.no-op")
        checks = list(_EQ_RE.finditer(content))
        if not checks:
            return AgentResult(action="numeric.no-op", notes="no arithmetic found")
        bad = []
        for m in checks:
            a, op, b, c = float(m["a"]), m["op"], float(m["b"]), float(m["c"])
            if not _check(a, op, b, c):
                bad.append(m.group(0))
        verdict = "dead_end" if bad else "validated"
        channel = PheromoneChannel.DEAD_END.value if bad else PheromoneChannel.VALIDATED.value
        v = Validation(
            id=new_id("val"),
            evidence_id=ev_id,
            validator_id=self.agent_id,
            validator_kind="numeric",
            verdict=verdict,
            confidence=0.9 if not bad else 0.95,
            note=f"ok={len(checks) - len(bad)} bad={bad}",
        )
        edge = self.forum.insert_validation(v)
        deposits = []
        if edge:
            deposits.append({"edge_id": edge, "channel": channel, "amount": 0.6})
        return AgentResult(
            action=f"numeric.{verdict}",
            wrote_node_id=v.id,
            wrote_edge_id=edge,
            pheromone_deposits=deposits,
            notes=v.note,
            alarm=bool(bad),
        )
