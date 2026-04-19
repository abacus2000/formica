"""Base Agent class - the tick loop.

Every caste runs: read_local_neighborhood → act → write_back, with OTEL spans
emitted for every step.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field

from formica.blackboard.forum import Forum
from formica.config import FormicaConfig
from formica.telemetry.logs import get_logger
from formica.telemetry.otel import get_tracer

log = get_logger(__name__)


@dataclass
class AgentResult:
    """Return value of an agent's single tick."""

    action: str
    wrote_node_id: str | None = None
    wrote_edge_id: str | None = None
    pheromone_deposits: list[dict] = field(default_factory=list)
    notes: str = ""
    alarm: bool = False


@dataclass(kw_only=True)
class Agent:
    """Abstract base for a caste. Subclasses override `act()`.

    Declared kw_only=True so subclasses can override `caste` with a default
    without breaking field ordering on inheritance.
    """

    agent_id: str
    caste: str
    forum: Forum
    config: FormicaConfig = field(default_factory=FormicaConfig)
    focus_id: str | None = None
    encounters: Counter = field(default_factory=Counter)

    def read(self, radius: int = 2) -> dict:
        focus = self.focus_id
        if focus is None:
            return {"focus": None, "neighbors": [], "edges": []}
        return self.forum.read_neighborhood(focus, radius=radius)

    def act(self, neighborhood: dict) -> AgentResult:
        raise NotImplementedError

    def write(self, result: AgentResult) -> None:
        for dep in result.pheromone_deposits:
            self.forum.deposit(
                edge_id=dep["edge_id"],
                channel=dep["channel"],
                amount=dep["amount"],
                half_life_s=dep.get("half_life_s"),
            )

    def tick(self, radius: int = 2) -> AgentResult:
        tracer = get_tracer(f"formica.agents.{self.caste}")
        with tracer.start_as_current_span(f"{self.caste}.tick") as span:
            span.set_attribute("formica.agent_id", self.agent_id)
            span.set_attribute("formica.caste", self.caste)
            span.set_attribute("formica.focus_id", self.focus_id or "")
            t0 = time.time()
            try:
                neighborhood = self.read(radius=radius)
                result = self.act(neighborhood)
                self.write(result)
                span.set_attribute("formica.action", result.action)
                span.set_attribute("formica.alarm", result.alarm)
                span.set_attribute("formica.tick_seconds", time.time() - t0)
                # Track encounter rates for Gordon's rule reallocation.
                for n in neighborhood.get("neighbors", []):
                    labels = n.get("_labels") or []
                    for lb in labels:
                        self.encounters[lb] += 1
                return result
            except Exception as e:
                log.exception("agent tick failed", extra={"agent_id": self.agent_id, "caste": self.caste})
                span.record_exception(e)
                return AgentResult(action="error", alarm=True, notes=str(e))


def new_agent_id(caste: str) -> str:
    import uuid
    return f"{caste}-{uuid.uuid4().hex[:8]}"
