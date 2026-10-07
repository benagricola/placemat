"""Escapes judged by surface lanes (docs/superpowers/specs/2026-10-07-surface-escapes-design.md): a pad's way out is a
straight lane on its own layer toward what it joins (free), else a via beside it (score.escape_via), else a lane another
way (score.escape_closed), else none (score.escape_walled)."""
import dataclasses

import pytest

from placemat.escapes import Way, judging, pad_lanes, price, _pads_of
from placemat.settings import Settings
from placemat.values import Net
from tests.escape_fixtures import PIN1_EDGE, PIN1_Y, ic_with_cap, ic_with_cap_board


def test_cap_across_the_normal_closes_the_straight_lane_but_not_the_45():
    occ, esc = ic_with_cap(offset_mm=1.5, lateral_mm=0.0, room=True)
    lanes = esc.lanes("U1", "1")
    west = next(l for l in lanes if l.direction == pytest.approx((-1.0, 0.0)))
    assert not esc.lane_open(west)
    assert any(esc.lane_open(l) and l.direction[0] < -0.5 and l.direction[1] != 0 for l in lanes)
    assert esc.judge("U1", "1") is Way.SURFACE


def test_no_room_past_the_cap_leaves_a_via():
    occ, esc = ic_with_cap(offset_mm=1.0, lateral_mm=0.0, room=False)     # neighbours block both diagonals
    assert esc.judge("U1", "1") is Way.VIA
    assert price(Way.VIA, Settings()) == Settings().score_escape_via


def test_quiet_and_no_connect_pads_are_not_judged():
    occ, esc = ic_with_cap(offset_mm=1.5, lateral_mm=0.0, room=True, pin1_net="GND", plane=True)
    assert ("U1", "1") not in {(r, n) for r, n, *_ in esc.judged()}
    occ, esc = ic_with_cap(offset_mm=1.5, lateral_mm=0.0, room=True, pin1_net="NC_U1_1")
    assert ("U1", "1") not in {(r, n) for r, n, *_ in esc.judged()}


def test_a_pad_whose_net_has_no_other_pad_is_not_judged():
    occ, esc = ic_with_cap()
    assert ("U1", "1") in {(r, n) for r, n, *_ in esc.judged()}
    assert ("U1", "2") not in {(r, n) for r, n, *_ in esc.judged()}     # N2 has no other pad


def test_a_row_pad_has_eight_lanes_from_its_edge_reaching_out_to_the_setting():
    occ, esc = ic_with_cap()
    g = occ.items["U1"]
    lanes, spots = pad_lanes(occ, "U1", _pads_of(g.shapes, "U1"), g.reference.rotation)
    mine = [l for l in lanes if l.number == "1"]
    assert len(mine) == 8
    for l in mine:
        (a, b), (b2, end) = l.legs
        assert a == b == b2 == pytest.approx((PIN1_EDGE, PIN1_Y))       # pin 1 is the row's end: no field west of it
        assert ((end[0] - 27.3) ** 2 + (end[1] - PIN1_Y) ** 2) ** 0.5 == pytest.approx(Settings().score_escape_reach)
    assert len([s for s in spots if s.number == "1"]) == 1          # a via touching the pad's edge along the normal


def test_on_a_fine_pitch_the_first_leg_runs_on_until_a_diagonal_clears_the_neighbours_tips():
    from placemat.values import Location, Part
    from tests.escape_fixtures import PAD_W, PD_NETS, PITCH, board_with, qfn, small_part
    b = board_with([qfn(nets=PD_NETS), small_part("T1", "t1", ("SENSE", "Z"), cx=30.0, cy=15.0)])
    b.place(Part("pd"), at=Location(30, 30))
    b.place(Part("t1"), at=Location(30, 15))
    occ = b.resolve().occupancy
    esc = judging(occ)
    (a, b), _ = esc.lanes("U1", "31")[0].legs                       # north row: pin 31's tip at y = 27.2
    assert a[1] == pytest.approx(27.2)
    half = 0.2 / 2 + 0.2                                            # track 0.2, clearance 0.2
    side = PITCH - PAD_W / 2                                        # to the neighbour's near corner
    assert a[1] - b[1] == pytest.approx(half * 2 ** 0.5 - side)
    g = occ.items["U1"]
    _, spots = pad_lanes(occ, "U1", _pads_of(g.shapes, "U1"), g.reference.rotation)
    assert len([s for s in spots if s.number == "31"]) == 2         # and one where the first leg leaves the field


def test_a_two_pad_part_has_no_first_leg_and_a_via_spot_on_three_sides():
    occ, esc = ic_with_cap()
    g = occ.items["T1"]
    lanes, spots = pad_lanes(occ, "T1", _pads_of(g.shapes, "T1"), g.reference.rotation)
    mine = [l for l in lanes if l.number == "1"]
    assert len(mine) == 8 and all(l.legs[0][0] == l.legs[0][1] for l in mine)
    assert len([s for s in spots if s.number == "1"]) == 3


def test_a_pad_with_no_via_room_and_no_lane_toward_its_target_is_closed_and_with_none_at_all_walled():
    from tests.test_escape_findings import _fixed, _walled_in
    plan = _fixed(_walled_in(0.1), keep_going=True)
    esc = judging(plan.occupancy)
    assert esc.judge("U9", "1") is Way.WALLED
    found = [str(f) for f in plan.findings if f.kind == "escape_walled"]
    assert found == ["U9 pin 1 (IN): walled off by R9"]


def test_a_via_only_pad_is_reported_escape_via_naming_what_blocks_its_lanes():
    plan = ic_with_cap_board(offset_mm=1.0, room=False).resolve()
    vias = [f for f in plan.findings if f.kind == "escape_via"]
    assert [(f.facts["ref"], f.facts["pin"], f.facts["net"]) for f in vias] == [("U1", "1", "SIG")]
    assert {b.get("name") for b in vias[0].facts["by"]} == {"C1", "C2", "C3"}
    assert vias[0].severity == "warning"
    assert str(vias[0]).startswith("U1 pin 1 (SIG): ")


def test_a_clearance_rule_between_the_nets_closes_a_lane_the_classes_leave_open():
    b = ic_with_cap_board(offset_mm=1.5, room=True)
    occ = b.resolve().occupancy
    assert judging(occ).judge("U1", "1") is Way.SURFACE
    b = ic_with_cap_board(offset_mm=1.5, room=True)
    b.rule(clearance=0.6, between=(Net("SIG"), Net("CA")), why="a wider gap to C1")
    b.rule(clearance=0.6, between=(Net("SIG"), Net("CB")), why="a wider gap to C1")
    occ = b.resolve().occupancy
    assert judging(occ).judge("U1", "1") is not Way.SURFACE


def test_the_run_score_prices_the_judgement_and_whole_agrees_with_the_plan():
    from placemat import score
    b = ic_with_cap_board(offset_mm=1.0, room=False)
    plan = b.resolve()
    m = score.plan_measures(b, plan)
    assert m["findings"].get("escape_via") == 1
    t = score.terms(m, b.settings)
    assert t["escape_via"] == pytest.approx(b.settings.score_escape_via)
    w = score.whole(b, plan.occupancy, plan)
    for k in ("escape_crossed", "escape_closed", "escape_walled", "escape_via"):
        assert w[k] == pytest.approx(t[k]), k


def test_the_settings_default_as_decided():
    s = Settings()
    assert s.score_escape_reach == 3.0 and s.score_escape_via == 10.0
    assert price(Way.SURFACE, s) == 0.0
    assert price(Way.AWAY, s) == s.score_escape_closed and price(Way.WALLED, s) == s.score_escape_walled
    cfg = dataclasses.replace(s, score_escape_via=7.0)
    assert price(Way.VIA, cfg) == 7.0
