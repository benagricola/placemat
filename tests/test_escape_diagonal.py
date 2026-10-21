"""board.escape() on a part turned 45: a row's way out is at 45 to the board's axes. Its risers run out along the way
out; with turn= an Edge on the way out runs the lanes along that board axis, and a Corner across it runs them along
the row; the lanes keep their clearance from each other and from the row's pads, and vias= lands vias along the lanes
as for a row along an axis. The QFN-56 (0.4 mm pitch, track and clearance 0.16) turned 45 at (30, 30): pins 1..14 face
south-east."""
import math

import pytest

from placemat.copper import Track, Via
from placemat.geometry import poly_distance
from placemat.values import Corner, CopperLayer, Edge, Location, Net, Part
from tests.escape_fixtures import CLEAR56, TRACK56, board_with, qfn56

F = CopperLayer.F
PINS = [5, 6, 7]


def _board(pins=PINS, vias=(), **kw):
    b = board_with([qfn56()], track=TRACK56, clearance=CLEAR56, keep_going=True)
    b.place(Part("mcu"), at=Location(30, 30), rotation=45)
    esc = b.escape(Part("mcu"), pins, vias=list(vias), why="a fan", **kw)
    for p in pins:
        b.track(Net("N%d" % p), [esc[p]], layer=F, why="its lane")
    return b, esc


def _tracks(plan, net):
    return [t for t in plan.copper if isinstance(t, Track) and t.net == net]


def _bad(plan):
    return [f for f in plan.findings if f.kind in ("copper", "escape_lane", "fixed", "escape_walled")]


def _clear(plan, pins):
    pads = [s for s in plan.occupancy.items["U1"].shapes if s.kind == "pad"]
    for p in pins:
        mine = _tracks(plan, "N%d" % p)
        for q in pins:
            if q != p:
                assert min(poly_distance(a.polygon, b.polygon) for a in mine for b in _tracks(plan, "N%d" % q)) \
                       >= CLEAR56 - 1e-6, (p, q)
        for pad in pads:
            if pad.net != "N%d" % p:
                assert min(poly_distance(a.polygon, pad.poly) for a in mine) >= CLEAR56 - 1e-6, (p, pad.label)


def _direction(t):
    dx, dy = t.end.x - t.start.x, t.end.y - t.start.y
    d = math.hypot(dx, dy)
    return round(dx / d, 3), round(dy / d, 3)


def test_the_risers_of_a_row_at_45_run_out_along_its_way_out():
    plan = _board()[0].resolve()
    assert _bad(plan) == []
    for p in PINS:
        t, = _tracks(plan, "N%d" % p)
        assert _direction(t) == (0.707, 0.707)
    _clear(plan, PINS)


@pytest.mark.parametrize("edge,along", [(Edge.SOUTH, (0.0, 1.0)), (Edge.EAST, (1.0, 0.0))])
def test_a_turn_to_a_board_axis_on_the_way_out_runs_the_lanes_along_it(edge, along):
    plan, = [_board(turn=edge)[0].resolve()]
    assert _bad(plan) == []
    for p in PINS:
        last = _tracks(plan, "N%d" % p)[-1]
        assert _direction(last) == along
    _clear(plan, PINS)


@pytest.mark.parametrize("corner,along", [(Corner.NE, (0.707, -0.707)), (Corner.SW, (-0.707, 0.707))])
def test_a_turn_across_the_way_out_runs_the_lanes_along_the_row(corner, along):
    plan = _board(turn=corner)[0].resolve()
    assert _bad(plan) == []
    for p in PINS:
        last = _tracks(plan, "N%d" % p)[-1]
        assert _direction(last) == along
    _clear(plan, PINS)


def test_turned_lanes_end_in_vias_that_keep_their_clearance():
    plan = _board(turn=Edge.SOUTH, vias=PINS)[0].resolve()
    assert _bad(plan) == []
    vias = [v for v in plan.copper if isinstance(v, Via) and v.net in {"N%d" % p for p in PINS}]
    assert len(vias) == 3
    for a in vias:
        for b in vias:
            if a is not b:
                assert math.hypot(a.at.x - b.at.x, a.at.y - b.at.y) - (a.size + b.size) / 2 >= CLEAR56 - 1e-6
    for p in PINS:
        last = _tracks(plan, "N%d" % p)[-1]
        via, = [v for v in vias if v.net == "N%d" % p]
        assert (round(last.end.x, 6), round(last.end.y, 6)) == (round(via.at.x, 6), round(via.at.y, 6))


@pytest.mark.parametrize("turn,word", [(Edge.NORTH, "turns back into the row"), (Edge.WEST, "turns back into the row"),
                                       (Corner.SE, "runs along the row's axis")])
def test_a_turn_off_the_way_out_is_refused_when_the_escape_is_declared(turn, word):
    with pytest.raises(ValueError, match=word):
        _board(turn=turn)
