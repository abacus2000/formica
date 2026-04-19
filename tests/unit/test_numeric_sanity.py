"""Numeric sanity inquiline — pure-Python path (no Neo4j)."""

from formica.agents.inquiline.numeric_sanity import _EQ_RE, _check


def test_eq_regex_matches_simple_arithmetic():
    m = list(_EQ_RE.finditer("therefore 2 + 3 = 5 and 10 / 2 = 5"))
    assert len(m) == 2


def test_check_accepts_true_arithmetic():
    assert _check(2, "+", 3, 5)
    assert _check(10, "/", 2, 5)
    assert _check(4, "*", 2.5, 10)


def test_check_rejects_false_arithmetic():
    assert not _check(2, "+", 3, 6)
    assert not _check(9, "-", 4, 4)
