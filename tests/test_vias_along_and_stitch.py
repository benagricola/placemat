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
