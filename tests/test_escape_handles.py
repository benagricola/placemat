"""The handles board.escape() returns: a lane as a track's first point, its via as a via handle (a track
point, a Past item, a Beside item), a lane as a Beside align target, its end as a point reference, and
the escape itself as a Beside item. Pure: synthetic boards."""
import math

import pytest

from placemat.copper import Track, Via
from placemat.values import Beside, CopperLayer, Edge, Location, Net, PadRef, Part, Past, Pin, X, Y
from tests.escape_fixtures import CLEAR, PD_NETS, TRACK, VIA, board_with, qfn, small_part

F = CopperLayer.F
OUT_TRACK = 0.3
LANE0_Y = 27.2 - (OUT_TRACK + CLEAR)           # VOUT's lane


def _model(*parts):
    """The north-row model with the three-lane escape declared, and `parts` on the board."""
    b = board_with([qfn(nets=PD_NETS)] + list(parts))
    b.place(Part("pd"), at=Location(30, 30))
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], widths={32: OUT_TRACK}, why="north row")
    return b, esc


def _pad(plan, ref, number):
    return plan.occupancy.pad_location(ref, str(number))


def _unplaced_or_fixed(plan):
    return [f for f in plan.findings if f.kind in ("fixed", "unplaced")]


def test_a_part_stands_beside_a_lane_s_via():
    b, esc = _model(small_part("C1", "c_pd", ("GND", "PGOOD")))
    b.place(Part("c_pd"), at=Beside(esc[30].via, Edge.WEST), why="west of PGOOD's via")
    b.track(Net("PGOOD"), [esc[30]], layer=F, why="its lane")
    plan = b.resolve()
    (via,) = [v for v in plan.copper if isinstance(v, Via)]
    pad = plan.occupancy.items["C1"].shapes
    east = max(s.box.right for s in pad if s.kind == "pad")
    assert plan.box("c_pd").center.x < via.at.x                     # west of it
    assert via.at.x - VIA / 2 - east >= CLEAR - 1e-6                # a gap off its copper
    assert via.at.x - VIA / 2 - east <= CLEAR + 0.3 + 1e-6          # and no more than the envelope's own
    assert not _unplaced_or_fixed(plan)


def test_a_part_waits_for_the_escaped_part_it_refers_to():
    b = board_with([qfn(nets=PD_NETS), small_part("C1", "c_pd", ("GND", "PGOOD"))])
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], widths={32: OUT_TRACK}, why="north row")
    b.place(Part("c_pd"), at=Beside(esc[30].via, Edge.WEST), why="declared first")
    b.place(Part("pd"), at=Location(30, 30))                        # the escaped part, placed after
    plan = b.resolve()
    assert plan.placement("c_pd") is not None and not _unplaced_or_fixed(plan)


def test_a_part_beside_a_via_rides_the_searched_part_whose_escape_it_is():
    from placemat.values import Near
    b = board_with([qfn(nets=PD_NETS), small_part("C1", "c_pd", ("GND", "PGOOD"))])
    b.place(Part("pd"), at=Near(Location(30, 30), radius=1.0, step=0.5, rotations=(0.0,)))
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], why="north row")
    b.place(Part("c_pd"), at=Beside(esc[30].via, Edge.WEST), why="west of PGOOD's via")
    plan = b.resolve()
    via = b._escape_laid[0].lanes["30"].via
    assert "rides pd" in plan.step("c_pd").note
    assert plan.box("c_pd").center.x < via.at.x
    assert not _unplaced_or_fixed(plan)


def test_a_pad_stands_centred_across_a_lane_s_line_at_the_end_of_it():
    b, esc = _model(small_part("C1", "c_pd", ("GND", "VOUT")))
    b.place(Part("c_pd"), at=Beside(esc[30].via, Edge.WEST, align=(2, esc[32])), why="on VOUT's lane, west of the via")
    b.track(Net("VOUT"), [esc[32], PadRef(Part("c_pd"), 2)], layer=F, why="the lane on to the pad")
    plan = b.resolve()
    assert _pad(plan, "C1", 2).y == pytest.approx(LANE0_Y, abs=1e-6)
    assert not _unplaced_or_fixed(plan)
    last = [t for t in plan.copper if isinstance(t, Track)][-1]
    assert last.end.y == pytest.approx(LANE0_Y) and last.end.x == pytest.approx(_pad(plan, "C1", 2).x)


def test_a_lane_aligned_across_the_wrong_side_is_refused():
    b, esc = _model(small_part("C1", "c_pd", ("GND", "VOUT")))
    with pytest.raises(ValueError, match="needs the side to decide"):
        b.place(Part("c_pd"), at=Beside(esc[30].via, Edge.NORTH, align=(2, esc[32])))


def test_a_pad_sits_at_a_lane_s_end():
    b = board_with([qfn(nets=PD_NETS), small_part("C1", "c_pd", ("VOUT", "GND"))])
    b.place(Part("pd"), at=Location(30, 30))
    esc = b.escape(Part("pd"), [32], turn=Edge.WEST, why="one lane, no via")
    b.place(Part("c_pd"), at=Pin(1, X(esc[32].end), Y(esc[32].end)), rotation=90.0, why="at the lane's end")
    b.track(Net("VOUT"), [esc[32], PadRef(Part("c_pd"), 1)], layer=F, why="the lane on to the pad")
    plan = b.resolve()
    lane_end = Location(28.125 - (TRACK / 2 + CLEAR + TRACK / 2), 27.2 - (TRACK + CLEAR))     # the row's end, a step on
    assert _pad(plan, "C1", 1).x == pytest.approx(lane_end.x, abs=1e-6)
    assert _pad(plan, "C1", 1).y == pytest.approx(lane_end.y, abs=1e-6)
    legs = [t for t in plan.copper if isinstance(t, Track)]
    assert (legs[0].start.x, legs[0].start.y) == pytest.approx((28.25, 27.55))       # begins at pin 32's pad
    assert (legs[-1].end.x, legs[-1].end.y) == pytest.approx((lane_end.x, lane_end.y))   # and ends on the cap's pad
    assert not _unplaced_or_fixed(plan)


def test_a_track_runs_from_a_lane_through_its_via_to_a_pad_beyond():
    b, esc = _model(small_part("C1", "c_pd", ("SENSE", "GND"), 22.0, 22.0))
    b.place(Part("c_pd"), at=Location(22.0, 22.0))
    b.track(Net("SENSE"), [esc[31], PadRef(Part("c_pd"), 1)], layer=F, why="on to the capacitor")
    plan = b.resolve()
    (via,) = [v for v in plan.copper if isinstance(v, Via)]
    legs = [t for t in plan.copper if isinstance(t, Track)]
    assert any((t.end.x, t.end.y) == pytest.approx((via.at.x, via.at.y)) for t in legs)        # through its via
    pad = _pad(plan, "C1", 1)
    assert (legs[-1].end.x, legs[-1].end.y) == pytest.approx((pad.x, pad.y))


def test_a_via_is_a_past_item():
    b, esc = _model()
    b.track(Net("PGOOD"), [esc[30]], layer=F, why="its lane")
    b.via(Net("N29"), Past([esc[30].via], Edge.WEST), why="a via past PGOOD's")
    plan = b.resolve()
    vias = {v.net: v for v in plan.copper if isinstance(v, Via)}
    a, c = vias["PGOOD"], vias["N29"]
    assert c.at.x < a.at.x
    assert math.hypot(a.at.x - c.at.x, a.at.y - c.at.y) - VIA >= CLEAR - 1e-6


def test_an_escape_is_a_beside_item_of_its_risers_lanes_and_vias():
    b, esc = _model(small_part("C1", "c_pd", ("N29", "GND")))
    b.place(Part("c_pd"), at=Beside(esc, Edge.NORTH), why="north of the escape")
    plan = b.resolve()
    laid = b._escape_laid[0].box()
    assert plan.box("c_pd").bottom <= laid.top - CLEAR + 1e-6        # north of the lanes, a gap off
    assert not _unplaced_or_fixed(plan)


def test_a_lane_is_not_a_beside_item_and_only_a_first_track_point():
    b, esc = _model(small_part("C1", "c_pd", ("GND", "VOUT")))
    with pytest.raises(TypeError, match="Beside's item"):
        b.place(Part("c_pd"), at=Beside(esc[31], Edge.WEST))
    with pytest.raises(TypeError, match="first"):
        b.track(Net("SENSE"), [Location(20, 20), esc[31]], layer=F)
    with pytest.raises(TypeError, match="first"):
        b.track(Net("SENSE"), [esc[31], esc[31]], layer=F)


def test_a_lane_without_a_via_has_no_via_handle_and_carries_its_pin_s_net():
    b, esc = _model()
    with pytest.raises(ValueError, match="no via"):
        esc[32].via
    with pytest.raises(ValueError, match="carries that net"):
        b.track(Net("SENSE"), [esc[32]], layer=F)
    with pytest.raises(KeyError):
        esc[29]                                                     # a pin the escape does not name
    assert esc["SENSE"].number == "31"                             # named by its net, as a PadRef names a pad


def test_a_lane_width_given_by_widths_is_the_track_a_lane_draws():
    b, esc = _model()
    b.track(Net("VOUT"), [esc[32]], layer=F, why="its lane")
    plan = b.resolve()
    assert {t.width for t in plan.copper if isinstance(t, Track)} == {OUT_TRACK}
