"""Softmax sampling over pheromone gradients."""

from __future__ import annotations

import math
import random
from typing import Sequence

from formica.pheromones.constants import (
    DEAD_END_PENALTY_BETA,
    PheromoneChannel,
    SOFTMAX_TAU,
)


def _channel_value(pheromones: list[dict], channel: str) -> float:
    for p in pheromones:
        if p.get("channel") == channel:
            return float(p.get("value", 0.0))
    return 0.0


def gradient_weights(
    edges: Sequence[dict],
    promising_channel: str = PheromoneChannel.PROMISING.value,
    dead_end_channel: str = PheromoneChannel.DEAD_END.value,
    beta: float = DEAD_END_PENALTY_BETA,
) -> list[float]:
    """For each edge, compute `max(0, promising - beta*dead_end)`."""
    out: list[float] = []
    for e in edges:
        pher = e.get("pheromones") or []
        prom = _channel_value(pher, promising_channel)
        dead = _channel_value(pher, dead_end_channel)
        out.append(max(0.0, prom - beta * dead))
    return out


def softmax_sample(
    weights: Sequence[float],
    tau: float = SOFTMAX_TAU,
    rng: random.Random | None = None,
) -> int:
    """Return the index sampled by softmax(w / tau). Returns -1 if all weights are zero."""
    if not weights or all(w <= 0 for w in weights):
        return -1
    rng = rng or random
    scaled = [w / max(tau, 1e-6) for w in weights]
    m = max(scaled)
    exps = [math.exp(s - m) for s in scaled]
    z = sum(exps)
    probs = [e / z for e in exps]
    r = rng.random()
    cum = 0.0
    for i, p in enumerate(probs):
        cum += p
        if r <= cum:
            return i
    return len(probs) - 1
