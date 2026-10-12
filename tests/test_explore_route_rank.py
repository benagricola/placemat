"""explore --route-rank orders the routed variants by named phases' clean closure, then as before."""
import pytest

from placemat.explore import _taken


def routes():
    return [{"seed": 1, "closure_clean": 0.95, "score": 10.0, "error": None, "phases": {"legs": 0.5, "signals": 0.97}},
            {"seed": 2, "closure_clean": 0.90, "score": 12.0, "error": None, "phases": {"legs": 1.0, "signals": 0.9}},
            {"seed": 3, "closure_clean": 0.90, "score": 11.0, "error": None, "phases": {"legs": 1.0, "signals": 0.9}}]


def test_without_a_rank_the_board_wide_closure_decides():
    assert _taken(routes(), {}) == 1


def test_a_ranked_phase_comes_first_then_the_score():
    assert _taken(routes(), {}, rank=("legs",)) == 3


def test_a_rank_naming_no_phase_is_refused(tmp_path):
    from placemat.cli import _route_rank
    with pytest.raises(SystemExit):
        _route_rank("legs,bogus", ("legs", "signals"))
