"""Past(items, edge) over any obstacle: cutouts, stretches of the board edge or of a hole, parts' and cells'
envelopes, and labels, as well as pads, vias and tracks. Each item is read as its box; the point stands half the
track's width (a via's radius) plus the pair's rule off each: the net-pair clearance from copper, the copper-to-edge
clearance from a hole or the edge, nothing from an envelope or (for a track) a label. Pure: synthetic boards."""
import dataclasses
import json
import math
import pickle
from pathlib import Path

import pytest

from placemat.board_geometry import Footprint
from placemat.copper import Track, Via
from placemat.cutouts import Circle, Slot
from placemat.finding_text import past_item
from placemat.layout import Board, _past_name
from placemat.settings import Settings
from placemat.values import (Along, Beside, Box, Cell, Centre, CopperLayer, Corner, Cutout, Edge, Face, LabelKey, Location,
                             Near, Net, PadRef, Part, Past, X, Y)
from tests.fixtures import board_geometry, declared_findings, footprint, pad

W3A = 1.37          # a 3 A track on 1 oz outer copper at a 10 C rise (IPC-2221): the width the reported board used
SAG = 0.02          # the setting geometry.arc_sag's default
EDGE = 0.4          # tests.fixtures.board_geometry's copper-to-edge clearance


def _part(ref, inst, net, cx, cy, w=1.0, h=1.0, margin=0.0, face=Face.FRONT):
    """A one-pad part whose body is the pad grown by `margin`, its courtyard 0.1 mm further."""
    p = pad(ref, inst, 1, net, cx, cy, w, h, face=face)
    body = Box(cx - w / 2 - margin, cy - h / 2 - margin, cx + w / 2 + margin, cy + h / 2 + margin)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, face, body, body.inflate(0.1), body, (p,))


def _board(parts=(), holes=(), width=40.0, height=30.0, margin=EDGE, keep_going=False, draw=None, **geom):
    g = board_geometry(list(parts), width=width, height=height, extra_nets=["VBUS", "SIG", "GND"], **geom)
    b = Board(g, edge_margin=margin, keep_going=keep_going)
    b.rect(width=width, height=height, holes=list(holes), draw=draw)
    for fp in parts:
        b.place(Part(fp.inst), at=fp.location, face=fp.face)
    return b


def _points(plan, net):
    return [p for t in plan.copper if isinstance(t, Track) and t.net == net for p in ((t.start.x, t.start.y), (t.end.x, t.end.y))]


def _has(plan, net, x, y):
    return any(abs(px - x) < 1e-6 and abs(py - y) < 1e-6 for px, py in _points(plan, net))


def _vias(plan, net):
    return [op for op in plan.copper if isinstance(op, Via) and op.net == net]


def _away(v, sign):
    """placemat's rounding of a Past point: to 1e-6 mm, away from the items."""
    q = v * 1e6
    return (math.ceil(q - 1e-3) if sign > 0 else math.floor(q + 1e-3)) / 1e6


def _not_drawn(plan):
    return [f for f in plan.findings if f.cause.value == "copper.not_drawn"]


# ---------------------------------------------------------------- declarations
def test_past_takes_a_cutout_a_stretch_of_a_hole_and_a_stretch_of_the_board_edge():
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))
    b = _board(holes=[vent])
    for items, edge in (([vent], Edge.WEST), ([b.cutout("vent")], Edge.NORTH),
                        ([b.cutout("vent").edge(side=Edge.WEST)], Edge.WEST), ([b.edge(facing=Edge.WEST)], Edge.EAST),
                        ([vent, b.edge(facing=Edge.NORTH)], Corner.SE)):
        b.track(Net("SIG"), [Location(2.0, 2.0), Past(items, edge), Location(38.0, 2.0)], layer=CopperLayer.F)


def test_an_item_of_another_kind_is_refused_naming_the_kinds():
    with pytest.raises(TypeError, match="cutouts .*stretches of the board edge"):
        Past([Location(1.0, 2.0)], Edge.EAST)


def test_a_cutout_that_is_not_this_boards_is_refused():
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))
    b = _board(holes=[vent])
    stray = Cutout(Circle(1.5), "stray", at=Location(5.0, 5.0))
    with pytest.raises(TypeError, match="'stray' is not one of this board's named cutouts"):
        b.track(Net("SIG"), [Location(2.0, 2.0), Past([stray], Edge.WEST), Location(2.0, 28.0)], layer=CopperLayer.F)
    other = _board(holes=[Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))])
    with pytest.raises(TypeError, match="another board"):
        b.track(Net("SIG"), [Location(2.0, 2.0), Past([other.cutout("vent")], Edge.WEST), Location(2.0, 28.0)],
                layer=CopperLayer.F)


def test_past_off_a_stretch_of_edge_keeps_to_the_boards_side():
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))
    b = _board(holes=[vent])
    west = b.edge(facing=Edge.WEST)
    Past([west], Edge.EAST)
    Past([west], Corner.NE)                     # its diagonal is 45 degrees off EAST: still the board's side
    with pytest.raises(ValueError, match="its edge is EAST"):
        Past([west], Edge.WEST)
    with pytest.raises(ValueError, match="its edge is EAST"):
        Past([west], Corner.NW)
    with pytest.raises(ValueError, match="its edge is WEST"):
        Past([b.cutout("vent").edge(side=Edge.WEST)], Edge.EAST)      # east of the hole's west side is the hole


def test_across_takes_a_cutout_and_not_a_stretch_of_edge():
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))
    b = _board(holes=[vent])
    Past([vent], Edge.WEST, across=vent)
    Past([vent], Edge.WEST, across=b.cutout("vent"))
    with pytest.raises(TypeError, match="across"):
        Past([vent], Edge.WEST, across=b.edge(facing=Edge.WEST))


# ---------------------------------------------------------------- cutouts
def test_past_a_round_cutout_stands_the_edge_clearance_and_the_arc_allowance_off_its_box():
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))      # box x 19.25..20.75, y 14.25..15.75
    b = _board(holes=[vent])
    b.track(Net("VBUS"), [Location(20.0, 5.0), Past([vent], Edge.WEST), Location(20.0, 25.0)], layer=CopperLayer.B,
            width=W3A)
    plan = b.resolve()
    # 19.25 - 0.02 (the arc's chords) - 0.4 (copper to edge) - 0.685 (half the track) = 18.145, on the hole's centre line
    assert _has(plan, "VBUS", 18.145, 15.0), _points(plan, "VBUS")
    assert not declared_findings(plan), plan.findings


def test_board_cutout_and_a_stretch_of_the_hole_name_the_hole():
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))
    b = _board(holes=[vent])
    b.track(Net("VBUS"), [Location(20.0, 5.0), Past([b.cutout("vent")], Edge.WEST), Location(20.0, 25.0)],
            layer=CopperLayer.B, width=W3A)
    b.via(Net("SIG"), at=Past([b.cutout("vent").edge(side=Edge.EAST)], Edge.EAST), size=0.6)
    plan = b.resolve()
    assert _has(plan, "VBUS", 18.145, 15.0), _points(plan, "VBUS")
    (v,) = _vias(plan, "SIG")
    # the east stretch's box: its eastmost point 20.75 grown by 0.02; 0.4 + the via's 0.3 radius; centred, as the arc is
    assert (v.at.x, v.at.y) == (pytest.approx(21.47, abs=1e-9), pytest.approx(15.0, abs=1e-6))


def test_past_a_slot_north_of_it():
    slot = Cutout(Slot(4.0, 1.5), "slot", at=Location(20.0, 15.0))     # box x 18..22, y 14.25..15.75
    b = _board(holes=[slot])
    b.track(Net("VBUS"), [Location(10.0, 13.145), Past([slot], Edge.NORTH), Location(30.0, 13.145)],
            layer=CopperLayer.B, width=W3A)
    plan = b.resolve()
    assert _has(plan, "VBUS", 20.0, 13.145), _points(plan, "VBUS")       # 14.25 - 0.02 - 0.4 - 0.685


def test_past_a_cutout_with_a_freedom_resolves_where_it_settled():
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, None), why="air")   # free in y: the board slides it
    b = _board(holes=[vent])
    b.via(Net("SIG"), at=Past([vent], Edge.NORTH), size=0.6)
    b.via(Net("VBUS"), at=Past([b.cutout("vent").edge(side=Edge.SOUTH)], Edge.SOUTH), size=0.6)  # a promise until it settles
    plan = b.resolve()
    c = plan.cutouts_placed["vent"].centre
    (v,), (w,) = _vias(plan, "SIG"), _vias(plan, "VBUS")
    assert v.at.x == pytest.approx(c.x, abs=1e-6) and v.at.y == pytest.approx(_away(c.y - 0.75 - SAG - EDGE - 0.3, -1), abs=1e-6)
    assert w.at.x == pytest.approx(c.x, abs=1e-6) and w.at.y == pytest.approx(_away(c.y + 0.75 + SAG + EDGE + 0.3, 1), abs=1e-6)


# ---------------------------------------------------------------- the board edge
def test_past_the_board_edge_stands_inboard_by_the_edge_clearance():
    b = _board()
    b.track(Net("SIG"), [Location(0.5, 2.0), Past([b.edge(facing=Edge.WEST)], Edge.EAST), Location(0.5, 28.0)],
            layer=CopperLayer.F)
    plan = b.resolve()
    assert _has(plan, "SIG", 0.5, 15.0), _points(plan, "SIG")             # 0 + 0.4 + 0.1, the middle of the west side


def test_past_a_curved_stretch_of_a_round_board_takes_its_box_grown_by_the_arc_allowance():
    b = Board(board_geometry([], width=40.0, height=40.0, extra_nets=["SIG"]), edge_margin=EDGE)
    b.disc(30.0)
    rim = b.edge(facing=Edge.WEST)
    box = Box.of_points(rim.points)
    b.via(Net("SIG"), at=Past([rim], Edge.EAST), size=0.6)
    (v,) = _vias(b.resolve(), "SIG")
    assert v.at.x == pytest.approx(_away(box.right + SAG + EDGE + 0.3, 1), abs=1e-9)
    assert v.at.y == pytest.approx(box.top + 0.5 * (box.bottom - box.top), abs=1e-6)


# ---------------------------------------------------------------- items mixed
def test_on_an_edge_the_outer_group_sets_the_point_and_across_a_cutout_its_centre_line():
    def plan_of(across):
        pa = _part("PA", "pa", "GND", 20.0, 10.0)                         # pad box 19.5..20.5, 9.5..10.5
        b = _board([pa], holes=[Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))])
        vent = b._named_cutouts["vent"]
        b.via(Net("SIG"), at=Past([PadRef(Part("pa"), 1), vent], Edge.WEST, across=vent if across else None), size=0.6)
        (v,) = _vias(b.resolve(), "SIG")
        return v.at
    # the pad: 19.5 - 0.2 - 0.3 = 19.0; the hole: 19.25 - 0.02 - 0.4 - 0.3 = 18.53, further out
    on_hole = plan_of(True)
    assert (on_hole.x, on_hole.y) == (pytest.approx(18.53, abs=1e-9), pytest.approx(15.0, abs=1e-6))
    middle = plan_of(False)                                               # the middle of the union, 9.5..15.77
    assert (middle.x, middle.y) == (pytest.approx(18.53, abs=1e-9), pytest.approx(12.635, abs=1e-6))


def test_at_a_corner_each_groups_corner_is_passed_at_least_at_its_own_stand_off():
    pa = _part("PA", "pa", "GND", 20.0, 15.0)                             # pad NE corner (20.5, 14.5), reach 0.3 + 0.2
    vent = Cutout(Circle(1.5), "vent", at=Location(24.0, 15.0))          # grown box NE corner (24.77, 14.23), reach 0.3 + 0.4
    b = _board([pa], holes=[vent])
    b.via(Net("SIG"), at=Past([PadRef(Part("pa"), 1), vent], Corner.NE), size=0.6)
    (v,) = _vias(b.resolve(), "SIG")
    # the union's NE corner is the hole's; the pad's corner stands 4.54 mm behind it along the diagonal, so the
    # hole's reach sets the point: 0.7 / sqrt(2) out on each axis
    d = 0.7 / math.sqrt(2.0)
    assert (v.at.x, v.at.y) == (pytest.approx(_away(24.77 + d, 1), abs=1e-9), pytest.approx(_away(14.23 - d, -1), abs=1e-9))
    for cx, cy, reach in ((20.5, 14.5, 0.5), (24.77, 14.23, 0.7)):        # a 45 through it passes each corner at its reach
        assert ((v.at.x - cx) - (v.at.y - cy)) / math.sqrt(2.0) >= reach - 1e-6


# ---------------------------------------------------------------- not drawn
def test_a_past_off_a_cutout_that_found_no_place_is_not_drawn():
    pa = _part("PA", "pa", "GND", 20.0, 15.0)
    # placed over the part it is placed by: refused (it would mill the part), so it has no place
    vent = Cutout(Circle(1.5), "vent", at=Centre(X(Part("pa")), Y(Part("pa"))), why="air")
    b = _board([pa], holes=[vent], keep_going=True)
    b.track(Net("SIG"), [Location(5.0, 2.0), Past([vent], Edge.NORTH), Location(35.0, 2.0)], layer=CopperLayer.F)
    plan = b.resolve()
    (f,) = _not_drawn(plan)
    assert f.facts["variant"] == "past" and f.facts["names"] == [{"kind": "cutout", "name": "vent"}]
    assert f.facts["why"] == {"code": "past_cutout_unplaced", "name": "vent"}
    assert "cutout vent found no place" in str(f)
    assert not _points(plan, "SIG")


def test_a_past_whose_point_lands_off_the_board_is_not_drawn():
    pa = _part("PA", "pa", "GND", 0.6, 15.0)                              # pad west side at x = 0.1
    b = _board([pa], margin=0.0)
    b.track(Net("SIG"), [Location(5.0, 10.0), Past([PadRef(Part("pa"), 1)], Edge.WEST), Location(5.0, 20.0)],
            layer=CopperLayer.F)
    plan = b.resolve()
    (f,) = _not_drawn(plan)
    assert f.facts["why"] == {"code": "past_off_board", "at": [-0.2, 15.0], "edge": "outside",
                              "names": [{"kind": "pad", "ref": "PA", "number": "1"}]}
    assert "(-0.20, 15.00) lies off the board" in str(f)
    assert not _points(plan, "SIG")


def test_a_fragments_frame_is_no_edge_for_a_past():
    pa = _part("PA", "pa", "GND", 0.6, 15.0)
    b = _board([pa], margin=0.0, draw=False)                              # a module's frame: never written to Edge.Cuts
    b.via(Net("SIG"), at=Past([PadRef(Part("pa"), 1)], Edge.WEST), size=0.6)
    (v,) = _vias(b.resolve(), "SIG")
    assert v.at.x == pytest.approx(-0.4, abs=1e-9)                        # 0.1 - 0.2 - 0.3, past the frame, drawn


def test_a_stretch_of_another_boards_hole_is_refused():
    def board():
        return _board(holes=[Cutout(Circle(1.5), "vent", at=Location(20.0, None), why="air")])
    b, other = board(), board()
    with pytest.raises(TypeError, match="a stretch of cutout 'vent' is another board's"):
        b.via(Net("SIG"), at=Past([other.cutout("vent").edge(side=Edge.SOUTH)], Edge.SOUTH), size=0.6)
    b.via(Net("SIG"), at=Past([b.cutout("vent").edge(side=Edge.SOUTH)], Edge.SOUTH), size=0.6)


# ---------------------------------------------------------------- copper alone, as before
def _copper_only_points():
    """Every point Past gives over pads, vias and tracks alone in one plan: vias' centres and tracks' ends, in plan
    order."""
    pa = _part("PA", "pa", "GND", 10.0, 10.0)
    pb = _part("PB", "pb", "VBUS", 14.0, 12.5, w=1.2, h=0.8)
    b = _board([pa, pb])
    v1 = b.via(Net("GND"), at=Location(20.0, 10.0), size=0.6)
    t1 = b.track(Net("VBUS"), [Location(20.0, 20.0), Location(26.0, 20.0)], layer=CopperLayer.F, width=0.5)
    a, c = PadRef(Part("pa"), 1), PadRef(Part("pb"), 1)
    for p in (Past([a], Edge.EAST), Past([a, c], Edge.NORTH, across=c), Past([v1], Edge.SOUTH),
              Past([t1], Corner.NE), Past([a, v1, t1], Corner.SW), Past([c, v1], Edge.WEST, across=v1),
              Past([t1], Edge.SOUTH, across=Along.END)):
        b.via(Net("SIG"), at=p, size=0.6)
    b.track(Net("SIG"), [Location(2.0, 2.0), Past([a, c], Edge.WEST, across=Along.START), Location(2.0, 28.0)],
            layer=CopperLayer.F, width=0.3)
    b.track(Net("SIG"), [Location(30.0, 26.0), Past([t1, v1], Corner.SE), Location(38.0, 26.0)], layer=CopperLayer.B,
            width=W3A)
    plan = b.resolve()
    return [(op.at.x, op.at.y) if isinstance(op, Via) else ((op.start.x, op.start.y), (op.end.x, op.end.y))
            for op in plan.copper if isinstance(op, (Via, Track)) and op.net == "SIG"]


BEFORE_OBSTACLES = [
    ((2.0, 2.0), (9.15, 9.15)), ((9.15, 9.15), (9.15, 9.5)), ((9.15, 9.5), (9.15, 20.85)), ((9.15, 20.85), (2.0, 28.0)),
    ((30.0, 26.0), (26.87579, 22.87579)), ((26.87579, 22.87579), (26.87579, 20.87579)),
    ((26.87579, 20.87579), (32.0, 26.0)), ((32.0, 26.0), (38.0, 26.0)),
    (11.0, 10.0), (14.0, 9.0), (20.0, 10.805878), (26.603554, 19.396446), (9.146446, 20.603554), (12.9, 10.0),
    (26.25, 20.75)]


def test_past_over_copper_alone_gives_the_points_it_gave_before_obstacles():
    # BEFORE_OBSTACLES: _copper_only_points at b665cc88, the release before Past took obstacles; exactly equal
    assert _copper_only_points() == BEFORE_OBSTACLES


# ---------------------------------------------------------------- parts, cells and labels
def test_past_takes_a_part_a_cell_and_a_label_and_refuses_text():
    b = _board([_part("PA", "pa", "SIG", 10.0, 10.0)])
    key = b.label(Part("pa"), "PA")
    for items, edge in (([Part("pa")], Edge.SOUTH), ([key], Edge.NORTH), ([PadRef(Part("pa"), 1), Part("pa"), key], Corner.NE)):
        b.track(Net("SIG"), [Location(2.0, 2.0), Past(items, edge), Location(38.0, 2.0)], layer=CopperLayer.F)
    with pytest.raises(TypeError, match="Past's items are .*labels"):
        Past(["label pa PA"], Edge.EAST)          # text is not a label: what board.label() returns is
    with pytest.raises(TypeError, match="across"):
        Past([Part("pa")], Edge.WEST, across=key)
    Past([key], Edge.WEST, across=Part("pa"))


def test_a_label_key_is_still_text():
    b = _board([_part("PA", "pa", "SIG", 10.0, 10.0)])
    keys = b.label([Part("pa")], ["PA"])
    assert keys == ["label pa PA"] and all(type(k) is LabelKey for k in keys)
    k = keys[0]
    assert "%s!" % k == "label pa PA!" and {k: 1}["label pa PA"] == 1
    assert json.dumps({k: k}) == '{"label pa PA": "label pa PA"}' and pickle.loads(pickle.dumps(k)) == k


def test_a_label_of_another_board_is_refused():
    a = _board([_part("PA", "pa", "SIG", 10.0, 10.0)])
    b = _board([_part("PA", "pa", "SIG", 10.0, 10.0)])
    key = a.label(Part("pa"), "PA")
    b.label(Part("pa"), "PA")                     # the same text on b: still a's key
    with pytest.raises(TypeError, match="not a label of this board"):
        b.track(Net("SIG"), [Location(2.0, 2.0), Past([key], Edge.NORTH), Location(38.0, 2.0)], layer=CopperLayer.F)


def test_past_a_part_the_pads_clearance_wins_where_the_pad_reaches_nearer_its_courtyard_than_that():
    b = _board([_part("PA", "pa", "GND", 20.0, 15.0, margin=0.0)])        # courtyard west side 19.4, pad west side 19.5
    b.track(Net("SIG"), [Location(19.2, 5.0), Past([Part("pa")], Edge.WEST), Location(19.2, 25.0)], layer=CopperLayer.F)
    plan = b.resolve()
    assert _has(plan, "SIG", 19.2, 15.0), _points(plan, "SIG")             # the pad: 19.5 - 0.2 - 0.1; the courtyard 19.3
    assert not declared_findings(plan), plan.findings


def test_past_a_part_whose_courtyard_reaches_further_stands_on_its_envelope():
    b = _board([_part("PA", "pa", "GND", 20.0, 15.0, margin=0.5)])        # courtyard west side 18.9
    b.track(Net("SIG"), [Location(18.8, 5.0), Past([Part("pa")], Edge.WEST), Location(18.8, 25.0)], layer=CopperLayer.F)
    assert _has(b.resolve(), "SIG", 18.8, 15.0)                           # 18.9 - 0.1, outside the pad's 19.2


def test_a_past_off_a_searched_part_waits_for_it():
    pa = _part("PA", "pa", "GND", 20.0, 15.0, margin=0.5)
    b = Board(board_geometry([pa], width=40, height=30, extra_nets=["SIG"]), edge_margin=EDGE)
    b.rect(width=40.0, height=30.0)
    b.place(Part("pa"))                           # searched: the via is planned after the search, off where pa lands
    b.via(Net("SIG"), at=Past([Part("pa")], Edge.NORTH), size=0.6)
    plan = b.resolve()
    env = b._placed_envelope_box(plan.occupancy, Part("pa"))
    (v,) = _vias(plan, "SIG")
    assert (v.at.x, v.at.y) == (pytest.approx(env.left + 0.5 * (env.right - env.left), abs=1e-6),
                                pytest.approx(_away(env.top - 0.3, -1), abs=1e-9))


def test_across_a_part_puts_the_point_on_its_envelopes_centre_line():
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))
    b = _board([_part("PA", "pa", "GND", 10.0, 10.0)], holes=[vent])
    b.via(Net("SIG"), at=Past([vent], Edge.WEST, across=Part("pa")), size=0.6)
    (v,) = _vias(b.resolve(), "SIG")
    assert (v.at.x, v.at.y) == (pytest.approx(18.53, abs=1e-9), pytest.approx(10.0, abs=1e-6))   # 19.25 - 0.02 - 0.4 - 0.3


def _labelled_board():
    b = _board([_part("PA", "pa", "GND", 20.0, 15.0)], silk_clearance=0.2)
    return b, b.label(Part("pa"), "PA", side=Edge.NORTH)


def test_a_track_stands_on_a_labels_box_and_a_via_keeps_the_silk_clearance():
    b, key = _labelled_board()
    b.track(Net("SIG"), [Location(2.0, 2.0), Past([key], Edge.NORTH), Location(38.0, 2.0)], layer=CopperLayer.F)
    plan = b.resolve()
    box = plan._labelled[key][0].box
    assert _has(plan, "SIG", round(box.left + 0.5 * (box.right - box.left), 6), _away(box.top - 0.1, -1)), (box, _points(plan, "SIG"))
    b, key = _labelled_board()
    b.via(Net("VBUS"), at=Past([key], Edge.EAST), size=0.6)
    plan = b.resolve()
    box = plan._labelled[key][0].box
    (v,) = _vias(plan, "VBUS")
    assert (v.at.x, v.at.y) == (pytest.approx(_away(box.right + 0.3 + 0.2, 1), abs=1e-9),
                                pytest.approx(box.top + 0.5 * (box.bottom - box.top), abs=1e-6))


def _label_board(other: bool):
    """tests/test_label_gives_way.py's board: a labelled connector in cell conn, and cell other placed beside it,
    whose silk the label slides away from."""
    size = (4.4 - 0.15) / (5 * 0.914 + 2 / 9)
    fps = [footprint("J1", 30, 30, w=4, h=2, inst="conn.j1", nets=("A", "B"), cell="conn"),
           footprint("P1", 25, 28, w=4, h=6, inst="conn.p1", nets=("C", "D"), cell="conn"),
           footprint("U2", 0, 0, w=3, h=5, inst="other.u2", nets=("E", "F"), cell="other", silk_boxes=((-1.5, -2.5, 1.5, 2.5),))]
    b = Board(board_geometry(fps, cells=["conn", "other"], width=80, height=80, silk_clearance=0.2, extra_nets=["SIG"]),
              edge_margin=1.0, settings=dataclasses.replace(Settings(), place_envelope="physical"))
    b.place(Cell("conn"), at=Location(27, 28))
    key = b.label(Part("conn.j1"), "USB-C", side=Edge.NORTH, align=Along.START, knockout=True, size=size)
    if other:
        b.place(Cell("other"), at=Beside(Cell("conn"), Edge.EAST, align=Along.START))
    b.via(Net("SIG"), at=Past([key], Edge.NORTH), size=0.6)
    return b, key


def test_a_past_off_a_label_that_gave_way_is_where_the_label_ended():
    still, key = _label_board(other=False)
    moved, _ = _label_board(other=True)
    before = still.resolve()._labelled[key][0].box
    plan = moved.resolve()
    box = plan._labelled[key][0].box
    assert box != before                                                   # the label slid for the other cell's silk
    (v,) = _vias(plan, "SIG")
    assert v.at.y == pytest.approx(_away(box.top - 0.3 - 0.2, -1), abs=1e-9)


def test_a_past_off_a_part_that_found_no_place_or_its_label_is_not_drawn():
    big = _part("BIG", "big", "GND", 20.0, 15.0, w=60.0, h=60.0)          # larger than the board: no place
    b = Board(board_geometry([big], width=40, height=30, extra_nets=["SIG"]), edge_margin=EDGE)
    b.rect(width=40.0, height=30.0)
    b.place(Part("big"))
    key = b.label(Part("big"), "BIG")
    b.via(Net("SIG"), at=Past([Part("big")], Edge.WEST), size=0.6)
    b.via(Net("SIG"), at=Past([key], Edge.WEST), size=0.6)
    whys = sorted(((f.facts["why"]["code"], f.facts["names"]) for f in _not_drawn(b.resolve())), key=lambda w: w[0])
    assert whys == [("past_item_unplaced", [{"kind": "part", "name": "big"}]),
                    ("past_label_not_drawn", [{"kind": "label", "key": "label big BIG"}])], whys


# ---------------------------------------------------------------- the corner verdict
def test_the_corner_verdict_names_the_group_a_leg_passes_too_near():
    pa = _part("PA", "pa", "GND", 10.0, 20.0)                             # pad SE corner (10.5, 20.5), reach 0.3
    vent = Cutout(Circle(1.5), "vent", at=Location(10.0, 23.0))          # grown box SE corner (10.77, 23.77), reach 0.5
    b = _board([pa], holes=[vent])
    px = _away(10.77 + 0.5 / math.sqrt(2.0), 1)
    # due north through the point: the leg passes the hole's corner 0.354 mm off, under its 0.5; the pad's 0.62 off
    b.track(Net("SIG"), [Location(px, 29.0), Past([PadRef(Part("pa"), 1), vent], Corner.SE), Location(px, 5.0)],
            layer=CopperLayer.F, chamfer=0)
    found = [f for f in b.resolve().findings if f.cause.value == "copper.corner"]
    assert len(found) == 1 and found[0].facts["names"] == [{"kind": "cutout", "name": "vent"}], found
    assert found[0].facts["need_mm"] == pytest.approx(EDGE)


def test_the_corner_verdict_measures_a_round_hole_from_its_curve():
    """A round hole's box corner stands outside its curve: a chamfered leg that passes inside the box corner, 1.4 mm clear
    of the hole itself, is no corner finding. Measured from the box corner it was one, 0.28 mm off."""
    vent = Cutout(Circle(6.0), "vent", at=Location(15.0, 12.0))         # box SE corner (18.02, 15.02) grown by the sag
    b = _board(holes=[vent])
    b.track(Net("SIG"), [Location(25.0, 14.9), Location(18.4, 14.9), Past([vent], Corner.SE), Location(10.0, 23.0)],
            layer=CopperLayer.F, chamfer=0.3)
    plan = b.resolve()
    assert any(isinstance(t, Track) and t.net == "SIG" and t.start.x == pytest.approx(18.4) for t in plan.copper)
    assert [f.facts for f in plan.findings if f.cause.value in ("copper.corner", "copper.edge")] == []


@pytest.mark.parametrize("layer, names", [(CopperLayer.F, [[{"kind": "pad", "ref": "PA", "number": "1"}]]),
                                                 (CopperLayer.B, [])], ids=["front", "back"])
def test_a_track_past_a_front_part_takes_its_point_off_the_part_and_is_judged_on_its_own_layer(layer, names):
    b = _board([_part("PA", "pa", "GND", 20.0, 15.0)])                    # front only: pad SE (20.5, 15.5), courtyard SE (20.6, 15.6)
    # the courtyard's corner is the union's; the pad's reach sets the step: (20.5 - 20.6 + 15.5 - 15.6) / 2 + 0.3 / sqrt(2)
    d = max(0.1 / math.sqrt(2.0), -0.1 + 0.3 / math.sqrt(2.0))
    px, py = _away(20.6 + d, 1), _away(15.6 + d, 1)
    b.track(Net("SIG"), [Location(px, 29.0), Past([Part("pa")], Corner.SE), Location(px, 5.0)], layer=layer, chamfer=0)
    plan = b.resolve()
    assert _has(plan, "SIG", px, py), _points(plan, "SIG")               # the same point on either layer
    assert [f.facts["names"] for f in plan.findings if f.cause.value == "copper.corner"] == names


# ---------------------------------------------------------------- the docs
_SKILLS = Path(__file__).resolve().parents[1] / "skills/placemat"


def test_the_skill_api_and_migration_teach_past_over_obstacles_and_copper_edge():
    api = (_SKILLS / "references/api.md").read_text()
    skill = (_SKILLS / "SKILL.md").read_text()
    lane = api.split("**Lane waypoints.**", 1)[1].split("**A part's pad on another pad's edge.**", 1)[0]
    for word in ("cutouts (the `Cutout` given to `holes=`", "board.edge(facing=)", "board.cutout(name).edge(side=)",
                 "parts and cells", "labels", "copper-to-edge clearance", "silk clearance", "lands off the board",
                 "**Copper near a hole or the edge.**", "`copper.edge`", "`copper.meets`"):
        assert word in lane, word
    assert "Past([vent], Edge.WEST)" in api and "Past([board.edge(facing=Edge.WEST)], Edge.EAST)" in api
    assert "the Past takes pads only" not in api
    assert "LabelKey" in api and "copper.edge" in skill and "Past([vent], Edge.WEST)" in skill
    released = (_SKILLS / "references/migration.md").read_text().split("## To 0.99.21", 1)[1].split("\n## To ", 1)[0]
    for word in ("Past passes any obstacle", "past_off_board", "LabelKey", "copper.edge", "copper.meets", "run score"):
        assert word in released, word
    assert all(ord(c) < 128 for c in api + skill + released), "ASCII only"


# ---------------------------------------------------------------- copper that waits for late copper
def _late_via_board():
    """A via past a label: planned after the search, as the label gives way to every part placed after it."""
    b = _board([_part("PA", "pa", "GND", 20.0, 15.0), _part("PB", "pb", "SIG", 6.0, 24.0)], silk_clearance=0.2)
    key = b.label(Part("pa"), "PA", side=Edge.NORTH)
    via = b.via(Net("SIG"), at=Past([key], Edge.EAST), size=0.6)
    return b, via


def _field_board():
    """A field of vias in a pad: planned after the search, as its part's grid gives way to the items placed."""
    b = _board([_part("PA", "pa", "GND", 20.0, 15.0, w=3.0, h=3.0), _part("PB", "pb", "SIG", 6.0, 24.0)])
    field = b.vias(Net("GND"), PadRef(Part("pa"), 1), size=0.6, drill=0.3)
    return b, field


def _drawn_clean(plan, net, *, vias=0, tracks=0):
    assert not _not_drawn(plan), [f.facts for f in _not_drawn(plan)]
    assert len(_vias(plan, net)) == vias
    assert len([t for t in plan.copper if isinstance(t, Track) and t.net == net]) >= tracks


def test_a_track_that_ends_on_a_via_past_a_label_is_drawn():
    b, via = _late_via_board()
    b.track(Net("SIG"), [PadRef(Part("pb"), 1), via], layer=CopperLayer.F)
    _drawn_clean(b.resolve(), "SIG", vias=1, tracks=1)


def test_copper_past_a_via_past_a_label_is_drawn():
    b, via = _late_via_board()
    b.track(Net("VBUS"), [Location(2.0, 28.0), Past([via], Edge.SOUTH), Location(38.0, 28.0)], layer=CopperLayer.F)
    b.via(Net("VBUS"), at=Past([via], Edge.NORTH), size=0.6)
    plan = b.resolve()
    _drawn_clean(plan, "VBUS", vias=1, tracks=1)
    _drawn_clean(plan, "SIG", vias=1)


def test_copper_past_a_field_of_vias_is_drawn():
    b, field = _field_board()
    b.track(Net("SIG"), [Location(2.0, 28.0), Past([field], Edge.SOUTH), Location(38.0, 28.0)], layer=CopperLayer.F)
    b.via(Net("VBUS"), at=Past([field], Edge.NORTH), size=0.6)
    plan = b.resolve()
    _drawn_clean(plan, "SIG", tracks=1)
    _drawn_clean(plan, "VBUS", vias=1)
    assert _vias(plan, "GND")


def test_a_past_names_its_items_as_records():
    """A finding names a Past's items as records, rendered as text only in the finding's message."""
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))
    b = _board([_part("PA", "pa", "GND", 10.0, 10.0)], holes=[vent], margin=0.0)
    via = b.via(Net("SIG"), Location(30.0, 10.0), size=0.6)
    key = b.label(Part("pa"), "PA")
    names = [_past_name(b, it) for it in (vent, b.cutout("vent"), b.edge(facing=Edge.WEST),
                                          Part("pa"), PadRef(Part("pa"), 1), key, via)]
    assert names == [{"kind": "cutout", "name": "vent"}, {"kind": "cutout", "name": "vent"},
                     {"kind": "edge", "facing": 270}, {"kind": "part", "name": "pa"},
                     {"kind": "pad", "ref": "PA", "number": "1"}, {"kind": "label", "key": "label pa PA"},
                     {"kind": "copper", "key": "via SIG"}]
    assert [past_item(n) for n in names] == ["cutout vent", "cutout vent", "edge facing 270", "pa", "PA.1",
                                             "label pa PA", "via SIG"]


def test_the_edge_loops_are_read_once_until_a_cutout_changes_them():
    """`_cutout_box` reads the board's edge loops for every cutout a Past names: they are kept on the board, and read
    again once a hole settles or the outline is declared again."""
    vent = Cutout(Circle(1.5), "vent", at=Location(20.0, None), why="air")   # free in y: settles during the resolve
    b = _board(holes=[vent])
    before = b._edge_loop_info()
    assert b._edge_loop_info() is before and len(before) == 1
    b.via(Net("SIG"), at=Past([vent], Edge.NORTH), size=0.6)
    plan = b.resolve()
    c = plan.cutouts_placed["vent"].centre
    (v,) = _vias(plan, "SIG")
    assert v.at.y == pytest.approx(_away(c.y - 0.75 - SAG - EDGE - 0.3, -1), abs=1e-6)
    assert len(b._edge_loop_info()) == 2
    b.rect(width=40.0, height=30.0)
    assert len(b._edge_loop_info()) == 1
