"""Closure is scored from the open connections before and after routing;
a net the router closed through a violation counts as fully open."""
from placemat.kicad.route import score


def test_closure_is_the_share_of_open_signal_items_closed():
    before = {"A": 2, "B": 3, "C": 1}
    after = {"B": 1}
    r = score(before, after, violated_nets=set())
    assert r.closure == 1 - 1 / 6
    assert r.closure_clean == r.closure and r.shorted == []


def test_a_net_closed_through_a_violation_counts_as_open_in_the_clean_number():
    before = {"A": 2, "B": 3}
    after = {}
    r = score(before, after, violated_nets={"A"})
    assert r.closure == 1.0
    assert r.closure_clean == 1 - 2 / 5 and r.shorted == ["A"]


def test_nothing_open_before_is_full_closure():
    r = score({}, {}, violated_nets=set())
    assert r.closure == 1.0 and r.closure_clean == 1.0
