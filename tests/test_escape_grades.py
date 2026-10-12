"""Escapes graded by the lanes, walled by the exact search (D24): a pad's price comes from its lanes (straight, and one
dog-leg per lane each way) and via spots; a pad with none of them is a walled suspect, priced as closed, and only then
does the exact path search run, deciding validity."""
import pytest

from placemat import geometry, score
from placemat.escapes import Way, judging, path_out
from placemat.occupancy import ban_shape
from placemat.values import Location, Part
from tests.escape_fixtures import board_with, one_pad


def _dog_leg_board():
    """P1's one pad at (30, 30), what it joins 20 mm west. Three other-net pads close its straight lanes west,
    north-west and south-west; a lane that starts west and turns north-west halfway gets past them."""
    fps = [one_pad("P1", "p1", "S", 30.0, 30.0, size=0.6), one_pad("T1", "t1", "S", 10.0, 30.0),
           one_pad("B1", "b1", "Z1", 27.2, 30.0), one_pad("B2", "b2", "Z2", 28.0, 28.0),
           one_pad("B3", "b3", "Z3", 28.0, 32.0)]
    b = board_with(fps, keep_going=True)
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    return b.resolve().occupancy


def test_a_dog_leg_lane_is_found_where_no_straight_lane_is():
    occ = _dog_leg_board()
    esc = judging(occ)
    lanes = esc.lanes("P1", "1")
    centre = occ.pad_location("P1", "1")

    def west(lane):
        end = lane.legs[-1][1]
        return end[0] - centre.x < -occ.settings.place_escape_cell
    straight = [l for l in lanes if len(l.legs) == 2 and west(l)]
    dog_legs = [l for l in lanes if len(l.legs) == 3 and west(l)]
    assert straight and not any(esc.lane_open(l) for l in straight)
    assert any(esc.lane_open(l) for l in dog_legs)
    assert esc.judge("P1", "1") is Way.SURFACE and esc.searched == 0
    # the lane is a way the exact search finds too
    assert path_out(occ, "P1", "1", depth=occ.settings.score_escape_reach, toward=(-20.0, 0.0), exact=True,
                    via_exit=False)
    if hasattr(geometry._native, "surface_judge"):
        assert esc.judge_native("P1", "1") is Way.SURFACE


def _banned(gap):
    """U9's IN pad ringed `gap` mm off by R9's pads (test_escape_findings._walled_in), a via ban over it: no lane gets
    out and no via spot is free, so it is a walled suspect."""
    from tests.test_escape_findings import _fixed, _walled_in
    plan = _fixed(_walled_in(gap), keep_going=True)
    occ = plan.occupancy
    occ.add_copper([ban_shape("via exclusion", ((27, 27), (33, 27), (33, 33), (27, 33)), None, ())])
    return occ


def test_a_suspect_the_exact_search_clears_is_priced_closed_and_valid():
    occ = _banned(1.0)              # the ring's 0.75 mm gaps pass a track
    esc = judging(occ)
    assert esc.lane_check("U9", "1")[:2] == (False, False)
    esc.searched = 0
    assert esc.judge("U9", "1") is Way.AWAY and esc.searched == 1
    found = esc.found()
    assert [r[:2] for r in found["escape_closed"]] == [("U9", "1")] and not found["escape_walled"]
    assert esc._verdict("U9", "1", esc._bans(), exact=False)[0] is Way.SUSPECT


def test_a_suspect_the_exact_search_walls_is_priced_closed_and_invalid():
    occ = _banned(0.1)
    esc = judging(occ)
    assert esc.judge("U9", "1") is Way.WALLED
    found = esc.found()
    assert [r[:2] for r in found["escape_walled"]] == [("U9", "1")]
    assert [r[:2] for r in found["escape_closed"]] == [("U9", "1")]        # its price: the lanes grade it a suspect
    counts = esc.counts()
    assert counts["escape_closed"] == 1 and counts["escape_walled"] == 1
    measures = {"findings": {k: v for k, v in counts.items() if v}}
    assert not score.hard_clear(measures)
    assert score.terms(measures, occ.settings)["escape_closed"] == pytest.approx(occ.settings.score_escape_closed)
