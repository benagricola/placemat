"""The one board comparison, `score.rank`: validity, the phases' closures, the clean closure, KRT's routed quality key on
complete boards, then the run score (D11-D17)."""
import math
from types import SimpleNamespace

import pytest

from placemat import score
from placemat.score import Standing, Validity, quality_key, rank
from placemat.settings import Settings, SettingsError, load

M = {"v": 2, "airwire_mm": 100.0, "crossings": {}}


def test_an_earlier_phase_outranks_clean_closure():
    a = Standing(M, closures=(1.0, 0.8), clean=0.8)
    b = Standing(M, closures=(0.9, 1.0), clean=0.95)
    assert rank(a, b, cfg=Settings()) == -1


def test_area_is_traded_in_the_run_score():
    s = Settings()
    small = Standing({**M, "area_mm2": 100.0, "airwire_mm": 300.0}, closures=(1.0,), clean=1.0)
    large = Standing({**M, "area_mm2": 140.0, "airwire_mm": 50.0}, closures=(1.0,), clean=1.0)
    want = -1 if 100 * s.score_area + 300 < 140 * s.score_area + 50 else 1
    assert rank(small, large, cfg=s) == want


def test_routed_quality_is_krts_key_on_complete_boards():
    few = Standing({**M, "airwire_mm": 500.0, "vias": 2, "copper_mm": 90.0, "segments": 40}, closures=(1.0,), clean=1.0)
    many = Standing({**M, "vias": 12, "copper_mm": 80.0, "segments": 30}, closures=(1.0,), clean=1.0)
    assert rank(few, many, cfg=Settings()) == -1          # fewer vias first, whatever the run score


def test_routed_quality_is_not_compared_on_incomplete_boards():
    few = Standing({**M, "airwire_mm": 500.0, "vias": 2}, closures=(0.9,), clean=0.9)
    many = Standing({**M, "vias": 12}, closures=(0.9,), clean=0.9)
    assert rank(few, many, cfg=Settings()) == 1           # the run score decides


def test_a_buildable_board_outranks_a_better_connected_one():
    legal = Standing(M, closures=(0.9,), clean=0.9)
    narrow = Standing(M, validity=Validity(widths_failed=1), closures=(1.0,), clean=1.0)
    drc = Standing(M, validity=Validity(drc_new=2), closures=(1.0,), clean=1.0)
    unplaced = Standing(M, validity=Validity(unplaced=(0, 1, 0)))
    assert rank(legal, narrow, cfg=Settings()) == -1
    assert rank(legal, drc, cfg=Settings()) == -1
    assert rank(legal, unplaced, cfg=Settings()) == -1


def test_a_tie_keeps_the_incumbent():
    assert rank(Standing(M), Standing(dict(M)), cfg=Settings()) == 0


def test_unrouted_standings_compare_on_the_score():
    a, b = Standing({**M, "airwire_mm": 90.0}), Standing(M)
    assert rank(a, b, cfg=Settings()) == -1


# ------------------------------------------------------------ the validity tier
def test_validity_is_valid_only_with_every_count_zero():
    assert Validity().valid
    assert Validity(drc_new=0).valid
    for bad in (Validity(unplaced=(0, 0, 1)), Validity(drc_new=1), Validity(widths_failed=1), Validity(critical=1)):
        assert not bad.valid


def test_the_validity_key_orders_unplaced_by_priority_then_drc_then_widths_then_critical():
    assert Validity(unplaced=(1, 2, 3), drc_new=4, widths_failed=5, critical=6).key() == (1, 2, 3, 4, 5, 6)
    assert Validity(drc_new=None).key() == (0, 0, 0, 0, 0, 0)
    # a high-priority part left out is worse than any number of default ones
    assert Validity(unplaced=(1, 0, 0)).key() > Validity(unplaced=(0, 9, 0), drc_new=9).key()


def test_two_invalid_boards_compare_by_fewest_failures_before_closure():
    one = Standing(M, validity=Validity(drc_new=1), closures=(0.5,), clean=0.5)
    two = Standing(M, validity=Validity(drc_new=2), closures=(1.0,), clean=1.0)
    assert rank(one, two, cfg=Settings()) == -1
    assert rank(two, one, cfg=Settings()) == 1


def test_two_invalid_boards_with_the_same_failures_go_on_to_closure():
    a = Standing(M, validity=Validity(critical=1), closures=(1.0,), clean=1.0)
    b = Standing(M, validity=Validity(critical=1), closures=(0.9,), clean=0.9)
    assert rank(a, b, cfg=Settings()) == -1


def test_validity_of_reads_the_measures_and_its_arguments():
    m = {**M, "unplaced": {"high": 1, "default": 2, "low": 3}, "drc": 7,
         "findings": {"fixed": 1, "copper": 2, "escape_walled": 4, "escape_closed": 9, "label": 1}}
    v = Validity.of(m, drc_new=5, widths_failed=2)
    assert v == Validity(unplaced=(1, 2, 3), drc_new=5, widths_failed=2, critical=7)
    assert Validity.of({**M}).valid
    assert Validity.of(m).drc_new is None                 # no DRC ran: the measures' own count is not read


def test_the_hard_findings_are_the_critical_kinds_the_measures_count():
    from placemat.findings import SEVERITY
    assert set(score.HARD_FINDINGS) == {"fixed", "copper", "escape_walled"}
    assert all(SEVERITY[k] == "critical" for k in score.HARD_FINDINGS)


# ------------------------------------------------------------ one home per term (D13)
def test_the_hard_terms_are_not_in_the_run_score():
    m = {**M, "unplaced": {"high": 3}, "drc": 4, "findings": {"fixed": 1, "copper": 1, "escape_walled": 2}}
    t = score.terms(m, Settings())
    for k in ("unplaced", "drc", "fixed", "copper", "escape_walled"):
        assert k not in t and k not in score.TERMS
    assert score.total(m, Settings()) == score.total(M, Settings())


@pytest.mark.parametrize("key", ["unplaced", "unplaced_high", "unplaced_default", "unplaced_low", "drc", "fixed", "copper",
                                 "escape_walled"])
def test_a_removed_hard_term_setting_is_refused_naming_the_validity_tier(tmp_path, key):
    (tmp_path / "placemat.toml").write_text("[score]\n%s = 1.0\n" % key)
    with pytest.raises(SettingsError, match=r"score\.%s is retired; .*validity" % key):
        load(tmp_path)
    assert not hasattr(Settings(), "score_" + key)


# ------------------------------------------------------------ KRT's quality key (D17)
def test_the_quality_key_reads_vias_copper_and_segments_and_ranks_the_unmeasured_last():
    assert quality_key({"vias": 3, "copper_mm": 12.5, "segments": 9}) == (3, 12.5, 9)
    assert quality_key({}) == (math.inf, math.inf, math.inf)
    assert quality_key({"vias": True, "copper_mm": float("nan"), "segments": "9"}) == (math.inf, math.inf, math.inf)


def test_the_quality_key_is_not_compared_when_either_board_is_invalid():
    few = Standing({**M, "airwire_mm": 500.0, "vias": 2}, validity=Validity(critical=1), closures=(1.0,), clean=1.0)
    many = Standing({**M, "vias": 12}, validity=Validity(critical=1), closures=(1.0,), clean=1.0)
    assert rank(few, many, cfg=Settings()) == 1           # both invalid alike: the run score decides


def test_a_routed_standing_is_read_from_the_route_report():
    report = SimpleNamespace(phases=[{"final_closure_clean": 1.0}, {"final_closure_clean": 0.75}], widths_failed=2,
                             drc_new=3, closure_clean=0.8, vias=7, track_mm=123.4, segments=55)
    s = Standing.of_route({**M, "unplaced": {"low": 1}, "findings": {"copper": 1}}, report)
    assert s.closures == (1.0, 0.75) and s.clean == 0.8
    assert s.validity == Validity(unplaced=(0, 0, 1), drc_new=3, widths_failed=2, critical=1)
    assert quality_key(s.measures) == (7, 123.4, 55)


def test_a_route_with_no_drc_has_no_drc_count():
    report = SimpleNamespace(phases=[], widths_failed=0, drc_new=None, closure_clean=1.0, vias=0, track_mm=0.0, segments=0)
    s = Standing.of_route(dict(M), report)
    assert s.validity.drc_new is None and s.validity.valid and s.closures == ()
