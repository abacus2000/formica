"""Pheromone decay math."""

import math

from formica.pheromones.decay import current_value, evaporate, pheromone_entropy


def test_current_value_half_life():
    # After exactly one half-life, value should be half.
    v = current_value(1.0, updated_at=0.0, half_life_s=100.0, now=100.0)
    assert math.isclose(v, 0.5, rel_tol=1e-9)


def test_current_value_no_time_passed():
    v = current_value(0.8, updated_at=1000.0, half_life_s=100.0, now=1000.0)
    assert v == 0.8


def test_current_value_zero_half_life_returns_zero():
    assert current_value(1.0, updated_at=0.0, half_life_s=0.0, now=10.0) == 0.0


def test_evaporate_drops_below_min():
    pher = [
        {"channel": "promising", "value": 1.0, "updated_at": 0.0, "half_life_s": 10.0},
        {"channel": "alarm",     "value": 1.0, "updated_at": 0.0, "half_life_s": 1.0},
    ]
    out = evaporate(pher, min_pheromone=1e-4, now=100.0)
    channels = {p["channel"] for p in out}
    # promising is 2^-10 ≈ 1e-3 (above threshold). alarm is 2^-100 ≈ 0 (below).
    assert "promising" in channels
    assert "alarm" not in channels


def test_evaporate_preserves_half_life():
    out = evaporate(
        [{"channel": "validated", "value": 0.5, "updated_at": 0.0, "half_life_s": 60.0}],
        now=30.0,
    )
    assert len(out) == 1
    assert out[0]["half_life_s"] == 60.0
    assert 0 < out[0]["value"] < 0.5


def test_entropy_zero_when_empty():
    assert pheromone_entropy({}) == 0.0


def test_entropy_positive_when_mixed():
    ent = pheromone_entropy({"promising": [0.5, 0.5], "dead-end": [0.5]})
    assert ent > 0
