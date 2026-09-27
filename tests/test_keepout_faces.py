"""A parts keepout on one face refuses what stands on that face: a through-
hole part's leads stand through to the other, a cell's vias do not. Pure."""
from placemat.board_geometry import CopperItem
from placemat.cutouts import Circle
from placemat.geometry import circle_polygon
from placemat.layout import Board
from placemat.values import Box, Cell, CopperLayer, Face, Location, Part
from tests.fixtures import board_geometry, footprint


def _front_keepout(b):
    b.keepout(Circle(6.0), "front only", at=Location(20, 20), excludes=("parts",), layers=(CopperLayer.F,),
              why="tall parts kept off the front here")


def test_a_cell_with_vias_on_the_back_is_not_refused_by_a_front_keepout():
    ring = circle_polygon(Location(21, 20), 0.3)
    via = CopperItem("via", "A", frozenset([CopperLayer.F, CopperLayer.B]), (ring,), Box.of_points(ring), "mod",
                     drill_mm=0.3)
    fps = [footprint("U1", 20, 20, w=2, h=1, inst="mod.u1", cell="mod", nets=("A", "B"))]
    b = Board(board_geometry(fps, cells=["mod"], copper=[via], width=40, height=40), edge_margin=0.5)
    _front_keepout(b)
    b.place(Cell("mod"), at=Location(20, 20), face=Face.BACK)
    plan = b.resolve()
    assert not [f for f in plan.findings if "front only" in f], plan.findings


def test_a_through_hole_part_on_the_back_is_still_refused_by_a_front_keepout():
    fps = [footprint("J1", 20, 20, w=2, h=1, inst="j1", nets=("A", "B"), through=True)]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5, keep_going=True)
    _front_keepout(b)
    b.place(Part("j1"), at=Location(20, 20), face=Face.BACK)
    plan = b.resolve()
    assert [f for f in plan.findings if "front only" in f]
