"""Phase cycling with hysteresis."""

from formica.coordinator.phases import Phase, PhaseState, pool_weights


def test_phase_transitions_with_hysteresis():
    s = PhaseState(phase=Phase.EXPLORATION, low_threshold=1.0, high_threshold=2.0)
    # Entropy between thresholds → no change.
    p, changed = s.transition(1.5)
    assert p is Phase.EXPLORATION and not changed
    # Entropy below low → consolidate.
    p, changed = s.transition(0.8)
    assert p is Phase.CONSOLIDATION and changed
    # Entropy between again → no flip back.
    p, changed = s.transition(1.5)
    assert p is Phase.CONSOLIDATION and not changed
    # Above high → back to exploration.
    p, changed = s.transition(2.5)
    assert p is Phase.EXPLORATION and changed


def test_pool_weights_favor_validators_in_consolidation():
    w = pool_weights(Phase.CONSOLIDATION)
    assert w["validator"] > w["scout"]


def test_pool_weights_favor_scouts_in_exploration():
    w = pool_weights(Phase.EXPLORATION)
    assert w["scout"] > w["validator"]
