"""Phase cycling: exploration ↔ consolidation with hysteresis.

Driven by global pheromone entropy. When entropy is high (diffuse knowledge), the
colony should explore; when entropy is low (concentrated trails), consolidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Phase(str, Enum):
    EXPLORATION = "exploration"
    CONSOLIDATION = "consolidation"


@dataclass
class PhaseState:
    phase: Phase = Phase.EXPLORATION
    low_threshold: float = 1.2   # below → consolidate
    high_threshold: float = 2.0  # above → explore

    def transition(self, entropy: float) -> tuple[Phase, bool]:
        """Return (new_phase, changed). Applies hysteresis."""
        if self.phase is Phase.EXPLORATION and entropy < self.low_threshold:
            self.phase = Phase.CONSOLIDATION
            return self.phase, True
        if self.phase is Phase.CONSOLIDATION and entropy > self.high_threshold:
            self.phase = Phase.EXPLORATION
            return self.phase, True
        return self.phase, False


def pool_weights(phase: Phase) -> dict[str, float]:
    """Spawn-weight multipliers per pool for the current phase."""
    if phase is Phase.EXPLORATION:
        return {"scout": 1.3, "forager": 1.1, "validator": 0.7, "gc": 0.5,
                "inquiline.citation": 0.6, "inquiline.numeric": 0.6}
    return {"scout": 0.6, "forager": 0.9, "validator": 1.3, "gc": 1.2,
            "inquiline.citation": 1.1, "inquiline.numeric": 1.1}
