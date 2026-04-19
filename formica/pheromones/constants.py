"""Pheromone constants. Override via Helm values."""

from __future__ import annotations

from enum import Enum


class PheromoneChannel(str, Enum):
    PROMISING = "promising"
    VALIDATED = "validated"
    RISKY = "risky"
    NEEDS_EXPERT = "needs-expert"
    DEAD_END = "dead-end"
    ALARM = "alarm"


CHANNELS = tuple(c.value for c in PheromoneChannel)

# Half-lives (seconds) — override in production via env vars or Helm.
DEFAULT_HALF_LIFE: dict[str, int] = {
    PheromoneChannel.PROMISING.value: 15 * 60,
    PheromoneChannel.VALIDATED.value: 60 * 60,
    PheromoneChannel.RISKY.value: 10 * 60,
    PheromoneChannel.NEEDS_EXPERT.value: 20 * 60,
    PheromoneChannel.DEAD_END.value: 120 * 60,
    PheromoneChannel.ALARM.value: 30,
}

# Evaporation cron cadence (seconds).
EVAPORATION_CADENCE: dict[str, int] = {
    PheromoneChannel.PROMISING.value: 60,
    PheromoneChannel.VALIDATED.value: 60,
    PheromoneChannel.RISKY.value: 60,
    PheromoneChannel.NEEDS_EXPERT.value: 60,
    PheromoneChannel.DEAD_END.value: 60,
    PheromoneChannel.ALARM.value: 10,
}

# Sampling constants.
SOFTMAX_TAU = 0.5
DEAD_END_PENALTY_BETA = 2.0
