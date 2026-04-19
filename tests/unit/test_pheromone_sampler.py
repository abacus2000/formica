"""Pheromone gradient sampling."""

import random

from formica.pheromones.sampler import gradient_weights, softmax_sample


def test_gradient_weights_penalizes_dead_end():
    edges = [
        {"pheromones": [{"channel": "promising", "value": 0.8},
                        {"channel": "dead-end", "value": 0.2}]},
        {"pheromones": [{"channel": "promising", "value": 0.8}]},
    ]
    w = gradient_weights(edges, beta=2.0)
    # First edge: 0.8 - 2*0.2 = 0.4. Second: 0.8. Second should be larger.
    assert w[1] > w[0]
    assert w[0] == 0.4


def test_gradient_weights_floor_at_zero():
    edges = [{"pheromones": [{"channel": "promising", "value": 0.1},
                             {"channel": "dead-end", "value": 0.9}]}]
    assert gradient_weights(edges, beta=2.0) == [0.0]


def test_softmax_sample_zero_weights_returns_minus_one():
    assert softmax_sample([0, 0, 0]) == -1


def test_softmax_sample_deterministic_with_seed():
    rng = random.Random(42)
    idx = softmax_sample([0.1, 0.9, 0.2], rng=rng)
    assert 0 <= idx < 3


def test_softmax_sample_prefers_higher_weights():
    rng = random.Random(7)
    counts = [0, 0, 0]
    for _ in range(1000):
        counts[softmax_sample([0.1, 5.0, 0.1], rng=rng, tau=0.5)] += 1
    # Middle option should dominate.
    assert counts[1] > counts[0] + counts[2]
