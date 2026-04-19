"""Pheromone channel definitions, evaporation math, and gradient sampling."""

from formica.pheromones.constants import (
    CHANNELS,
    DEFAULT_HALF_LIFE,
    EVAPORATION_CADENCE,
    PheromoneChannel,
)
from formica.pheromones.decay import evaporate, current_value
from formica.pheromones.sampler import softmax_sample, gradient_weights

__all__ = [
    "CHANNELS",
    "DEFAULT_HALF_LIFE",
    "EVAPORATION_CADENCE",
    "PheromoneChannel",
    "evaporate",
    "current_value",
    "softmax_sample",
    "gradient_weights",
]
