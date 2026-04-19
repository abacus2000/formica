"""Pheromone evaporation math."""

from __future__ import annotations

import math
import time
from typing import Iterable

from formica.pheromones.constants import DEFAULT_HALF_LIFE


def current_value(value_0: float, updated_at: float, half_life_s: float, now: float | None = None) -> float:
    """Exponential decay: value(t) = value_0 * 0.5 ** ((t - updated_at) / half_life_s)."""
    if half_life_s <= 0:
        return 0.0
    t = now if now is not None else time.time()
    dt = max(0.0, t - updated_at)
    return value_0 * math.pow(0.5, dt / half_life_s)


def evaporate(
    pheromones: Iterable[dict],
    min_pheromone: float = 1e-4,
    now: float | None = None,
) -> list[dict]:
    """Recompute current values and drop those below min_pheromone.

    Each input is `{channel, value, updated_at, half_life_s}`. The returned list
    contains the same shape with `value` decayed to the current time and
    `updated_at` bumped to `now`. Entries below threshold are omitted entirely.
    """
    t = now if now is not None else time.time()
    out: list[dict] = []
    for p in pheromones:
        channel = p["channel"]
        half = float(p.get("half_life_s") or DEFAULT_HALF_LIFE.get(channel, 600))
        v = current_value(float(p["value"]), float(p["updated_at"]), half, now=t)
        if v >= min_pheromone:
            out.append(
                {
                    "channel": channel,
                    "value": v,
                    "updated_at": t,
                    "half_life_s": half,
                }
            )
    return out


def pheromone_entropy(values_by_channel: dict[str, list[float]]) -> float:
    """Shannon entropy of the normalized channel mass distribution.

    Used to drive phase cycling (exploration vs consolidation) with hysteresis.
    """
    total_mass = sum(sum(v) for v in values_by_channel.values())
    if total_mass <= 0:
        return 0.0
    ent = 0.0
    for vs in values_by_channel.values():
        s = sum(vs)
        if s <= 0:
            continue
        p = s / total_mass
        ent -= p * math.log(p, 2)
    return ent
