from formica.coordinator.anternet import anternet_signal


def test_returns_one_on_no_compute():
    assert anternet_signal(1.0, 0.0) == 1.0


def test_scales_up_when_yield_above_target():
    mult = anternet_signal(validated_delta=2.0, compute_seconds=10.0, target_yield=0.01)
    assert mult > 1.0


def test_scales_down_when_yield_below_target():
    mult = anternet_signal(validated_delta=0.0, compute_seconds=10.0, target_yield=0.1)
    assert mult < 1.0


def test_bounded_between_quarter_and_two():
    big = anternet_signal(100.0, 1.0, target_yield=0.001)
    small = anternet_signal(0.0, 1.0, target_yield=1.0)
    assert 0.25 <= big <= 2.0
    assert 0.25 <= small <= 2.0
