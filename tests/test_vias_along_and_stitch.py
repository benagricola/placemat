"""board.vias(net, along=PadRef(...), count=N): a row of vias out from a
pad along its escape axis, at the via-to-via rule. board.stitch(net,
region, pitch=None): stitching vias over a cell, a pour or a keepout's
region at the rule pitch, clear of other nets' copper. Pure."""
import pytest

from placemat.copper import Via
from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.values import Box, Cell, Centre, CopperLayer, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _vias(plan):
    return [o for o in plan.copper if isinstance(o, Via)]


def _u1():
    return footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B"))


def test_vias_along_a_pads_axis_march_out_at_the_via_to_via_rule():
    b = Board(board_geometry([_u1()], width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(20, 20))
    b.vias(Net("A"), along=PadRef(Part("u1"), "A"), count=3, size=0.6, drill=0.3)
    plan = b.resolve()
    vias = _vias(plan)
    xs = sorted((round(v.at.x, 6) for v in vias), reverse=True)
    assert xs == [17.8, 17.2, 16.6]                  # west of pad A: half (0.5) + size/2 (0.3), then 0.6 mm apart
    assert all(v.at.y == 20.0 for v in vias)
    assert all(v.drill == 0.3 and v.size == 0.6 for v in vias)


def test_vias_along_are_joined_to_their_pad_by_a_tail():
    """A via standing just clear of the pad's tip touches it at one point at
    most, which KiCad counts as unconnected: the row is joined to its pad by a
    track at the net's width, from the pad out to the farthest via."""
    from placemat.copper import Track
    b = Board(board_geometry([_u1()], width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(20, 20))
    b.vias(Net("A"), along=PadRef(Part("u1"), "A"), count=1, size=0.6, drill=0.3)
    plan = b.resolve()
    (via,) = _vias(plan)
    tails = [o for o in plan.copper if isinstance(o, Track) and o.net == "A"]
    assert len(tails) == 1, tails
    t = tails[0]
    pad = plan.occupancy.pad_location("U1", "1")
    assert {(round(t.start.x, 6), round(t.start.y, 6)), (round(t.end.x, 6), round(t.end.y, 6))} == {
        (round(pad.x, 6), round(pad.y, 6)), (round(via.at.x, 6), round(via.at.y, 6))}


def test_a_track_can_end_on_a_row_of_vias_along_a_pad():
    """The intent vias(along=) returns stands for the row's farthest via, as
    one via() does for its own: a track given it as a point ends there."""
    from placemat.copper import Track
    b = Board(board_geometry([_u1()], width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(20, 20))
    row = b.vias(Net("A"), along=PadRef(Part("u1"), "A"), count=2, size=0.6, drill=0.3)
    b.track(Net("A"), [row, Location(17.2, 30.0)], layer=CopperLayer.B, chamfer=0)
    plan = b.resolve()
    assert not any("lost" in f or "no via" in f for f in plan.findings), plan.findings
    legs = [o for o in plan.copper if isinstance(o, Track) and o.layer is CopperLayer.B]
    assert legs and legs[0].start == Location(17.2, 20.0), legs


def test_vias_along_stops_and_notes_when_the_row_runs_off_the_board():
    # pad A (the west pad) at x=4.6; vias march west from it (3.8, 3.2, ..., 0.8):
    # the 1.0 mm keep-in stops the last of 6 short (0.8 - 0.3 < 1.0)
    fp = footprint("U1", 6.0, 20.0, w=4, h=2, inst="u1", nets=("A", "B"))
    b = Board(board_geometry([fp], width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(6.0, 20))
    b.vias(Net("A"), along=PadRef(Part("u1"), "A"), count=6, size=0.6, drill=0.3)
    plan = b.resolve()
    vias = _vias(plan)
    assert 0 < len(vias) < 6
    assert any("along" in f and "U1.1" in f for f in plan.findings), plan.findings


def test_vias_needs_exactly_one_of_pad_or_along():
    b = Board(board_geometry([_u1()], width=60, height=60), edge_margin=1.0)
    with pytest.raises(TypeError):
        b.vias(Net("A"))
    with pytest.raises(TypeError):
        b.vias(Net("A"), PadRef(Part("u1"), "A"), along=PadRef(Part("u1"), "A"), count=2)


def test_vias_along_needs_a_positive_count():
    b = Board(board_geometry([_u1()], width=60, height=60), edge_margin=1.0)
    with pytest.raises(ValueError, match="count"):
        b.vias(Net("A"), along=PadRef(Part("u1"), "A"), count=0)


def test_vias_along_refuses_inset_it_has_no_pad_to_keep_inside():
    b = Board(board_geometry([_u1()], width=60, height=60), edge_margin=1.0)
    with pytest.raises(ValueError, match="inset"):
        b.vias(Net("A"), along=PadRef(Part("u1"), "A"), count=2, inset=0.1)


# ---------------------------------------------------------------- stitch()
def test_stitch_fills_a_cell_with_vias_clear_of_the_other_net():
    fp = footprint("H1", 20, 20, w=4, h=2, cell="pd", inst="pd.h1", nets=("GND", "OTHER"))
    b = Board(board_geometry([fp], cells=["pd"], width=60, height=60), edge_margin=1.0)
    b.place(Cell("pd"), at=Centre(20, 20), rotation=0)
    b.stitch(Net("GND"), Cell("pd"), size=0.6, drill=0.3, pitch=1.0)
    plan = b.resolve()
    vias = _vias(plan)
    assert vias
    assert all(18.0 <= v.at.x <= 22.0 and 19.0 <= v.at.y <= 21.0 for v in vias)
    assert all(v.net == "GND" for v in vias)


def test_stitch_fills_a_keepouts_region_with_vias():
    b = Board(board_geometry([], width=60, height=60, extra_nets=["GND"]), edge_margin=1.0, keep_going=True)
    b.keepout(Circle(6.0), "shield", at=Location(30, 30), excludes=["parts"], why="probe")
    b.stitch(Net("GND"), "shield", size=0.6, drill=0.3, pitch=1.5)
    plan = b.resolve()
    vias = _vias(plan)
    assert vias
    assert all(v.at.distance(Location(30, 30)) <= 3.0 + 1e-6 for v in vias)


def test_stitch_fills_a_pours_region_with_vias():
    b = Board(board_geometry([], width=60, height=60, extra_nets=["GND"]), edge_margin=1.0, keep_going=True)
    p = b.pour(Net("GND"), [Location(10, 10), Location(20, 10), Location(20, 16), Location(10, 16)],
              layer=CopperLayer.F)
    b.stitch(Net("GND"), p, size=0.6, drill=0.3, pitch=1.5)
    plan = b.resolve()
    vias = _vias(plan)
    assert vias
    assert all(10.0 <= v.at.x <= 20.0 and 10.0 <= v.at.y <= 16.0 for v in vias)


def test_stitch_refuses_a_copper_intent_that_is_not_a_pour():
    b = Board(board_geometry([], width=60, height=60, extra_nets=["GND"]), edge_margin=1.0, keep_going=True)
    v = b.via(Net("GND"), Location(30.0, 30.0))
    with pytest.raises(TypeError):
        b.stitch(Net("GND"), v)


def test_stitch_refuses_an_unknown_keepout_name():
    b = Board(board_geometry([], width=60, height=60, extra_nets=["GND"]), edge_margin=1.0, keep_going=True)
    with pytest.raises(KeyError):
        b.stitch(Net("GND"), "nope")


def test_stitch_refuses_a_pitch_under_the_hole_to_hole_rule():
    b = Board(board_geometry([], width=60, height=60, extra_nets=["GND"]), edge_margin=1.0, keep_going=True)
    b.keepout(Circle(6.0), "shield", at=Location(30, 30), excludes=["parts"], why="probe")
    with pytest.raises(ValueError, match="hole-to-hole"):
        b.stitch(Net("GND"), "shield", size=0.4, drill=0.3, pitch=0.4)


def test_stitch_refuses_a_keepouts_default_excludes_that_forbid_vias():
    """The default excludes forbid vias: planning would find nowhere for one
    to stand and just say "no via fits ... at a pitch". Refused up front,
    naming the keepout's own exclusion, is a clearer message."""
    b = Board(board_geometry([], width=60, height=60, extra_nets=["GND"]), edge_margin=1.0, keep_going=True)
    b.keepout(Circle(6.0), "shield", at=Location(30, 30), why="probe")     # default excludes: vias forbidden
    with pytest.raises(ValueError, match="vias"):
        b.stitch(Net("GND"), "shield")


def test_stitch_refuses_a_pours_region_of_another_net():
    b = Board(board_geometry([], width=60, height=60, extra_nets=["GND", "OTHER"]), edge_margin=1.0, keep_going=True)
    p = b.pour(Net("OTHER"), [Location(10, 10), Location(20, 10), Location(20, 16), Location(10, 16)],
              layer=CopperLayer.F)
    with pytest.raises(ValueError, match="OTHER"):
        b.stitch(Net("GND"), p)


def test_stitch_edge_rows_vias_along_a_regions_outline():
    """stitch(..., edge=True): a row of vias along the region's own outline
    at the pitch, a via's clearance inside it - not a grid over the whole
    interior (the audit's real case: GnssAntenna_layout.py's stitching vias,
    "at most 2 mm apart and 0.35 mm from the ground's edge, along two sides
    of the clearance")."""
    b = Board(board_geometry([], width=60, height=60, extra_nets=["GND"]), edge_margin=1.0, keep_going=True)
    p = b.pour(Net("GND"), [Location(10, 10), Location(30, 10), Location(30, 26), Location(10, 26)],
              layer=CopperLayer.F)
    b.stitch(Net("GND"), p, size=0.6, drill=0.3, pitch=2.0, edge=True)
    plan = b.resolve()
    vias = _vias(plan)
    assert vias
    inset = 0.6 / 2.0 + 0.2                     # via radius + the board's own netclass clearance
    box = Box(10.0, 10.0, 30.0, 26.0)
    sides = set()
    for v in vias:
        dists = {"left": v.at.x - box.left, "right": box.right - v.at.x,
                "top": v.at.y - box.top, "bottom": box.bottom - v.at.y}
        nearest, dist = min(dists.items(), key=lambda kv: kv[1])
        assert abs(dist - inset) < 1e-6, (v.at, dists)          # sits the inset in from its own side, not scattered
        sides.add(nearest)
    assert len(sides) >= 2                                      # it goes around the outline, not just one side


def test_stitch_over_a_keepout_that_lets_its_net_in_is_not_refused():
    """A keepout that excludes vias but allows the stitching net (allow=
    holds Net(...)s) lets the stitch stand: the check compared the net's
    name with the Net objects and never matched."""
    b = Board(board_geometry([], width=60, height=60, extra_nets=["GND"]), edge_margin=1.0, keep_going=True)
    b.keepout(Circle(6.0), "shield", at=Location(30, 30), allow=(Net("GND"),), why="probe")
    b.stitch(Net("GND"), "shield", size=0.6, drill=0.3, pitch=1.5)
    assert _vias(b.resolve())


# ------------------------------------------------- stitch(edge=True, outside=True)
RECT = [(0.0, 0.0), (10.0, 0.0), (10.0, 6.0), (0.0, 6.0)]       # centred on (30, 30): x 25..35, y 27..33


def _outside_board(parts=(), **kw):
    from placemat.cutouts import Path
    b = Board(board_geometry(list(parts), width=60, height=60, extra_nets=["GND", "OTHER"]),
              edge_margin=1.0, keep_going=True)
    b.keepout(Path(RECT), "clearance", at=Location(30, 30), why="probe", **kw)
    return b


def _row(vias, axis, value):
    """The vias whose `axis` coordinate is `value`, sorted along the other one."""
    other = "y" if axis == "x" else "x"
    return sorted(round(getattr(v.at, other), 6) for v in vias if abs(getattr(v.at, axis) - value) < 1e-4)


def test_stitch_outside_rows_two_sides_off_the_edge_with_a_shared_corner():
    from placemat.values import Edge
    b = _outside_board()
    b.stitch(Net("GND"), "clearance", edge=True, outside=True, hole_to_edge=0.35, pitch=2.0,
             sides=[Edge.EAST, Edge.SOUTH], size=0.6, drill=0.3, why="probe")
    plan = b.resolve()
    vias = _vias(plan)
    # a hole edge 0.35 off the edge puts its centre 0.35 + 0.15 out
    east, south = _row(vias, "x", 35.5), _row(vias, "y", 33.5)
    # the north and west sides are not kept: a row ends 0.5 in from them, and runs out to the shared corner
    assert east == [27.5, 29.5, 31.5, 33.5]                     # 6 mm: ceil(6 / 2) + 1 = 4 vias
    assert south == [25.5, 27.5, 29.5, 31.5, 33.5, 35.5]        # 10 mm: ceil(10 / 2) + 1 = 6 vias
    assert len(vias) == len(set((v.at.x, v.at.y) for v in vias)) == 4 + 6 - 1     # the corner via is shared
    assert not [v for v in vias if abs(v.at.x - 35.5) > 1e-6 and abs(v.at.y - 33.5) > 1e-6]     # none on the others
    for row in (east, south):
        assert max(b - a for a, b in zip(row, row[1:])) <= 2.0 + 1e-9
    assert not any("stitch" in str(f) and "-> board" not in str(f) for f in plan.findings), plan.findings


def test_stitch_outside_default_hole_to_edge_lets_the_copper_touch_the_edge_from_outside():
    from placemat.values import Edge
    b = _outside_board()
    b.stitch(Net("GND"), "clearance", edge=True, outside=True, pitch=2.0, sides=[Edge.WEST],
             size=0.6, drill=0.3, why="probe")
    plan = b.resolve()
    vias = _vias(plan)
    assert vias, plan.findings
    # the centre is half the via's size out: the via is judged as a 16-gon whose corners stand 0.006 mm past its circle
    # the row stands in from the unkept north and south sides by the same 0.306, so it spans 27.306 to 32.694
    assert sorted(round(v.at.y, 6) for v in vias) == [27.305878, 29.101959, 30.898041, 32.694122]
    assert all(24.69 < v.at.x < 24.70 for v in vias), [v.at.x for v in vias]


def test_stitch_outside_every_edge_by_default_with_four_shared_corners():
    b = _outside_board()
    b.stitch(Net("GND"), "clearance", edge=True, outside=True, hole_to_edge=0.35, pitch=2.0,
             size=0.6, drill=0.3, why="probe")
    plan = b.resolve()
    assert len(_vias(plan)) == 2 * 5 + 2 * 7 - 4         # 7 mm sides: 5 vias, 11 mm sides: 7; four corners shared
    xs = [(round(v.at.x, 6), round(v.at.y, 6)) for v in _vias(plan)]
    assert len(xs) == len(set(xs))
    for corner in ((24.5, 26.5), (35.5, 26.5), (35.5, 33.5), (24.5, 33.5)):
        assert corner in xs


def test_stitch_outside_reads_sides_in_a_turned_keepouts_frame():
    from placemat.cutouts import Path
    from placemat.values import Edge, Turned
    ant = footprint("ANT", 10, 10, w=4, h=2, inst="ant", nets=("A", "B"))
    b = Board(board_geometry([ant], width=60, height=60, extra_nets=["GND"]), edge_margin=1.0, keep_going=True)
    b.place(Part("ant"), at=Location(10, 10), rotation=90)
    b.keepout(Path(RECT), "clearance", at=Location(30, 30), rotation=Turned(Part("ant"), 0), why="probe")
    b.stitch(Net("GND"), "clearance", edge=True, outside=True, hole_to_edge=0.35, pitch=2.0,
             sides=[Edge.EAST], size=0.6, drill=0.3, why="probe")
    plan = b.resolve()
    vias = _vias(plan)
    # the part's east is the board's north once it turns 90 degrees: the keepout is 6 wide, 10 tall
    assert sorted((round(v.at.x, 6), round(v.at.y, 6)) for v in vias) == [(27.5, 24.5), (29.166667, 24.5), (30.833333, 24.5), (32.5, 24.5)]


def test_stitch_outside_leaves_out_a_via_another_nets_pad_blocks_and_finds_the_gap():
    from placemat.values import Edge
    other = footprint("T1", 37.0, 29.0, w=4, h=2, inst="t1", nets=("OTHER", "OTHER"))      # its pad 1 at x 35.1..36.1
    b = _outside_board([other])
    b.place(Part("t1"), at=Location(37.0, 29.0))
    b.stitch(Net("GND"), "clearance", edge=True, outside=True, hole_to_edge=0.35, pitch=2.0,
             sides=[Edge.EAST], size=0.6, drill=0.3, why="probe")
    plan = b.resolve()
    ys = _row(_vias(plan), "x", 35.5)
    assert ys == [27.5, 30.833333, 32.5], ys            # the via at y=29.17 would sit 0.19 mm from the pad
    said = [str(f) for f in plan.findings if "stitch GND" in str(f)]
    assert any("(35.50, 29.17)" in t and "copper" in t for t in said), said
    assert any("east side" in t and "3.33 mm gap" in t and "2.00 mm pitch" in t for t in said), said


def test_stitch_outside_without_edge_is_refused():
    b = _outside_board()
    with pytest.raises(ValueError, match="edge=True"):
        b.stitch(Net("GND"), "clearance", outside=True, pitch=2.0)


def test_stitch_sides_and_hole_to_edge_without_outside_are_refused():
    from placemat.values import Edge
    b = _outside_board()
    with pytest.raises(ValueError, match="outside"):
        b.stitch(Net("GND"), "clearance", edge=True, sides=[Edge.EAST])
    with pytest.raises(ValueError, match="outside"):
        b.stitch(Net("GND"), "clearance", edge=True, hole_to_edge=0.3)


def test_stitch_outside_an_l_shaped_region_crosses_at_a_reflex_corner():
    from placemat.cutouts import Path
    b = Board(board_geometry([], width=60, height=60, extra_nets=["GND"]), edge_margin=1.0, keep_going=True)
    b.keepout(Path([(0, 0), (6, 0), (6, 3), (3, 3), (3, 6), (0, 6)]), "l", at=Location(30, 30), why="probe")
    b.stitch(Net("GND"), "l", edge=True, outside=True, hole_to_edge=0.35, pitch=2.0, size=0.6, drill=0.3, why="probe")
    pts = {(round(v.at.x, 6), round(v.at.y, 6)) for v in _vias(b.resolve())}
    # the inner corner is at (30, 30) in the keepout's box; the offset lines cross 0.5 out along both normals
    assert (30.5, 30.5) in pts


def _edge_board(margin=0.1):
    """A turned keepout (the part is turned 90 degrees: its east is the board's north, its north the board's
    west) 6 wide and 10 tall, its board-west side on the board edge."""
    from placemat.cutouts import Path
    from placemat.values import Turned
    ant = footprint("ANT", 40, 40, w=4, h=2, inst="ant", nets=("A", "B"))
    b = Board(board_geometry([ant], width=60, height=60, extra_nets=["GND"]), edge_margin=margin, keep_going=True)
    b.place(Part("ant"), at=Location(40, 40), rotation=90)
    b.keepout(Path(RECT), "clearance", at=Location(3, 30), rotation=Turned(Part("ant"), 0), why="probe")
    return b


def test_stitch_outside_row_ending_at_an_unkept_side_is_inset_from_it():
    from placemat.values import Edge
    b = _edge_board()
    b.stitch(Net("GND"), "clearance", edge=True, outside=True, hole_to_edge=0.35, pitch=2.0,
             sides=[Edge.EAST], size=0.6, drill=0.3, why="probe")
    plan = b.resolve()
    vias = _vias(plan)
    # the board's north row, y = 25 - 0.5; the unkept west (x = 0) and east (x = 6) sides each hold the end 0.5 in
    assert _row(vias, "y", 24.5) == [0.5, 2.166667, 3.833333, 5.5], [(v.at.x, v.at.y) for v in vias]
    assert not any("left out" in str(f) for f in plan.findings), plan.findings


def test_stitch_outside_every_via_keeps_the_board_edge_clearance():
    from placemat.values import Edge
    b = _edge_board(margin=0.3)             # the 0.5 inset leaves 0.2 of copper to the edge: too close, so left out
    b.stitch(Net("GND"), "clearance", edge=True, outside=True, hole_to_edge=0.35, pitch=2.0,
             sides=[Edge.EAST], size=0.6, drill=0.3, why="probe")
    plan = b.resolve()
    vias = _vias(plan)
    assert vias and all(v.at.x - 0.3 >= 0.3 - 1e-9 for v in vias), [(v.at.x, v.at.y) for v in vias]
    assert any("left out" in str(f) and "board edge" in str(f) for f in plan.findings), plan.findings


def test_stitch_outside_with_sides_notes_which_board_side_each_row_landed_on():
    from placemat.values import Edge
    b = _edge_board()
    b.stitch(Net("GND"), "clearance", edge=True, outside=True, hole_to_edge=0.35, pitch=2.0,
             sides=[Edge.EAST, Edge.WEST], size=0.6, drill=0.3, why="probe")
    said = [str(f) for f in b.resolve().findings if "stitch GND" in str(f) and "board" in str(f)]
    assert any("east side -> board north" in t and "west side -> board south" in t for t in said), said
