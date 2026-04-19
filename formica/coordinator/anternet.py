"""Anternet feedback: spawn rate follows recent `validated` yield per compute-second."""

from __future__ import annotations


def anternet_signal(
    validated_delta: float,
    compute_seconds: float,
    target_yield: float = 0.01,
    gain: float = 1.0,
) -> float:
    """Return a spawn-rate multiplier in [0.25, 2.0].

    If recent validated yield (validated pheromone added per compute-second) is
    above target, multiplier > 1 (spawn more). Below target → multiplier < 1.
    """
    if compute_seconds <= 0:
        return 1.0
    yield_rate = validated_delta / compute_seconds
    mult = 1.0 + gain * ((yield_rate - target_yield) / max(target_yield, 1e-6))
    return max(0.25, min(2.0, mult))
