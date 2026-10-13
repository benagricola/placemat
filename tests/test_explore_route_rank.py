"""explore --route-rank orders the routed variants by named phases' clean closure, then as before."""
import pytest

from placemat.explore import _taken
from placemat.settings import Settings


def routes():
    return [{"seed": 1, "drc_new": 0, "closure_clean": 0.95, "score": 10.0, "error": None, "phases": {"legs": 0.5, "signals": 0.97}},
            {"seed": 2, "drc_new": 0, "closure_clean": 0.90, "score": 12.0, "error": None, "phases": {"legs": 1.0, "signals": 0.9}},
            {"seed": 3, "drc_new": 0, "closure_clean": 0.90, "score": 11.0, "error": None, "phases": {"legs": 1.0, "signals": 0.9}}]


def test_without_a_rank_the_board_wide_closure_decides():
    assert _taken(routes(), measures(), Settings()) == 1


def test_a_ranked_phase_comes_first_then_the_score():
    assert _taken(routes(), measures(), Settings(), rank=("legs",)) == 3


def test_a_rank_naming_no_phase_is_refused(tmp_path):
    from placemat.cli import _route_rank
    with pytest.raises(SystemExit):
        _route_rank("legs,bogus", ("legs", "signals"))


def measures():
    return {r["seed"]: {"airwire_mm": r["score"], "findings": {}, "unplaced": {}} for r in routes()}


@pytest.mark.parametrize("failure", [{"drc_new": 1}, {"widths_failed": 1}])
def test_invalid_high_closure_loses_to_valid_route(failure):
    rows = routes()
    rows[0].update(failure)
    assert _taken(rows, measures(), Settings()) == 3


def test_complete_route_quality_precedes_run_score():
    rows = routes()
    for r in rows:
        r.update(closure_clean=1.0, vias=2, copper_mm=100.0, segments=10)
    rows[2]["vias"] = 1
    assert _taken(rows, measures(), Settings()) == 3


def test_unjudged_route_cannot_be_accepted():
    rows = routes()
    rows[0]["drc_new"] = None
    assert _taken(rows, measures(), Settings()) == 3
    for row in rows:
        row["drc_new"] = None
    assert _taken(rows, measures(), Settings()) is None
