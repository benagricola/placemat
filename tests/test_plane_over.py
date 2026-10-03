"""board.plane(net, layers, over=[Part(...), Cell(...)], margin=): a zone
whose outline is the box round the named items' drawn envelopes, grown by
`margin` and clipped to the frame. Pure: synthetic boards."""
import dataclasses

import pytest

from placemat.copper import Zone
from placemat.layout import Board
from placemat.values import Beside, Box, Cell, CopperLayer, Edge, Face, Location, Net, Part
from tests.fixtures import board_geometry, footprint


def _zone_box(plan):
    (z,) = [c for c in plan.copper if isinstance(c, Zone)]
    return Box.of_points(z.points)


def _poly_box(poly):
    b = Box.of_points(poly)
    return (b.left, b.top, b.right, b.bottom)


def _parts():
    """Two parts whose drawn envelope is their body (a fab outline on it)."""
    return [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "GND"), fab=(18, 19, 22, 21)),
            footprint("R1", 0, 0, w=2, h=1, inst="r1", nets=("A", "GND"), fab=(-1, -0.5, 1, 0.5))]


def test_a_plane_over_two_parts_covers_one_placed_beside_the_other():
    b = Board(board_geometry(_parts(), width=60, height=60), edge_margin=1.0)
    b.plane(Net("GND"), layers=(CopperLayer.B,), over=[Part("u1"), Part("r1")], margin=0.5)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.EAST))
    plan = b.resolve()
    u1, r1 = plan.box("u1"), plan.box("r1")
    assert r1.left > u1.right                       # outside u1's box
    want = Box.union([u1, r1]).inflate(0.5)
    got = _zone_box(plan)
    assert (got.left, got.top, got.right, got.bottom) == pytest.approx(
        (want.left, want.top, want.right, want.bottom))


def test_a_plane_over_parts_is_clipped_to_the_frame_less_its_inset():
    fps = [footprint("U1", 3, 30, w=4, h=2, inst="u1", nets=("A", "GND"), fab=(1, 29, 5, 31))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=0.5)
    b.plane(Net("GND"), layers=(CopperLayer.B,), over=[Part("u1")], margin=5.0)
    b.place(Part("u1"), at=Location(3, 30))
    got = _zone_box(b.resolve())
    inset = b.settings.copper_plane_inset
    assert got.left == pytest.approx(inset)
    assert (got.top, got.right, got.bottom) == pytest.approx((24.0, 10.0, 36.0))


def test_over_with_outline_is_refused():
    b = Board(board_geometry(_parts(), width=60, height=60), edge_margin=1.0)
    with pytest.raises(ValueError, match="over=.*outline="):
        b.plane(Net("GND"), layers=(CopperLayer.B,), over=[Part("u1")],
                outline=[Location(0, 0), Location(1, 0), Location(1, 1)])


def test_over_takes_parts_and_cells():
    b = Board(board_geometry(_parts(), width=60, height=60), edge_margin=1.0)
    with pytest.raises(TypeError, match="Part"):
        b.plane(Net("GND"), layers=(CopperLayer.B,), over=[Location(0, 0)])


def test_a_plane_over_a_cell_covers_its_members():
    fps = [footprint("U1", 10, 10, w=4, h=2, inst="k/u1", cell="k", nets=("A", "GND"), fab=(8, 9, 12, 11)),
           footprint("R1", 16, 12, w=2, h=1, inst="k/r1", cell="k", nets=("A", "GND"), fab=(15, 11.5, 17, 12.5))]
    b = Board(board_geometry(fps, cells=("k",), width=60, height=60), edge_margin=1.0)
    b.plane(Net("GND"), layers=(CopperLayer.B,), over=[Cell("k")])
    b.place(Cell("k"), at=Location(30, 30))
    plan = b.resolve()
    want = plan.box("k")                            # the union of its members' bodies
    got = _zone_box(plan)
    assert (got.left, got.top, got.right, got.bottom) == pytest.approx(
        (want.left, want.top, want.right, want.bottom))


def test_a_plane_over_a_part_covers_its_copper_graphics():
    winding = (CopperLayer.IN1, ((12.0, 17.0), (19.0, 17.0), (19.0, 23.0), (12.0, 23.0)))
    part = dataclasses.replace(footprint("U1", 20.0, 20.0, w=4.0, h=2.0, inst="u1", nets=("A", "GND")),
                               copper=(winding,))
    b = Board(board_geometry([part], width=60.0, height=60.0), edge_margin=0.5)
    b.plane(Net("GND"), layers=(CopperLayer.B,), over=[Part("u1")])
    b.place(Part("u1"), at=Location(25.0, 20.0))
    got = _zone_box(b.resolve())
    assert (got.left, got.top, got.right, got.bottom) == pytest.approx((17.0, 17.0, 26.9, 23.0), abs=0.01)


@pytest.mark.parametrize("rotation,face", [(90, Face.FRONT), (0, Face.BACK), (270, Face.BACK)])
def test_a_plane_over_a_turned_part_takes_the_region_its_keepout_takes(rotation, face):
    fps = [footprint("U1", 20.0, 20.0, w=4.0, h=2.0, inst="u1", nets=("A", "GND"),
                     silk_boxes=[(16.0, 19.0, 22.0, 21.0)])]
    b = Board(board_geometry(fps, width=60.0, height=60.0), edge_margin=0.5)
    b.keepout(Part("u1"), "clr", excludes=("fill",), why="the region the plane is compared with")
    b.plane(Net("GND"), layers=(CopperLayer.B,), over=[Part("u1")])
    b.place(Part("u1"), at=Location(30.0, 25.0), rotation=rotation, face=face)
    plan = b.resolve()
    got = _zone_box(plan)
    assert (got.left, got.top, got.right, got.bottom) == pytest.approx(_poly_box(plan.keepouts["clr"].poly),
                                                                      abs=0.01)


def test_a_plane_over_a_turned_cell_takes_the_region_its_keepout_takes():
    fps = [footprint("U1", 10, 10, w=4, h=2, inst="k/u1", cell="k", nets=("A", "GND"), fab=(8, 9, 12, 11)),
           footprint("R1", 16, 12, w=2, h=1, inst="k/r1", cell="k", nets=("A", "GND"), fab=(15, 11.5, 17, 12.5))]
    b = Board(board_geometry(fps, cells=("k",), width=60, height=60), edge_margin=1.0)
    b.keepout(Cell("k"), "clr", excludes=("fill",), why="the region the plane is compared with")
    b.plane(Net("GND"), layers=(CopperLayer.B,), over=[Cell("k")])
    b.place(Cell("k"), at=Location(30, 30), rotation=90)
    plan = b.resolve()
    got = _zone_box(plan)
    assert (got.left, got.top, got.right, got.bottom) == pytest.approx(_poly_box(plan.keepouts["clr"].poly),
                                                                      abs=0.01)
    assert got.height > got.width                   # turned: the cell's long side runs north-south


def test_a_plane_over_a_cell_and_a_part_beside_it_covers_both():
    fps = [footprint("U1", 10, 10, w=4, h=2, inst="k/u1", cell="k", nets=("A", "GND"), fab=(8, 9, 12, 11)),
           footprint("R1", 16, 12, w=2, h=1, inst="k/r1", cell="k", nets=("A", "GND"), fab=(15, 11.5, 17, 12.5)),
           footprint("C1", 0, 0, w=2, h=1, inst="c1", nets=("A", "GND"), fab=(-1, -0.5, 1, 0.5))]
    b = Board(board_geometry(fps, cells=("k",), width=60, height=60), edge_margin=1.0)
    b.plane(Net("GND"), layers=(CopperLayer.B,), over=[Cell("k"), Part("c1")])
    b.place(Cell("k"), at=Location(30, 30))
    b.place(Part("c1"), at=Beside(Cell("k"), Edge.SOUTH))
    plan = b.resolve()
    want = Box.union([plan.box("k"), plan.box("c1")])
    # south of the cell's own shapes: it stands under U1, where the cell's box is lower for R1 further east
    u1 = Box.union([sh.box for sh in plan.occupancy.items["U1"].shapes])
    assert plan.box("c1").top > u1.bottom
    got = _zone_box(plan)
    assert (got.left, got.top, got.right, got.bottom) == pytest.approx(
        (want.left, want.top, want.right, want.bottom))


def test_a_plane_over_a_cell_the_script_never_places_covers_it_where_it_stands():
    """A cell left where the generator put it: the plane reads its members
    there, rather than failing for want of a placement the script never made."""
    fps = [footprint("U1", 10, 10, w=4, h=2, inst="k/u1", cell="k", nets=("A", "GND"), fab=(8, 9, 12, 11)),
           footprint("R1", 16, 12, w=2, h=1, inst="k/r1", cell="k", nets=("A", "GND"), fab=(15, 11.5, 17, 12.5))]
    b = Board(board_geometry(fps, cells=("k",), width=60, height=60), edge_margin=1.0, keep_going=True)
    b.plane(Net("GND"), layers=(CopperLayer.B,), over=[Cell("k")])
    plan = b.resolve()
    got = _zone_box(plan)
    assert (got.left, got.top, got.right, got.bottom) == pytest.approx((8.0, 9.0, 17.0, 12.5))
