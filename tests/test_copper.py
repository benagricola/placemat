"""Copper is declared against pads and lanes, and planned after placement
against where the pads actually landed."""
import math

import pytest

from placemat.layout import Board
from placemat.copper import Track, Via, Pour
from placemat.values import (Near, Centre, Box, CopperLayer, Location, Net, Part, PadRef, Priority)
from tests.fixtures import board_geometry, footprint


def make_board():
    fps = [footprint("J1", 5, 5, w=8, h=3, inst="j_in", nets=("V48", "GND")),
           footprint("R1", 20, 20, inst="r1", nets=("V48", "MID")),
           footprint("R2", 25, 20, inst="r2", nets=("MID", "GND")),
           footprint("H1", 40, 40, w=6, h=2, cell="pd", inst="pd.jumper", nets=("CANH", "CANH_S0")),
           footprint("F1", 40, 44, w=6, h=2, cell="pd", inst="pd.fuse", nets=("V48", "FUSE_OUT"))]
    return Board(board_geometry(fps, cells=["pd"], width=100, height=100), edge_margin=1.0)


def test_a_track_between_pads_follows_the_placed_pads():
    b = make_board()
    b.place(Part("r1"), at=Location(30, 30))
    b.place(Part("r2"), at=Location(50, 30))
    b.track(Net("MID"), [PadRef(Part("r1"), "MID"), PadRef(Part("r2"), "MID")], layer=CopperLayer.F)
    plan = b.resolve()
    ops = plan.copper
    assert len(ops) == 1 and isinstance(ops[0], Track)
    t = ops[0]
    assert t.net == "MID" and t.layer is CopperLayer.F
    assert t.start == Location(31.4, 30) and t.end == Location(48.6, 30)     # pad centres after the move
    assert t.width == pytest.approx(0.2)                                     # the net class width


def test_a_pad_reference_with_an_unknown_net_fails_at_declaration():
    b = make_board()
    with pytest.raises(KeyError):
        b.track(Net("NOPE"), [PadRef(Part("r1"), "MID"), Location(0, 0)], layer=CopperLayer.F)
    with pytest.raises(KeyError):
        b.track(Net("MID"), [PadRef(Part("r1"), "NOPE"), Location(0, 0)], layer=CopperLayer.F)


def test_a_polyline_becomes_one_track_per_leg_and_vias_are_ops():
    b = make_board()
    b.track(Net("MID"), [Location(0, 0), Location(5, 0), Location(5, 5)], layer=CopperLayer.B, width=0.5, chamfer=0)
    b.via(Net("MID"), Location(5, 5))
    plan = b.resolve()
    tracks = [o for o in plan.copper if isinstance(o, Track)]
    vias = [o for o in plan.copper if isinstance(o, Via)]
    assert len(tracks) == 2 and all(t.width == 0.5 and t.layer is CopperLayer.B for t in tracks)
    assert len(vias) == 1 and vias[0].at == Location(5, 5) and vias[0].drill == 0.3 and vias[0].size == 0.6


def test_a_pour_is_a_polygon_on_one_layer():
    b = make_board()
    b.pour(Net("V48"), [Location(0, 0), Location(10, 0), Location(10, 4), Location(0, 4)], layer=CopperLayer.F)
    plan = b.resolve()
    p = plan.copper[0]
    assert isinstance(p, Pour) and p.net == "V48" and len(p.points) == 4


def test_fixed_copper_is_planned_before_loose_parts_and_blocks_them():
    b = make_board()
    b.place(Part("j_in"), at=Location(10, 10))
    # a bar the loose part would otherwise settle on
    b.pour(Net("V48"), [Location(20, 18), Location(40, 18), Location(40, 22), Location(20, 22)],
           layer=CopperLayer.F, priority=Priority.FIXED)
    b.place(Part("r2"), at=Near(Location(30, 20), radius=6.0, step=0.5))      # MID/GND: foreign to V48
    plan = b.resolve()
    r2 = plan.box("r2")
    bar = Box(20, 18, 40, 22)
    assert not r2.overlaps(bar.inflate(-0.01)), r2
    order = [s.item for s in plan.steps]
    assert order.index("pour V48") < order.index("r2")


def test_default_copper_is_planned_after_loose_parts():
    b = make_board()
    b.place(Part("r2"), at=Near(Location(30, 20), radius=6.0, step=0.5))
    b.pour(Net("V48"), [Location(20, 18), Location(40, 18), Location(40, 22), Location(20, 22)],
           layer=CopperLayer.F)
    plan = b.resolve()
    order = [s.item for s in plan.steps]
    assert order.index("r2") < order.index("pour V48")


def test_fixed_copper_may_not_reference_a_searched_part():
    b = make_board()
    b.place(Part("r2"), at=Near(Location(30, 20)))
    with pytest.raises(ValueError):
        b.track(Net("MID"), [PadRef(Part("r2"), "MID"), Location(0, 0)], layer=CopperLayer.F,
                priority=Priority.FIXED)


def test_a_cell_pad_reference_follows_the_placed_cell():
    b = make_board()
    from placemat.values import Cell, CellPadRef
    b.place(Cell("pd"), at=Centre(60, 60), rotation=0)
    b.track(Net("CANH"), [CellPadRef(Cell("pd"), net="CANH", ref_prefix="H"), Location(0, 0)],
            layer=CopperLayer.F)
    plan = b.resolve()
    t = plan.copper[0]
    # jumper pad 1 (CANH) sits 2.4 west of the jumper centre; the cell moved by (+20, +18)
    assert t.start == Location(40 - 2.4 + 20, 40 + 18)


def test_a_point_may_mix_a_fixed_coordinate_with_a_pads():
    from placemat.values import X, Y
    b = make_board()
    b.place(Part("r1"), at=Location(30, 30))
    b.track(Net("MID"), [PadRef(Part("r1"), "MID"), (10.0, Y(PadRef(Part("r1"), "MID"))),
                         (X(PadRef(Part("r1"), "MID"), dx=1.0), 50.0)], layer=CopperLayer.F, chamfer=0)
    plan = b.resolve()
    t1, t2, t3 = plan.copper                            # the second leg is off the 45 grid: a 45 and a straight
    assert t1.end == Location(10.0, 30.0)
    assert t3.end == Location(31.4 + 1.0, 50.0)


def test_a_finger_band_may_be_placed_around_a_pads_y():
    from placemat.copper import Pour
    from placemat.values import X, Y
    b = make_board()
    b.place(Part("r1"), at=Location(30, 30))
    pad = PadRef(Part("r1"), "MID")
    b.finger(Net("V48"), layer=CopperLayer.F, from_=(60.0, Y(pad)), to=(X(pad, 2.0), Y(pad)), width=6.0)
    plan = b.resolve()
    p = [o for o in plan.copper if isinstance(o, Pour)][0]
    ys = sorted({y for _, y in p.points})
    xs = sorted({x for x, _ in p.points})
    assert ys == [27.0, 33.0] and xs == [33.4, 60.0]


def test_a_tracks_right_angle_corner_is_chamfered_at_45_unless_told_not():
    """Two 45s survive vibration better than one 90: every right-angle
    corner of a track becomes a chamfer, `chamfer=0` keeps the corner."""
    b = make_board()
    b.place(Part("r1"), at=Location(30, 30))
    b.track(Net("MID"), [PadRef(Part("r1"), "MID"), (40.0, 30.0), (40.0, 40.0)], layer=CopperLayer.F, width=0.3)
    plan = b.resolve()
    legs = [op for op in plan.copper if isinstance(op, Track)]
    diag = [t for t in legs if abs(abs(t.end.x - t.start.x) - abs(t.end.y - t.start.y)) < 1e-9 and t.start != t.end]
    assert len(legs) == 3 and len(diag) == 1
    assert diag[0].start == Location(39.0, 30.0) and diag[0].end == Location(40.0, 31.0)      # 1 mm legs
    b = make_board()
    b.place(Part("r1"), at=Location(30, 30))
    b.track(Net("MID"), [PadRef(Part("r1"), "MID"), (40.0, 30.0), (40.0, 40.0)], layer=CopperLayer.F, width=0.3, chamfer=0)
    assert len([op for op in b.resolve().copper if isinstance(op, Track)]) == 2


def test_a_track_leg_off_the_45_grid_becomes_a_45_and_a_straight():
    """KiCad draws at 0, 45 and 90 only; so does placemat. A leg between two
    points at an odd angle leaves the first point at 45 and runs straight
    from there."""
    b = make_board()
    b.track(Net("MID"), [Location(0, 0), Location(10, 3)], layer=CopperLayer.F, width=0.3)
    legs = [op for op in b.resolve().copper if isinstance(op, Track)]
    assert [(t.start, t.end) for t in legs] == [(Location(0, 0), Location(3, 3)), (Location(3, 3), Location(10, 3))]
    b = make_board()
    b.track(Net("MID"), [Location(0, 0), Location(10, 10)], layer=CopperLayer.F, width=0.3)
    assert len([op for op in b.resolve().copper if isinstance(op, Track)]) == 1        # a true 45 is one leg
    b = make_board()
    b.place(Part("r1"), at=Location(30, 30))
    b.track(Net("MID"), [Location(20, 40), PadRef(Part("r1"), "MID")], layer=CopperLayer.F, width=0.3)
    legs = [op for op in b.resolve().copper if isinstance(op, Track)]
    assert legs[-1].start.distance(legs[-1].end) == pytest.approx(10 * math.sqrt(2)) and legs[-1].end == Location(31.4, 30)   # arriving at a pad: the 45 is last


def test_an_off_grid_leg_is_split_the_way_that_turns_least():
    """Every turn costs signal integrity. Leaving a pad vertically and then
    heading for another pad up and to the right: the 45 goes next to the
    turn, so the track is vertical, 45, horizontal (two turns), not
    vertical, chamfered right angle, 45 (three)."""
    b = make_board()
    b.track(Net("MID"), [Location(0, 0), Location(0, -2.5), Location(6.75, -5.3)], layer=CopperLayer.F, width=0.3)
    legs = [op for op in b.resolve().copper if isinstance(op, Track)]
    assert [(t.start, t.end) for t in legs] == [(Location(0, 0), Location(0, -2.5)),
                                                (Location(0, -2.5), Location(2.8, -5.3)),
                                                (Location(2.8, -5.3), Location(6.75, -5.3))]
    # and the mirror case: arriving along an axis, the 45 goes next to that turn too
    b = make_board()
    b.track(Net("MID"), [Location(6.75, -5.3), Location(0, -2.5), Location(0, 0)], layer=CopperLayer.F, width=0.3)
    legs = [op for op in b.resolve().copper if isinstance(op, Track)]
    assert [(t.start, t.end) for t in legs] == [(Location(6.75, -5.3), Location(2.8, -5.3)),
                                                (Location(2.8, -5.3), Location(0, -2.5)),
                                                (Location(0, -2.5), Location(0, 0))]


def test_the_fewest_turn_split_yields_to_a_pad_in_its_way():
    """The turn-saving order is only taken when its legs clear every pad of
    another net; if they would clip one (a neighbouring pin), the other
    order is drawn."""
    from placemat.board_geometry import Footprint
    from placemat.values import Box, Face, X, Y
    from tests.fixtures import pad, footprint
    pins = (pad("U1", "u1", 1, "A", 42.3, 14.2, 3.0, 3.0, True), pad("U1", "u1", 2, "B", 47.4, 14.2, 3.0, 3.0, True))
    body = Box(38.0, 8.0, 52.0, 16.0)
    conn = Footprint("U1", "u1", None, "U1", Location(44.85, 12.0), 0.0, Face.FRONT, body, body, body, pins)
    jumper = footprint("H1", 42.8, 19.5, w=4, h=2, inst="h1", nets=("B", "C"), through=True)     # pad B at (41.4, 19.5), under pin A
    b = Board(board_geometry([conn, jumper], width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(44.85, 12.0))
    b.place(Part("h1"), at=Location(42.8, 19.5))
    hb, ub = PadRef(Part("h1"), "B"), PadRef(Part("u1"), "B")
    b.track(Net("B"), [hb, (X(hb), Y(hb, -2.5)), ub], layer=CopperLayer.F, width=0.3)
    legs = [op for op in b.resolve().copper if isinstance(op, Track)]
    last = legs[-1]
    assert abs(abs(last.end.x - last.start.x) - abs(last.end.y - last.start.y)) < 1e-9 and last.end == Location(47.4, 14.2)
    assert all(t.start.x >= 43.8 + 0.2 or t.start.y >= 15.7 + 0.2 for t in legs)           # nothing inside pin A's pad


def test_a_waypoint_that_forces_a_track_into_a_pad_is_named():
    """When a track with waypoints hits a pad of another net and the same
    track drawn pad to pad would clear, the finding says so: the waypoint is
    the defect, not the geometry."""
    from placemat.board_geometry import Footprint
    from placemat.values import Box, Face, X, Y
    from tests.fixtures import pad, footprint
    pins = (pad("U1", "u1", 1, "A", 42.3, 14.2, 3.0, 3.0, True), pad("U1", "u1", 2, "B", 47.4, 14.2, 3.0, 3.0, True))
    body = Box(38.0, 8.0, 52.0, 16.0)
    conn = Footprint("U1", "u1", None, "U1", Location(44.85, 12.0), 0.0, Face.FRONT, body, body, body, pins)
    jumper = footprint("H1", 42.8, 19.5, w=4, h=2, inst="h1", nets=("B", "C"), through=True)
    b = Board(board_geometry([conn, jumper], width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(44.85, 12.0))
    b.place(Part("h1"), at=Location(42.8, 19.5))
    hb, ub = PadRef(Part("h1"), "B"), PadRef(Part("u1"), "B")
    b.track(Net("B"), [hb, (X(hb), Y(hb, -1.0)), (X(hb, 2.0), Y(hb, -4.0)), ub], layer=CopperLayer.F, width=0.3)   # a waypoint inside pin A's pad
    plan = b.resolve()
    assert any("waypoint" in f and "pad to pad" in f for f in plan.findings), plan.findings


def _pin_board():
    """Two pins in a row and a jumper pad under the first: the case where the
    straight shot from the jumper to the far pin clips the near pin."""
    from placemat.board_geometry import Footprint
    from placemat.values import Box, Face
    from tests.fixtures import pad, footprint
    pins = (pad("U1", "u1", 1, "A", 42.3, 14.2, 3.0, 3.0, True), pad("U1", "u1", 2, "B", 47.4, 14.2, 3.0, 3.0, True))
    body = Box(38.0, 8.0, 52.0, 16.0)
    conn = Footprint("U1", "u1", None, "U1", Location(44.85, 12.0), 0.0, Face.FRONT, body, body, body, pins)
    jumper = footprint("H1", 43.7, 19.5, w=4, h=2, inst="h1", nets=("B", "C"), through=True)   # pad B at (42.3, 19.5): straight under pin A
    b = Board(board_geometry([conn, jumper], width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(44.85, 12.0))
    b.place(Part("h1"), at=Location(43.7, 19.5))
    return b


def test_a_leg_is_routed_round_a_pad_in_its_way_with_the_fewest_turns():
    """Pad to pad, no waypoint: the direct 45 would clip pin A, so the tool
    tries the octilinear candidates and keeps the clear one with the fewest
    turns and then the shortest length."""
    b = _pin_board()
    hb, ub = PadRef(Part("h1"), "B"), PadRef(Part("u1"), "B")
    b.track(Net("B"), [hb, ub], layer=CopperLayer.F, width=0.3)
    plan = b.resolve()
    legs = [op for op in plan.copper if isinstance(op, Track)]
    assert not plan.findings
    assert legs[0].start == Location(42.3, 19.5) and legs[-1].end == Location(47.4, 14.2)
    assert len(legs) <= 4                                              # three legs, or a chamfered two
    for t in legs:                                                     # every leg on the 45 grid
        dx, dy = abs(t.end.x - t.start.x), abs(t.end.y - t.start.y)
        assert dx < 1e-9 or dy < 1e-9 or abs(dx - dy) < 1e-9


def test_the_candidate_with_the_fewest_turns_wins_then_the_shortest():
    from placemat.copper import route_leg
    # open board: (0,0) to (10,4). Candidates with one turn: 45-then-straight or straight-then-45; both 1 turn, equal length
    pts = route_leg(Location(0, 0), Location(10, 4), False, False, None, None, lambda a, b: True)
    assert len(pts) == 3
    # arriving horizontally at the far end is needed next: the straight should come last
    pts = route_leg(Location(0, 0), Location(10, 4), False, False, None, (1, 0), lambda a, b: True)
    assert pts[1] == Location(4, 4)
