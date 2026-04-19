"""Garbage collector caste (Lustrum) - necrophoresis.

Prunes nodes whose aggregate pheromone mass is below a floor, after their last
update is older than a grace period.
"""

from __future__ import annotations

from dataclasses import dataclass

from formica.agents.base import Agent, AgentResult


@dataclass
class GarbageCollector(Agent):
    caste: str = "gc"
    floor: float = 1e-3

    def act(self, neighborhood: dict) -> AgentResult:
        deleted = self.forum.prune_dead(pheromone_floor=self.floor)
        return AgentResult(
            action="gc.prune",
            notes=f"pruned {deleted} nodes",
        )
