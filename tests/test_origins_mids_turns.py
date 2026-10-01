"""Origin(item), a part's own pad midpoint (Pin(Mid(k1, k2), ...), Beside's
align), Pin(land=), Parallel and Bearing, and Facing. Pure: synthetic boards."""
import math

import pytest

from placemat.board_geometry import Footprint
from placemat.layout import Board
from placemat.values import (Bearing, Beside, Box, Cell, Edge, Face, Facing, Land, Location, Mid, Origin, PadRef, Parallel,
                             Part, Pin, PinName, Polar, X, Y)
from tests.fixtures import board_geometry, pad


def _part(ref, pads, ox=0.0, oy=0.0, cell=None):
    """A part whose footprint origin is (ox, oy); `pads` are (number, net, dx, dy, w, h) off the origin."""
    inst = ref.lower()
    built = [pad(ref, inst, n, net, ox + dx, oy + dy, w, h) for n, net, dx, dy, w, h in pads]
    body = Box.union([p.box for p in built]).inflate(0.2) if built else Box(ox - 1, oy - 1, ox + 1, oy + 1)
    return Footprint(ref, inst, cell, ref, Location(ox, oy), 0.0, Face.FRONT, body, body.inflate(0.1), body,
                     tuple(built))


def _asym(ref, **kw):
    """Origin at (20, 20), pads at -0.5 and +2.5 from it: its body centre is not its origin."""
    return _part(ref, [(1, "A", -0.5, 0, 1.0, 1.0), (2, "B", 2.5, 0, 1.0, 1.0)], 20.0, 20.0, **kw)


def _board(parts, cells=()):
    return Board(board_geometry(parts, cells=cells, width=80, height=80), edge_margin=1.0, keep_going=True)


def _pad_at(plan, ref, number):
    shapes = [s for s in plan.occupancy.items[ref].shapes if s.kind == "pad" and s.label == str(number)]
    return Box.union([s.box for s in shapes]).center


def _origin(plan, ref):
    return plan.occupancy.items[ref].reference.location


# ------------------------------------------------------------------ Origin

def test_a_part_at_another_parts_origin_stands_its_origin_there():
    b = _board([_asym("A"), _asym("B")])
    b.place(Part("a"), at=Location(30, 40), rotation=90)
    b.place(Part("b"), at=Origin(Part("a")), rotation=0)
    plan = b.resolve()
    assert _origin(plan, "B") == Location(30, 40)


def test_the_part_declared_first_waits_for_the_one_whose_origin_it_stands_on():
    b = _board([_asym("A"), _asym("B")])
    b.place(Part("b"), at=Origin(Part("a")), rotation=0)
    b.place(Part("a"), at=Location(30, 40), rotation=0)
    assert _origin(b.resolve(), "B") == Location(30, 40)


def test_x_of_an_origin_reads_the_origin_not_the_body_centre():
    b = _board([_asym("A"), _asym("B")])
    b.place(Part("a"), at=Location(30, 40), rotation=0)
    b.place(Part("b"), at=Pin(1, X(Origin(Part("a"))), 10.0), rotation=0)
    plan = b.resolve()
    assert _pad_at(plan, "B", 1).x == pytest.approx(30.0)
    assert plan.occupancy.items["A"].body.center.x != pytest.approx(30.0)


def test_an_origin_is_a_point_in_mid_and_polar():
    b = _board([_asym("A"), _asym("B"), _asym("C"), _asym("D")])
    b.place(Part("a"), at=Location(30, 40), rotation=0)
    b.place(Part("b"), at=Location(50, 40), rotation=0)
    b.place(Part("c"), at=Pin(1, Mid(Origin(Part("a")), Origin(Part("b")))), rotation=0)
    b.place(Part("d"), at=Pin(1, Polar(5.0, 90.0, about=Origin(Part("a")))), rotation=0)
    plan = b.resolve()
    assert _pad_at(plan, "C", 1) == Location(40, 40)
    assert _pad_at(plan, "D", 1) == Location(35, 40)


def test_a_cells_origin_is_its_frame_origin_as_placed():
    members = [_part("M1", [(1, "A", 0, 0, 1.0, 1.0)], 40.0, 40.0, cell="c"),
               _part("M2", [(1, "B", 0, 0, 1.0, 1.0)], 44.0, 40.0, cell="c")]
    b = _board(members + [_asym("A")], cells=["c"])
    b.place(Cell("c"), at=Location(20, 30), rotation=0)        # the cell's box centre (42, 40) goes to (20, 30)
    b.place(Part("a"), at=Origin(Cell("c")), rotation=0)
    plan = b.resolve()
    assert _origin(plan, "A") == Location(-22.0, -10.0)        # the stamped frame's (0, 0), carried the same way


def test_an_origin_of_neither_a_part_nor_a_cell_is_refused():
    with pytest.raises(TypeError):
        Origin(PadRef(Part("a"), 1))


# ------------------------------------------------------------------ Pin(Mid(...))

@pytest.mark.parametrize("rotation", [0, 90, 180, 270, 37])
@pytest.mark.parametrize("face", [Face.FRONT, Face.BACK])
def test_the_midpoint_of_two_own_pads_lands_on_the_point(rotation, face):
    b = _board([_asym("Q")])
    b.place(Part("q"), at=Pin(Mid(1, 2), 30.0, 40.0), rotation=rotation, face=face)
    plan = b.resolve()
    a, c = _pad_at(plan, "Q", 1), _pad_at(plan, "Q", 2)
    assert ((a.x + c.x) / 2, (a.y + c.y) / 2) == pytest.approx((30.0, 40.0), abs=1e-5)


def test_the_one_point_form_and_net_keys_say_the_same():
    b = _board([_asym("Q")])
    b.place(Part("q"), at=Pin(Mid("A", "B"), Location(30.0, 40.0)), rotation=90)
    plan = b.resolve()
    a, c = _pad_at(plan, "Q", 1), _pad_at(plan, "Q", 2)
    assert ((a.x + c.x) / 2, (a.y + c.y) / 2) == pytest.approx((30.0, 40.0), abs=1e-5)


def test_a_midpoint_of_a_pad_and_itself_is_refused():
    b = _board([_asym("Q")])
    with pytest.raises(ValueError):
        b.place(Part("q"), at=Pin(Mid(1, 1), 30.0, 40.0))


def test_a_midpoint_of_a_pad_the_part_lacks_is_refused():
    b = _board([_asym("Q")])
    with pytest.raises(KeyError):
        b.place(Part("q"), at=Pin(Mid(1, 9), 30.0, 40.0))


def test_a_pin_land_names_one_land_of_a_pin_drawn_as_several():
    two = _part("Q", [(1, "A", -1.0, 0, 0.5, 0.5), (1, "A", 1.0, 0, 1.0, 1.0), (2, "B", 4.0, 0, 1.0, 1.0)], 20.0, 20.0)

    def lands(b):
        return [s for s in b.resolve().occupancy.items["Q"].shapes if s.kind == "pad" and s.label == "1"]
    for land in (2, Land.LARGEST):
        b = _board([two])
        b.place(Part("q"), at=Pin(1, 30.0, 40.0, land=land), rotation=0)
        assert max(lands(b), key=lambda s: s.box.area).box.center == Location(30.0, 40.0)
    b = _board([two])
    b.place(Part("q"), at=Pin(1, 30.0, 40.0, land=1), rotation=0)
    assert min(lands(b), key=lambda s: s.box.area).box.center == Location(30.0, 40.0)


def test_a_land_past_the_pin_is_refused_and_a_land_with_a_mid_is_refused():
    b = _board([_asym("Q")])
    with pytest.raises(ValueError):
        b.place(Part("q"), at=Pin(1, 30.0, 40.0, land=3))
    with pytest.raises(TypeError):
        Pin(Mid(1, 2), 30.0, 40.0, land=1)


def test_a_pin_by_its_symbol_name_takes_the_pad_it_names():
    b = _board([_asym("Q")])
    b.geometry.pin_names["Q"] = {"1": "IN", "2": "OUT"}
    b.place(Part("q"), at=Pin(PinName("OUT"), 30.0, 40.0), rotation=0)
    assert _pad_at(b.resolve(), "Q", 2) == Location(30.0, 40.0)


# ------------------------------------------------------------------ Beside(align=(Mid(...), ...))

def _target():
    return _part("T", [(1, "X", -3.0, 0, 1.0, 1.0), (2, "Y", 3.0, 0, 1.0, 1.0)], 30.0, 20.0)


def test_beside_lines_the_own_midpoint_up_with_a_point_on_the_other_axis():
    b = _board([_target(), _asym("Q"), _part("W", [(1, "C", 0, 0, 1.0, 1.0)], 50.0, 50.0)])
    b.place(Part("t"), at=Location(30, 20), rotation=0)
    b.place(Part("w"), at=Location(47, 60), rotation=0)
    aim = X(Mid(PadRef(Part("t"), 1), PadRef(Part("w"), 1)))
    b.place(Part("q"), at=Beside(Part("t"), Edge.SOUTH, align=(Mid(1, 2), aim)), rotation=0)
    plan = b.resolve()
    a, c = _pad_at(plan, "Q", 1), _pad_at(plan, "Q", 2)
    assert (a.x + c.x) / 2 == pytest.approx((27.0 + 47.0) / 2, abs=1e-5)
    assert a.y > _pad_at(plan, "T", 1).y


def test_beside_with_a_point_of_the_wrong_axis_is_refused():
    b = _board([_target(), _asym("Q")])
    b.place(Part("t"), at=Location(30, 20), rotation=0)
    with pytest.raises(ValueError):
        b.place(Part("q"), at=Beside(Part("t"), Edge.SOUTH, align=(Mid(1, 2), Y(PadRef(Part("t"), 1)))))


def test_beside_aligns_an_own_pad_on_an_origin():
    b = _board([_target(), _asym("Q")])
    b.place(Part("t"), at=Location(30, 20), rotation=0)
    b.place(Part("q"), at=Beside(Part("t"), Edge.SOUTH, align=(2, Origin(Part("t")))), rotation=0)
    assert _pad_at(b.resolve(), "Q", 2).x == pytest.approx(30.0)


# ------------------------------------------------------------------ Parallel and Bearing

def _line_part():
    """A part with pads 1 and 2 twenty apart in x and 1.3842 in y: a line 3.96 degrees off x."""
    return _part("L", [(1, "A", 0, 0, 1.0, 1.0), (2, "B", 20.0, 1.3842, 1.0, 1.0)], 10.0, 10.0)


def _two_pad(ref="R"):
    return _part(ref, [(1, "C", -1.0, 0, 0.8, 0.8), (2, "D", 1.0, 0, 0.8, 0.8)], 5.0, 5.0)


def _span(plan, ref):
    a, c = _pad_at(plan, ref, 1), _pad_at(plan, ref, 2)
    return a, c, math.hypot(c.x - a.x, c.y - a.y)


_LINE = (20.0 / math.hypot(20.0, 1.3842), 1.3842 / math.hypot(20.0, 1.3842))


def test_a_part_is_turned_to_lie_along_the_line_between_two_pads():
    b = _board([_line_part(), _two_pad()])
    b.place(Part("l"), at=Location(10, 10), rotation=0)
    line = (PadRef(Part("l"), 1), PadRef(Part("l"), 2))
    b.place(Part("r"), at=Location(40, 40), rotation=Parallel(*line))
    plan = b.resolve()
    a, c, n = _span(plan, "R")
    assert ((c.x - a.x) / n, (c.y - a.y) / n) == pytest.approx(_LINE, abs=1e-6)
    want = 360.0 - math.degrees(math.atan(1.3842 / 20.0))
    assert plan.occupancy.items["R"].reference.rotation == pytest.approx(want, abs=1e-4)


def test_degrees_turn_it_further():
    b = _board([_line_part(), _two_pad()])
    b.place(Part("l"), at=Location(10, 10), rotation=0)
    line = (PadRef(Part("l"), 1), PadRef(Part("l"), 2))
    b.place(Part("r"), at=Location(40, 40), rotation=Parallel(*line, degrees=90))
    a, c, n = _span(b.resolve(), "R")
    assert (c.x - a.x) * _LINE[0] + (c.y - a.y) * _LINE[1] == pytest.approx(0.0, abs=1e-5)


def test_on_the_back_face_the_own_x_axis_still_lies_along_the_line():
    b = _board([_line_part(), _two_pad()])
    b.place(Part("l"), at=Location(10, 10), rotation=0)
    line = (PadRef(Part("l"), 1), PadRef(Part("l"), 2))
    b.place(Part("r"), at=Location(40, 40), rotation=Parallel(*line), face=Face.BACK)
    a, c, n = _span(b.resolve(), "R")
    assert ((c.x - a.x) / n, (c.y - a.y) / n) == pytest.approx(_LINE, abs=1e-6)


def test_parallel_waits_for_both_points_and_takes_origins():
    b = _board([_line_part(), _two_pad(), _asym("A")])
    b.place(Part("r"), at=Location(40, 40), rotation=Parallel(Origin(Part("l")), Origin(Part("a"))))
    b.place(Part("a"), at=Location(10, 30), rotation=0)
    b.place(Part("l"), at=Location(10, 10), rotation=0)
    a, c, n = _span(b.resolve(), "R")
    assert (c.x - a.x, c.y - a.y) == pytest.approx((0.0, 2.0), abs=1e-5)    # (10, 10) -> (10, 30): south, +y


def test_parallel_to_its_own_pads_is_refused():
    b = _board([_two_pad()])
    with pytest.raises(ValueError):
        b.place(Part("r"), at=Location(40, 40), rotation=Parallel(PadRef(Part("r"), 1), PadRef(Part("r"), 2)))


def test_parallel_with_rotations_is_refused():
    b = _board([_line_part(), _two_pad()])
    with pytest.raises(ValueError):
        b.place(Part("r"), at=Location(40, 40), rotation=Parallel(Origin(Part("l")), Location(1, 1)), rotations=(0, 90))


def test_bearing_in_polar_is_a_compass_bearing_off_the_line():
    b = _board([_line_part(), _two_pad()])
    b.place(Part("l"), at=Location(10, 10), rotation=0)
    p1, p2 = PadRef(Part("l"), 1), PadRef(Part("l"), 2)
    b.place(Part("r"), at=Pin(1, Polar(3.0, Bearing(p1, p2, 90), about=p1)), rotation=0)
    plan = b.resolve()
    off = _pad_at(plan, "R", 1)
    start, end = _pad_at(plan, "L", 1), _pad_at(plan, "L", 2)
    dx, dy = off.x - start.x, off.y - start.y
    assert math.hypot(dx, dy) == pytest.approx(3.0, abs=1e-5)
    assert dx * (end.x - start.x) + dy * (end.y - start.y) == pytest.approx(0.0, abs=1e-4)
    assert dy > 0                       # a line heading east, 90 on: south


def test_a_bearing_of_two_points_is_a_compass_bearing_with_degrees():
    from placemat.layout import _locate
    b = _board([_asym("A")])
    b.place(Part("a"), at=Location(30, 40), rotation=0)
    occ = b.resolve().occupancy
    north = Polar(2.0, Bearing(Location(0, 10), Location(0, 0)), about=Location(5, 5))
    east = Polar(2.0, Bearing(Location(0, 10), Location(0, 0), 90), about=Location(5, 5))
    assert _locate(b, occ, north) == Location(5, 3)
    assert _locate(b, occ, east) == Location(7, 5)


def test_a_bearing_needs_a_radius():
    b = _board([_two_pad()])
    with pytest.raises(TypeError):
        b.place(Part("r"), at=Polar(None, Bearing(Location(0, 0), Location(1, 0))))


# ------------------------------------------------------------------ Facing

def _qfn(corner=False):
    pads = []
    for k in range(4):                                  # 1-4 west, 5-8 south, 9-12 east, 13-16 north
        t = -1.5 + k
        pads += [(1 + k, "N%d" % (1 + k), -2.5, t, 0.8, 0.3), (5 + k, "N%d" % (5 + k), t, 2.5, 0.3, 0.8),
                 (9 + k, "N%d" % (9 + k), 2.5, -t, 0.8, 0.3), (13 + k, "N%d" % (13 + k), -t, -2.5, 0.3, 0.8)]
    if corner:
        pads.append((17, "N17", -2.5, -2.5, 0.5, 0.5))
    return _part("Q", pads, 30.0, 30.0)


_DIRECTION = {Edge.NORTH: (0, -1), Edge.SOUTH: (0, 1), Edge.EAST: (1, 0), Edge.WEST: (-1, 0)}


def _faces(plan, number, edge):
    c = plan.occupancy.items["Q"].body.center
    p = _pad_at(plan, "Q", number)
    ex, ey = _DIRECTION[edge]
    return (p.x - c.x) * ex + (p.y - c.y) * ey > 2.0 and abs((p.x - c.x) * ey) + abs((p.y - c.y) * ex) < 1.6


@pytest.mark.parametrize("number", [1, 5, 9, 13])
@pytest.mark.parametrize("edge", list(Edge))
def test_facing_turns_a_part_so_a_pads_row_points_at_the_edge(number, edge):
    b = _board([_qfn()])
    b.place(Part("q"), at=Location(30, 30), rotation=Facing(PadRef(Part("q"), number), edge))
    assert _faces(b.resolve(), number, edge)


@pytest.mark.parametrize("edge", list(Edge))
def test_facing_on_the_back_face_is_as_seen_from_the_front(edge):
    b = _board([_qfn()])
    b.place(Part("q"), at=Location(30, 30), face=Face.BACK, rotation=Facing(PadRef(Part("q"), 1), edge))
    assert _faces(b.resolve(), 1, edge)


def test_facing_takes_a_list_of_pads_as_their_row():
    b = _board([_qfn()])
    b.place(Part("q"), at=Location(30, 30),
            rotation=Facing([PadRef(Part("q"), 2), PadRef(Part("q"), 3)], Edge.EAST))
    assert _faces(b.resolve(), 2, Edge.EAST)


def test_facing_is_refused_for_a_corner_pad_naming_it():
    b = _board([_qfn(corner=True)])
    with pytest.raises(ValueError, match="17"):
        b.place(Part("q"), at=Location(30, 30), rotation=Facing(PadRef(Part("q"), 17), Edge.NORTH))


def test_facing_is_refused_for_pads_of_two_rows_naming_them():
    b = _board([_qfn()])
    with pytest.raises(ValueError, match="1.*5|5.*1"):
        b.place(Part("q"), at=Location(30, 30),
                rotation=Facing([PadRef(Part("q"), 1), PadRef(Part("q"), 5)], Edge.NORTH))


def test_facing_pads_of_another_part_are_refused():
    b = _board([_qfn(), _two_pad()])
    with pytest.raises(TypeError):
        b.place(Part("r"), at=Location(30, 30), rotation=Facing(PadRef(Part("q"), 1), Edge.NORTH))


def test_facing_with_rotations_is_refused():
    b = _board([_qfn()])
    with pytest.raises(ValueError):
        b.place(Part("q"), at=Location(30, 30), rotation=Facing(PadRef(Part("q"), 1), Edge.NORTH),
                rotations=(0, 90))


# ------------------------------------------------------------------ at=Mid(a, b)

def test_a_part_at_the_midpoint_of_two_pads_stands_its_origin_there_and_waits_for_them():
    coin = _part("C", [], 5.0, 5.0)
    b = _board([_asym("A"), _asym("B"), coin])
    b.place(Part("c"), at=Mid(PadRef(Part("a"), 1), PadRef(Part("b"), 2)), rotation=0)      # declared before them
    b.place(Part("a"), at=Location(30, 40), rotation=0)
    b.place(Part("b"), at=Location(50, 20), rotation=0)
    plan = b.resolve()
    a, c = _pad_at(plan, "A", 1), _pad_at(plan, "B", 2)
    assert _origin(plan, "C") == Location((a.x + c.x) / 2, (a.y + c.y) / 2)


def test_a_cell_at_a_midpoint_is_placed_as_it_is_at_a_location():
    members = [_part("M1", [(1, "A", 0, 0, 1.0, 1.0)], 10.0, 10.0, cell="c")]
    b = _board(members + [_asym("A"), _asym("B")], cells=["c"])
    b.place(Part("a"), at=Location(30, 40), rotation=0)
    b.place(Part("b"), at=Location(50, 40), rotation=0)
    b.place(Cell("c"), at=Mid(Origin(Part("a")), Origin(Part("b"))), rotation=0)
    plan = b.resolve()
    assert plan.occupancy.items["M1"].body.center == Location(40, 40)
