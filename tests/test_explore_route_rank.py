"""Explore ranks final routed reports by named phase priorities after validity."""
import pytest

from placemat.explore import _taken
from placemat.settings import Settings


def routes():
    reports = [(1, 0.95, 0.5, 0.97), (2, 0.90, 1.0, 0.9), (3, 0.90, 1.0, 0.9)]
    return [{"seed": seed, "route_report": {
        "drc_new": 0, "widths_failed": 0, "critical_checks": 0,
        "critical_unknown": [], "final_findings": {}, "closure_clean": clean,
        "phases": [
            {"name": "legs", "comparison_contract": "original-legs",
             "final_closure_clean": legs},
            {"name": "signals", "comparison_contract": "original-signals",
             "final_closure_clean": signals}],
    }} for seed, clean, legs, signals in reports]


def measures():
    return {seed: {"v": 2, "airwire_mm": airwire}
            for seed, airwire in [(1, 10.0), (2, 12.0), (3, 11.0)]}


def test_default_ranking_uses_the_full_configured_phase_order():
    assert _taken(routes(), measures(), Settings()) == 3


def test_explicit_empty_priorities_use_board_wide_closure():
    assert _taken(routes(), measures(), Settings(), phase_priority=()) == 1


def test_a_ranked_phase_comes_first_then_the_common_score():
    assert _taken(routes(), measures(), Settings(), phase_priority=("legs",)) == 3


def test_validity_precedes_the_named_phase_and_score():
    candidates = routes()
    candidates[2]["route_report"]["drc_new"] = 1
    assert _taken(candidates, measures(), Settings(), phase_priority=("legs",)) == 2


def test_omitted_phase_contracts_still_must_match():
    candidates = routes()
    candidates[2]["route_report"]["phases"][1]["comparison_contract"] = "changed-signals"
    with pytest.raises(ValueError, match="incomparable"):
        _taken(candidates, measures(), Settings(), phase_priority=("legs",))


def test_a_rank_naming_no_phase_is_refused():
    from placemat.cli import _route_rank
    with pytest.raises(SystemExit):
        _route_rank("legs,bogus", ("legs", "signals"))
