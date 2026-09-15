"""A board of any shape: an outline of straight legs and arcs, the stretches
of its edge picked by which way they face, and parts placed along them -
including a curved one, where each part turns with the edge."""
import math

import pytest

from placemat.copper import Zone
from placemat.layout import Board
from placemat.outline import Arc, Outline
from placemat.values import (Along, CopperLayer, Edge, Fraction, Location, Net, OnEdge, Part, Polar, Priority)
from tests.fixtures import board_geometry, footprint

SHAPES = {"j1": ("J1", 6.0, 4.0), "r1": ("R1", 2.0, 1.2), "u1": ("U1", 4.0, 4.0),
          "d1": ("D1", 1.6, 0.8), "d2": ("D2", 1.6, 0.8), "d3": ("D3", 1.6, 0.8)}

# Ben's shape: a square with a rounded top. The arc passes through (20, 0),
# so it is the semicircle of radius 20 over the square's top half.
ROUNDED_TOP = [(0.0, 40.0), (0.0, 20.0), Arc(to=(40.0, 20.0), via=(20.0, 0.0)), (40.0, 40.0)]


def make_board(*insts, margin=0.5, keep_going=False):
    fps = [footprint(SHAPES[i][0], 60.0, 3.0 + n * 6.0, w=SHAPES[i][1], h=SHAPES[i][2], inst=i, nets=("M", "GND"))
           for n, i in enumerate(insts)]
    return Board(board_geometry(fps, width=80, height=60), edge_margin=margin, keep_going=keep_going)


def corners(box):
    return [Location(box.left, box.top), Location(box.right, box.top),
            Location(box.right, box.bottom), Location(box.left, box.bottom)]


def reach_of(plan, ref):
    g = plan.occupancy.items[ref]
    return g.reach or g.body


# An arc is flattened to chords for the arithmetic, and a chord lies inside the
# curve, so a part held at the keep-in from the chords is up to the flattening
# tolerance further in than the true arc. The fab still gets the real arc.
AT_KEEP_IN = 0.03


def test_a_shaped_board_is_a_path_of_legs_and_arcs():
    b = make_board()
    b.outline(ROUNDED_TOP)
    plan = b.resolve()
    assert isinstance(plan.shape, Outline)
    assert (b.width, b.height) == (40.0, 40.0)
    assert b.centre == Location(20.0, 20.0)                     # the middle of the box round it
    assert b.centroid.y > 20.0                                  # the area sits low: the top is a half circle
    assert plan.shape.area == pytest.approx(40.0 * 20.0 + math.pi * 400.0 / 2.0, rel=0.01)


def test_a_stretch_of_the_edge_is_chosen_by_which_way_it_faces():
    b = make_board()
    b.outline(ROUNDED_TOP)
    top = b.edge(facing=Edge.NORTH)
    assert not top.straight                                     # the rounded top, as one run
    assert top.length == pytest.approx(math.pi * 20.0 / 2.0, rel=0.02)
    assert top.facing == pytest.approx(0.0, abs=0.5)
    (foot,) = b.edges(facing=Edge.SOUTH)
    assert foot.straight and foot.length == pytest.approx(40.0)
    # The right-hand side and the eastern quarter of the arc face the same way
    # and run into each other, so they come back as ONE run: a rounded corner
    # belongs to the side it flows into.
    (east,) = b.edges(facing=Edge.EAST)
    assert east.length == pytest.approx(20.0 + math.pi * 20.0 / 4.0, rel=0.02) and not east.straight
    flat = b.edge(facing=Edge.EAST, within=2.0)          # narrowed: the straight part alone
    assert flat.straight and flat.length == pytest.approx(20.0)


def test_a_part_on_a_curved_run_sits_at_the_keep_in_and_faces_out():
    b = make_board("j1")
    b.outline(ROUNDED_TOP)
    top = b.edge(facing=Edge.NORTH)
    b.place(Part("j1"), at=OnEdge(top, along=Along.MID))
    plan = b.resolve()
    assert plan.findings == []
    assert plan.step("j1").priority is Priority.EDGE
    far = max(c.distance(Location(20.0, 20.0)) for c in corners(reach_of(plan, "J1")))
    assert far == pytest.approx(19.5, abs=AT_KEEP_IN) and far <= 19.5   # the arc holds its furthest corner at the keep-in
    assert plan.box("j1").center.x == pytest.approx(20.0, abs=0.05)
    assert plan.placement("j1").rotation == pytest.approx(180.0, abs=0.5)   # facing north, at the apex


def test_a_part_may_sit_a_length_along_a_run_or_a_fraction_of_it():
    b = make_board("d1")
    b.outline(ROUNDED_TOP)
    top = b.edge(facing=Edge.NORTH)
    b.place(Part("d1"), at=OnEdge(top, along=Fraction(0.25)))
    plan = b.resolve()
    where, facing = top.at(top.length * 0.25)
    assert plan.findings == []
    far = max(c.distance(Location(20.0, 20.0)) for c in corners(reach_of(plan, "D1")))
    assert far == pytest.approx(19.5, abs=AT_KEEP_IN) and far <= 19.5    # at the keep-in a quarter of the way along
    assert plan.box("d1").center.distance(where) < 2.0                   # just inside the board, on that normal
    assert plan.placement("d1").rotation == pytest.approx((180.0 - facing) % 360.0, abs=1.0)


def test_a_row_runs_along_a_curved_edge_turning_with_it():
    b = make_board("d1", "d2", "d3")
    b.outline(ROUNDED_TOP)
    top = b.edge(facing=Edge.NORTH)
    row = b.row([Part("d1"), Part("d2"), Part("d3")], top, align="center")
    plan = b.resolve()
    assert plan.findings == []
    assert row.alongs == sorted(row.alongs)                     # in order along the run
    # three 1.8 mm claims take MORE than 5.4 mm of a curve: they sit inboard of
    # it, where the same angle spans less of the edge, so the row opens out.
    assert 3 * 1.8 < row.length < 3 * 1.8 * 1.15
    rots = [plan.placement(k).rotation for k in ("d1", "d2", "d3")]
    assert rots[0] != rots[1] != rots[2]                        # each turned to the edge where it sits
    for ref in ("D1", "D2", "D3"):
        far = max(c.distance(Location(20.0, 20.0)) for c in corners(reach_of(plan, ref)))
        assert far == pytest.approx(19.5, abs=AT_KEEP_IN) and far <= 19.5
    middle = plan.box("d2").center
    assert middle.x == pytest.approx(20.0, abs=0.3)             # centred on the run


def test_a_free_item_slides_along_a_run():
    b = make_board("j1", "u1")
    b.outline(ROUNDED_TOP)
    top = b.edge(facing=Edge.NORTH)
    b.place(Part("j1"), at=OnEdge(top, along=Along.MID))
    b.place(Part("u1"), at=OnEdge(top))
    plan = b.resolve()
    assert plan.findings == []
    assert "along the run" in plan.step("u1").note
    assert plan.box("u1").center.distance(plan.box("j1").center) > 4.0


def test_a_cutout_is_a_hole_the_board_keeps_clear():
    b = make_board("u1", keep_going=True)
    b.outline(ROUNDED_TOP, holes=[[(16.0, 26.0), (24.0, 26.0), (24.0, 34.0), (16.0, 34.0)]])
    b.place(Part("u1"), at=Location(18.0, 28.0))                # over the cutout
    plan = b.resolve()
    assert any("cutout" in f for f in plan.findings), plan.findings


def test_a_shaped_board_takes_coordinates_and_polar_places_too():
    b = make_board("d1", "d2")
    b.outline(ROUNDED_TOP)
    b.place(Part("d1"), at=Location(20.0, 30.0))
    b.place(Part("d2"), at=Polar(8.0, Edge.SOUTH))              # about the board's centre
    plan = b.resolve()
    assert plan.findings == []
    assert plan.box("d2").center == Location(20.0, 28.0)


def test_a_shaped_board_refuses_a_named_edge():
    b = make_board("d1")
    b.outline(ROUNDED_TOP)
    with pytest.raises(ValueError, match="chosen"):
        b.place(Part("d1"), at=OnEdge(Edge.NORTH))
    with pytest.raises(ValueError, match="chosen"):
        b.row([Part("d1")], Edge.NORTH)


def test_the_plane_of_a_shaped_board_follows_its_outline():
    b = make_board("d1")
    b.outline(ROUNDED_TOP)
    b.plane(Net("GND"), layers=(CopperLayer.B,), inset=0.4)
    plan = b.resolve()
    (zone,) = [op for op in plan.copper if isinstance(op, Zone)]
    assert min(y for _, y in zone.points) == pytest.approx(0.4, abs=0.05)      # the arc, pulled in
    assert max(y for _, y in zone.points) == pytest.approx(39.6, abs=0.05)
    over = [p for p in zone.points if math.hypot(p[0] - 20.0, p[1] - 20.0) > 19.65 and p[1] < 20.0]
    assert not over                                                            # nothing outside the inset arc


def test_a_run_may_be_read_off_a_round_board_too():
    """A rim is an edge like any other: the quarter of it facing north is a
    run, so the same row works on a disc."""
    b = make_board("d1", "d2")
    b.disc(diameter=40.0)
    north = b.edge(facing=Edge.NORTH)
    assert not north.straight and north.length == pytest.approx(math.pi * 20.0 / 2.0, rel=0.02)
    b.row([Part("d1"), Part("d2")], north, align="center")
    plan = b.resolve()
    assert plan.findings == []
    for ref in ("D1", "D2"):
        far = max(c.distance(Location(20.0, 20.0)) for c in corners(reach_of(plan, ref)))
        assert far == pytest.approx(19.5, abs=AT_KEEP_IN) and far <= 19.5
